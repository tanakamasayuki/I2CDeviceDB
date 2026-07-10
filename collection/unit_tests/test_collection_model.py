"""Hardware-free tests for product selection and structured probe output."""

import json
from pathlib import Path

import pytest
import yaml

from conftest import derive_probe_keys, parse_probe_events

REPO_ROOT = Path(__file__).parents[2]


def test_enviii_derives_characterization_probes():
    probes = derive_probe_keys("m5stack-u001-c")
    assert {"scan", "sht30__characterize", "qmp6988__characterize"} <= probes


def test_parse_probe_events():
    first = {"type": "presence", "address": "0x44", "ack": True}
    second = {"type": "measurement", "raw_temperature": 1234}
    output = (
        b"boot noise\r\nEVENT "
        + json.dumps(first).encode()
        + b"\r\nEVENT "
        + json.dumps(second).encode()
        + b"\r\nALL_DONE target=sht30 ok=1\r\n"
    )
    assert parse_probe_events(output) == [first, second]


def test_parse_probe_events_rejects_invalid_json():
    with pytest.raises(ValueError, match="invalid probe EVENT"):
        parse_probe_events(b"EVENT {not-json}\n")


def test_parse_probe_events_requires_type():
    with pytest.raises(ValueError, match="with type"):
        parse_probe_events(b'event ignored\nEVENT {"value":1}\n')


def test_marker_parser_keeps_input_out_of_case_name():
    from conftest import _load_decoder

    decoder = _load_decoder()
    text = (
        "CASE_BEGIN Single Measurement"
        'INPUT {"command":"0x2C06"}'
        "PHASE read"
        'RESULT {"ok":true}'
        "CASE_END Single Measurement"
    )
    events = [
        {"pid": "uart-1", "tid": "RX", "ph": "B", "name": char, "ts": i}
        for i, char in enumerate(text)
    ]
    markers = decoder.parse_markers(events)
    assert [(m["kind"], m["arg"]) for m in markers] == [
        ("CASE_BEGIN", "Single Measurement"),
        ("INPUT", '{"command":"0x2C06"}'),
        ("PHASE", "read"),
        ("RESULT", '{"ok":true}'),
        ("CASE_END", "Single Measurement"),
    ]


def test_jsontrace_parser_repairs_unescaped_uart_quote():
    from conftest import _load_decoder

    decoder = _load_decoder()
    raw = (
        '{"traceEvents":['
        '{"pid":"uart-1","tid":"RX","ph":"B","name":"""}'
        "]}"
    )
    assert decoder.parse_jsontrace(raw)[0]["name"] == '"'


@pytest.mark.parametrize("target", ["sht30", "qmp6988"])
def test_p0_scenario_points_to_available_probe(target):
    path = REPO_ROOT / "scenarios" / target / "p0.yaml"
    scenario = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert scenario["key"] == f"{target}/p0"
    assert scenario["target"] == target
    assert scenario["product"] == "m5stack-u001-c"
    assert scenario["probe"] == f"{target}__characterize"
    assert (
        REPO_ROOT / "collection" / "sketches" / scenario["probe"]
    ).is_dir()
