"""Drive the Address Sweep probe and capture it.

Order matters:
1. confirm the probe is up (poll READY; robust to slow init / missed banner);
2. arm sigrok (--continuous) — nothing worth capturing has happened yet;
3. trigger the sweep so all bus traffic falls inside the armed window;
4. stop on the ALL_DONE sentinel.
"""

import pytest


@pytest.mark.probe("scan")
def test_address_sweep(dut, wait_ready, sigrok_capture):
    wait_ready(dut)

    cap = sigrok_capture(signals=["UART_TX", "SCL", "SDA"], out="scan.sr")
    try:
        dut.write("RUN\n")
        dut.expect_exact("ALL_DONE", timeout=30)
    finally:
        cap.stop()

    assert cap.path.exists() and cap.path.stat().st_size > 0

    # Decode is a transient intermediate; assert it runs end to end.
    trace = cap.decode_jsontrace()
    assert trace.exists() and trace.stat().st_size > 0
