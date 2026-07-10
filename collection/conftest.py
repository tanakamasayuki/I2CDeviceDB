"""Collection harness fixtures.

pytest is used as a *collection orchestrator*, not a pass/fail judge: it flashes
an Arduino probe, brackets a sigrok capture around the run (marker-driven, via
``--continuous`` + SIGINT), and leaves a ``.sr`` in ``_staging/``. Decode /
content-hash naming / persistence into ``captures/`` is a separate offline step.

See docs/COLLECTION.ja.md.
"""

from __future__ import annotations

import json
import os
import pty
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

COLLECTION_ROOT = Path(__file__).parent
REPO_ROOT = COLLECTION_ROOT.parent
STAGING_DIR = COLLECTION_ROOT / "_staging"
SCAN_FAILED = pytest.StashKey[bool]()


def pytest_configure(config: pytest.Config) -> None:
    config.stash[SCAN_FAILED] = False


@pytest.fixture(scope="session")
def staging_session(request: pytest.FixtureRequest) -> Path:
    """Prepare staging once, and only for a run that actually captures.

    Outputs (.sr / .jsontrace.json / logs) are left in place after a run for
    inspection and cleared when the next hardware capture run requests this
    fixture. Unit tests and --collect-only therefore never destroy the last
    run's artifacts. The durable store is ``captures/``, not ``_staging/``.
    """
    if request.config.getoption("collectonly", False):
        return STAGING_DIR
    if STAGING_DIR.exists():
        shutil.rmtree(STAGING_DIR)
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    return STAGING_DIR


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


def decoded_artifact_path(capture: Path) -> Path:
    """Return the decoded sibling for a raw ``.sr`` capture."""
    return capture.with_name(f"{capture.stem}.decoded.jsonl")


class SigrokCapture:
    def __init__(self, proc: subprocess.Popen, path: Path, log_fh, log_path: Path,
                 stdin_fd: int):
        self.proc = proc
        self.path = path
        self._log_fh = log_fh
        self.log_path = log_path
        self._stdin_fd = stdin_fd  # pty master; kept open so --continuous does not EOF
        self._events: list[dict] | None = None
        self._timing_features: list[dict] | None = None

    def stop(self) -> None:
        """Stop a --continuous capture cleanly with SIGINT (flushes the .sr)."""
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGINT)
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        if self._stdin_fd is not None:
            os.close(self._stdin_fd)
            self._stdin_fd = None
        if not self._log_fh.closed:
            self._log_fh.close()

    def decode_jsontrace(self, out: Path | None = None) -> Path:
        """Decode SCL/SDA (+UART_TX markers) to Google Trace JSON.

        Transient intermediate (not persisted): i2c and uart share one timebase
        here, which is what lets the offline decoder correlate markers to
        transactions (Level4). See docs/DATA_MODEL.ja.md.
        """
        out = out or self.path.with_suffix(".jsontrace.json")
        decoders = [
            "-P", "uart:rx=UART_TX:baudrate=115200:format=hex",
            "-P", "i2c:scl=SCL:sda=SDA",
        ]
        cmd = [
            _sigrok_cli(), "-i", str(self.path),
            *decoders, "--protocol-decoder-jsontrace",
        ]
        with out.open("wb") as fh:
            subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=fh,
                           stderr=subprocess.PIPE, check=True)
        return out

    def decode(self, out: Path | None = None, extract_clock_stretch: bool = False) -> Path:
        """Compact decode to JSONL (Level2 + Level4) via tools/decode.

        Uniform across probes: every capture produces a ``.decoded.jsonl`` here.
        Whether it is persisted into captures/ is a separate policy (scan is
        not persisted); this only writes to the transient _staging/.
        """
        trace = self.decode_jsontrace()
        decoder = _load_decoder()
        events = decoder.load_events(trace)
        self._events = events
        txns = decoder.parse_transactions(events)
        decoder.annotate(txns, decoder.parse_markers(events))
        if extract_clock_stretch:
            self._timing_features = _load_timing().clock_stretch_features(
                self.path, decoder.parse_markers(events), txns
            )
        records = decoder.to_records(txns)
        out = out or decoded_artifact_path(self.path)
        out.write_text(
            "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in records),
            encoding="utf-8",
        )
        return out

    def clock_stretch_features(self) -> list[dict]:
        """Extract raw SCL-low timing after ``decode()`` establishes markers."""
        if self._events is None:
            raise RuntimeError("decode() must run before timing extraction")
        if self._timing_features is not None:
            return self._timing_features
        decoder = _load_decoder()
        self._timing_features = _load_timing().clock_stretch_features(
            self.path, decoder.parse_markers(self._events)
        )
        return self._timing_features


def _load_decoder():
    """Import the offline decoder from tools/ (repo root, outside this uv project)."""
    tools_dir = str(REPO_ROOT / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    import decode  # tools/decode.py

    return decode


def _load_timing():
    """Import raw-waveform timing extraction from tools/."""
    tools_dir = str(REPO_ROOT / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    import timing  # tools/timing.py

    return timing


@pytest.fixture
def sigrok_capture(staging_session: Path):
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

        # sigrok-cli --continuous only keeps running while stdin is an open tty;
        # a non-tty / EOF stdin (pytest's /dev/null under fd-capture, or DEVNULL)
        # makes it exit immediately with rc=0. Give it a pty slave (isatty True)
        # and keep the master open so it never sees EOF. stdout/stderr go to a
        # log file (not the terminal) so pytest's captured output isn't garbled.
        log_path = path.with_suffix(".sigrok.log")
        log_fh = log_path.open("wb")
        master_fd, slave_fd = pty.openpty()
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=slave_fd,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        finally:
            os.close(slave_fd)  # child holds its own copy; parent keeps master
        cap = SigrokCapture(proc, path, log_fh, log_path, master_fd)
        started.append(cap)

        # Let the device arm before the probe emits traffic, or we clip the run.
        time.sleep(arm_delay)
        if proc.poll() is not None:
            log_fh.flush()
            log = log_path.read_text(errors="replace").strip()
            raise RuntimeError(
                f"sigrok-cli exited early (rc={proc.returncode}):\n"
                f"  {' '.join(cmd)}\n{log or '(no output)'}"
            )
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
             "product needs (scan + characterization + supporting libraries).",
    )


def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@pytest.fixture
def expected_product_addresses(request: pytest.FixtureRequest) -> set[str]:
    """Expected 7-bit addresses from the selected product BOM."""
    product_key = request.config.getoption("product")
    if not product_key:
        return set()
    product = _load_yaml(REPO_ROOT / "products" / f"{product_key}.yaml")
    return {
        component["addr"].upper().replace("0X", "0x")
        for component in product.get("components", [])
        if component.get("addr")
    }


def derive_probe_keys(product_key: str) -> set[str]:
    """Derive scan + available characterization/library probes for a product.

    chip list comes from products/<key>.yaml components; libraries from every
    libraries/*.yaml whose supports.chips includes that chip. A characterization
    probe is selected when sketches/<chip>__characterize exists. Mirrors the
    coverage-derivation logic, so there is no per-product command table to drift.
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
    for chip in chips:
        key = f"{chip}__characterize"
        if (COLLECTION_ROOT / "sketches" / key).is_dir():
            keys.add(key)
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


def _probe_sort_key(item: pytest.Item) -> tuple[int, str]:
    """Always place the MCU address scan before other collected tests."""
    return (0 if _probe_marker(item) == "scan" else 1, item.nodeid)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    product_key = config.getoption("product")
    if not product_key:
        # The unscoped hardware command must keep the same safety gate as
        # --product: scan first, then skip chip probes if scan fails.
        items.sort(key=_probe_sort_key)
        return

    wanted = derive_probe_keys(product_key)
    selected, deselected = [], []
    for item in items:
        key = _probe_marker(item)
        (selected if key in wanted else deselected).append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
    # Presence is the safety gate and must run before any chip traffic.
    selected.sort(key=_probe_sort_key)
    items[:] = selected


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    outcome = yield
    report = outcome.get_result()
    if (
        _probe_marker(item) == "scan"
        and report.when == "call"
        and report.failed
    ):
        item.config.stash[SCAN_FAILED] = True


def pytest_runtest_setup(item: pytest.Item) -> None:
    if _probe_marker(item) != "scan" and item.config.stash[SCAN_FAILED]:
        pytest.skip("address scan failed; chip probes are gated for this run")


# --------------------------------------------------------------------------- #
# structured probe events + observation candidates
# --------------------------------------------------------------------------- #
EVENT_RE = re.compile(rb"EVENT (\{[^\r\n]+\})")


def parse_probe_events(serial_output: bytes) -> list[dict]:
    """Extract one-line JSON EVENT records emitted by a probe."""
    events: list[dict] = []
    for match in EVENT_RE.finditer(serial_output):
        try:
            event = json.loads(match.group(1))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(f"invalid probe EVENT: {match.group(1)!r}") from exc
        if not isinstance(event, dict) or not event.get("type"):
            raise ValueError(f"probe EVENT must be an object with type: {event!r}")
        events.append(event)
    return events


def _relative_artifact(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


@pytest.fixture
def observation_candidate(request: pytest.FixtureRequest):
    """Write a provisional observation JSON beside staging capture artifacts.

    This is deliberately a staging artifact, not the curated observations/
    schema. It preserves enough input/result/provenance to curate after the
    first hardware runs without prematurely freezing that schema.
    """
    product = request.config.getoption("product") or os.getenv("TEST_PRODUCT", "").strip()
    specimen = os.getenv("TEST_SPECIMEN_ID", "").strip()
    if not product:
        raise pytest.UsageError(
            "characterization requires --product or TEST_PRODUCT for provenance"
        )
    if not specimen:
        raise pytest.UsageError(
            "characterization requires TEST_SPECIMEN_ID (anonymous bench-local ID)"
        )

    def _write(*, target: str, probe: str, scenario: str, events: list[dict],
               capture: Path, decoded: Path, condition: str = "nominal",
               timing_features: list[dict] | None = None) -> Path:
        rate = os.getenv("SIGROK_SAMPLERATE", "8MHz")
        bus_hz = int(os.getenv("TEST_I2C_BUS_HZ", "100000"))
        record = {
            "schema": "i2cdevicedb/observation-candidate/v0",
            "kind": "characterization",
            "target": target,
            "probe": probe,
            "scenario": scenario,
            "condition": condition,
            "events": events,
            "artifacts": {
                "raw": _relative_artifact(capture),
                "decoded": _relative_artifact(decoded),
            },
            "provenance": {
                "product": product,
                "specimen_id": specimen,
                "bus_speed_hz": bus_hz,
                "sigrok_samplerate": rate,
                "supply_voltage_v": os.getenv("TEST_SUPPLY_VOLTAGE_V") or None,
                "pullup_ohms": os.getenv("TEST_PULLUP_OHMS") or None,
                "fqbn": "esp32:esp32:esp32s3",
                "platform": "esp32:esp32@3.3.10",
            },
        }
        if timing_features:
            record["timing_features"] = timing_features
        out = STAGING_DIR / f"{probe}.observation.json"
        out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        return out

    return _write
