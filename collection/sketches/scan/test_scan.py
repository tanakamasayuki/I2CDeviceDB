"""Drive the Address Sweep probe.

scan's meaningful result is the MCU-discovered address map (presence), judged by
``Wire.endTransmission()`` — not the noise-prone LA decode. The LA capture +
decode still run (uniform pipeline) but are transient and not persisted.

Order: confirm probe is up -> arm sigrok -> RUN -> stop on ALL_DONE.
If the MCU finds no devices, stop here: capturing chip probes against absent
devices is pointless.
"""

import re

import pytest

FOUND_RE = re.compile(rb"FOUND (0x[0-9A-Fa-f]{2})")
DONE_RE = re.compile(rb"ALL_DONE found=(\d+)")


@pytest.mark.probe("scan")
def test_address_sweep(dut, wait_ready, sigrok_capture):
    wait_ready(dut)

    cap = sigrok_capture(signals=["UART_TX", "SCL", "SDA"], out="scan.sr")
    try:
        dut.write("RUN\n")
        dut.expect(DONE_RE, timeout=30)
        before = dut.pexpect_proc.before  # bytes emitted before ALL_DONE
    finally:
        cap.stop()

    found = sorted({m.group(1).decode() for m in FOUND_RE.finditer(before)})
    print(f"scan: MCU found {len(found)} device(s): {found}")

    # Uniform pipeline: LA capture -> decode still runs (transient, not persisted).
    # scan's LA data is noise-prone on a floating bus: the decoded transaction
    # count is unstable (e.g. 128 vs 120 across runs) and NOT meaningful for
    # presence, so we only confirm the pipeline produced output, never a count.
    assert cap.path.exists() and cap.path.stat().st_size > 0
    decoded = cap.decode()
    n = len(decoded.read_text(encoding="utf-8").splitlines())
    print(f"scan: LA decoded {n} transaction(s) (transient; not used for presence)")

    # Presence gate: the MCU is the authority. Nothing on the bus -> stop here.
    if not found:
        pytest.fail(
            "scan found no I2C devices (MCU saw all-NACK). Check wiring, power, "
            "pull-ups, GPIO (TEST_I2C_SDA / TEST_I2C_SCL), and that a unit is "
            "connected.",
            pytrace=False,
        )
