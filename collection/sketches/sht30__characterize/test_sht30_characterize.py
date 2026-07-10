"""Capture the safe P0 SHT30 characterization sequence."""

import re

import pytest

from conftest import parse_probe_events

DONE_RE = re.compile(rb"ALL_DONE target=sht30 ok=([01])")


@pytest.mark.probe("sht30__characterize")
def test_sht30_characterize(
    dut, wait_ready, sigrok_capture, observation_candidate
):
    wait_ready(dut)
    cap = sigrok_capture(
        signals=["UART_TX", "SCL", "SDA"], out="sht30__characterize.sr"
    )
    try:
        dut.write("RUN\n")
        dut.expect(DONE_RE, timeout=45)
        serial_output = dut.pexpect_proc.before
        ok = dut.pexpect_proc.match.group(1) == b"1"
    finally:
        cap.stop()

    events = parse_probe_events(serial_output)
    assert events, "SHT30 probe emitted no structured EVENT records"
    assert any(e.get("type") == "presence" and e.get("ack") for e in events)
    assert any(e.get("type") == "reset_status" for e in events)
    assert sum(e.get("type") == "measurement" for e in events) == 6
    assert ok, f"SHT30 probe reported failure; events={events!r}"

    assert cap.path.exists() and cap.path.stat().st_size > 0
    decoded = cap.decode()
    observation = observation_candidate(
        target="sht30",
        probe="sht30__characterize",
        scenario="sht30/p0",
        events=events,
        capture=cap.path,
        decoded=decoded,
    )
    print(f"staged observation candidate: {observation}")
