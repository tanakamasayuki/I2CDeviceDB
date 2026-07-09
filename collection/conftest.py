"""Collection harness fixtures.

pytest is used as a *collection orchestrator*, not a pass/fail judge: it flashes
an Arduino probe, brackets a sigrok capture around the run (marker-driven, via
``--continuous`` + SIGINT), and leaves a ``.sr`` in ``_staging/``. Decode /
content-hash naming / persistence into ``captures/`` is a separate offline step.

See docs/COLLECTION.ja.md.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from pathlib import Path

import pytest
import yaml

COLLECTION_ROOT = Path(__file__).parent
REPO_ROOT = COLLECTION_ROOT.parent
STAGING_DIR = COLLECTION_ROOT / "_staging"


# --------------------------------------------------------------------------- #
# probe readiness
# --------------------------------------------------------------------------- #
@pytest.fixture
def wait_ready():
    """Poll a probe until it answers ``READY`` on the control serial.

    Actively re-requests READY instead of waiting for the one-shot boot banner,
    so a slow init or a banner emitted before the serial port was open does not
    get lost. Probes respond to a ``READY`` command in their loop().
    """
    from pexpect import EOF, TIMEOUT

    ready_re = re.compile(rb"READY\b.*")

    def _wait(dut, attempts: int = 30, interval: float = 1.0):
        for _ in range(attempts):
            dut.write("READY\n")
            try:
                dut.expect(ready_re, timeout=interval)
                return
            except (TIMEOUT, EOF):
                continue
        pytest.fail(
            "probe did not report READY (check serial port, flashing, power)",
            pytrace=False,
        )

    return _wait


# --------------------------------------------------------------------------- #
# sigrok capture
# --------------------------------------------------------------------------- #
def _sigrok_cli() -> str:
    return os.getenv("SIGROK_CLI", "sigrok-cli")


def _channel_map() -> dict[str, str]:
    """signal name -> physical channel, from SIGROK_CH_<SIGNAL> env vars."""
    prefix = "SIGROK_CH_"
    return {
        name[len(prefix):]: chan
        for name, chan in os.environ.items()
        if name.startswith(prefix) and chan.strip()
    }


def _compose_channels(signals: list[str]) -> str:
    """Build the --channels arg for just the signals a probe needs.

    Signal names (UART_TX / SCL / SDA) are the stable interface: they get baked
    into the .sr as channel labels and the decoders key off them, so the
    physical Dn assignment only matters at capture time.
    """
    chmap = _channel_map()
    missing = [s for s in signals if s not in chmap]
    if missing:
        raise pytest.UsageError(
            f"no channel mapping for signal(s) {missing}; "
            f"set SIGROK_CH_<SIGNAL> in .env (have: {sorted(chmap)})"
        )
    return ",".join(f"{chmap[s]}={s}" for s in signals)


class SigrokCapture:
    def __init__(self, proc: subprocess.Popen, path: Path):
        self.proc = proc
        self.path = path

    def stop(self) -> None:
        """Stop a --continuous capture cleanly with SIGINT (flushes the .sr)."""
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGINT)
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()

    def decode_jsontrace(self, out: Path | None = None) -> Path:
        """Decode SCL/SDA (+UART_TX markers) to Google Trace JSON.

        Transient intermediate (not persisted): i2c and uart share one timebase
        here, which is what lets the offline decoder correlate markers to
        transactions (Level4). See docs/DATA_MODEL.ja.md.
        """
        out = out or self.path.with_suffix(".jsontrace.json")
        decoders = [
            "-P", "uart:rx=UART_TX:baudrate=115200:format=ascii",
            "-P", "i2c:scl=SCL:sda=SDA",
        ]
        cmd = [
            _sigrok_cli(), "-i", str(self.path),
            *decoders, "--protocol-decoder-jsontrace",
        ]
        with out.open("wb") as fh:
            subprocess.run(cmd, stdout=fh, check=True)
        return out


@pytest.fixture
def sigrok_capture():
    """Factory: start a --continuous capture; teardown SIGINTs any still running."""
    started: list[SigrokCapture] = []

    def _start(signals: list[str], out: str, samplerate: str | None = None,
               arm_delay: float = 1.0) -> SigrokCapture:
        STAGING_DIR.mkdir(exist_ok=True)
        path = STAGING_DIR / out

        driver = os.getenv("SIGROK_DRIVER", "fx2lafw")
        conn = os.getenv("SIGROK_CONN", "").strip()
        rate = samplerate or os.getenv("SIGROK_SAMPLERATE", "8MHz")
        driver_spec = f"{driver}:conn={conn}" if conn else driver

        cmd = [
            _sigrok_cli(),
            "--driver", driver_spec,
            "--config", f"samplerate={rate}",
            "--channels", _compose_channels(signals),
            "--continuous",
            "--output-file", str(path),
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        cap = SigrokCapture(proc, path)
        started.append(cap)

        # Let the device arm before the probe emits traffic, or we clip the run.
        time.sleep(arm_delay)
        if proc.poll() is not None:
            log = proc.stdout.read().decode(errors="replace") if proc.stdout else ""
            raise RuntimeError(f"sigrok-cli exited early:\n{' '.join(cmd)}\n{log}")
        return cap

    yield _start

    for cap in started:
        cap.stop()


# --------------------------------------------------------------------------- #
# --product: derive the probe set from data, select matching tests
# --------------------------------------------------------------------------- #
def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("i2cdevicedb")
    group.addoption(
        "--product",
        action="store",
        default=None,
        help="Product key (products/<key>.yaml). Selects only the probes that "
             "product needs (scan + each chip x supporting library).",
    )


def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def derive_probe_keys(product_key: str) -> set[str]:
    """probe set for a product = {"scan"} + {"<chip>__<library>"}.

    chip list comes from products/<key>.yaml components; libraries from every
    libraries/*.yaml whose supports.chips includes that chip. Mirrors the
    coverage-derivation logic (docs/COLLECTION.ja.md), so there is no hand-kept
    command table to drift.
    """
    product_path = REPO_ROOT / "products" / f"{product_key}.yaml"
    if not product_path.exists():
        available = sorted(p.stem for p in (REPO_ROOT / "products").glob("*.yaml"))
        raise pytest.UsageError(
            f"--product '{product_key}' not found ({product_path}). "
            f"Available: {available}"
        )
    product = _load_yaml(product_path)
    chips = {c["chip"] for c in product.get("components", []) if c.get("chip")}

    keys = {"scan"}
    for lib_path in sorted((REPO_ROOT / "libraries").glob("*.yaml")):
        lib = _load_yaml(lib_path)
        lib_key = lib.get("key", lib_path.stem)
        supported = set((lib.get("supports") or {}).get("chips", []))
        for chip in chips & supported:
            keys.add(f"{chip}__{lib_key}")
    return keys


def _probe_marker(item: pytest.Item) -> str | None:
    marker = item.get_closest_marker("probe")
    return marker.args[0] if marker and marker.args else None


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    product_key = config.getoption("product")
    if not product_key:
        return

    wanted = derive_probe_keys(product_key)
    selected, deselected = [], []
    for item in items:
        key = _probe_marker(item)
        (selected if key in wanted else deselected).append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected
