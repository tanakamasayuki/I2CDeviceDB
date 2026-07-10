"""Capture the safe P0 QMP6988 characterization sequence."""

import re

import pytest

from conftest import parse_probe_events

DONE_RE = re.compile(rb"ALL_DONE target=qmp6988 ok=([01])")


@pytest.mark.probe("qmp6988__characterize")
def test_qmp6988_characterize(
    dut, wait_ready, sigrok_capture, observation_candidate
):
    wait_ready(dut)
    cap = sigrok_capture(
        signals=["UART_TX", "SCL", "SDA"], out="qmp6988__characterize.sr"
    )
    try:
        dut.write("RUN\n")
        dut.expect(DONE_RE, timeout=45)
        serial_output = dut.pexpect_proc.before
        ok = dut.pexpect_proc.match.group(1) == b"1"
    finally:
        cap.stop()

    events = parse_probe_events(serial_output)
    assert events, "QMP6988 probe emitted no structured EVENT records"
    assert any(e.get("type") == "presence" and e.get("ack") for e in events)
    assert any(
        e.get("type") == "reset_identity" and e.get("chip_id_ok") for e in events
    )
    assert any(e.get("type") == "calibration" for e in events)
    assert any(e.get("type") == "forced_measurement" for e in events)
    assert sum(e.get("type") == "normal_sample" for e in events) == 10
    events.append({"type": "probe_summary", "ok": ok})

    assert cap.path.exists() and cap.path.stat().st_size > 0
    decoded = cap.decode()
    observation = observation_candidate(
        target="qmp6988",
        probe="qmp6988__characterize",
        scenario="qmp6988/p0",
        events=events,
        capture=cap.path,
        decoded=decoded,
    )
    print(f"staged observation candidate: {observation}")
