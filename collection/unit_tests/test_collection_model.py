"""Hardware-free tests for product selection and structured probe output."""

import json
from pathlib import Path

import pytest
import yaml

from conftest import decoded_artifact_path, derive_probe_keys, parse_probe_events

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


def test_decoded_artifact_name_describes_its_role():
    assert decoded_artifact_path(Path("_staging/sht30__characterize.sr")) == Path(
        "_staging/sht30__characterize.decoded.jsonl"
    )


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


def test_marker_parser_reconstructs_hex_uart_bytes():
    from conftest import _load_decoder

    decoder = _load_decoder()
    text = "CASE_BEGIN Device Detection\nCASE_END Device Detection\n"
    events = [
        {
            "pid": "uart-1",
            "tid": "RX",
            "ph": "B",
            "name": f"{byte:02X}",
            "ts": i,
        }
        for i, byte in enumerate(text.encode("ascii"))
    ]
    assert [(m["kind"], m["arg"]) for m in decoder.parse_markers(events)] == [
        ("CASE_BEGIN", "Device Detection"),
        ("CASE_END", "Device Detection"),
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


def test_clock_stretch_features_come_from_raw_scl_low_intervals():
    from conftest import _load_timing

    vcd = """$timescale 1 ns $end
$scope module libsigrok $end
$var wire 1 ! SCL $end
$upscope $end
$enddefinitions $end
#0 1!
#100000 0!
#3100000 1!
"""
    timing = _load_timing()
    assert timing.scl_low_intervals(vcd) == [
        {"start_us": 100.0, "end_us": 3100.0, "duration_us": 3000.0}
    ]


def test_clock_stretch_feature_keeps_its_operation_and_request(monkeypatch):
    from conftest import _load_timing

    timing = _load_timing()
    monkeypatch.setattr(
        timing,
        "export_vcd",
        lambda _capture: """$var wire 1 ! SCL $end
#0 1!
#100000 0!
#3100000 1!
""",
    )
    markers = [
        {"ts": 0.0, "kind": "CASE_BEGIN", "arg": "Single Measurement"},
        {"ts": 50.0, "kind": "PHASE", "arg": "stretching-high"},
        {
            "ts": 60.0,
            "kind": "INPUT",
            "arg": '{"command":"0x2C06","clock_stretch":true}',
        },
        {"ts": 4000.0, "kind": "RESULT", "arg": "{}"},
    ]
    assert timing.clock_stretch_features(Path("unused.sr"), markers) == [
        {
            "type": "clock_stretch",
            "source": "raw_scl_low",
            "scl_low_us": 3000.0,
            "request": {"command": "0x2C06", "clock_stretch": True},
            "operation": "Single Measurement",
            "phase": "stretching-high",
            "repeatability": "high",
        }
    ]


def test_decoded_content_hash_excludes_measured_timing():
    from conftest import _load_decoder

    decoder = _load_decoder()
    base = {
        "i": 0,
        "addr": "0x44",
        "rw": "read",
        "addr_ack": True,
        "bytes": [],
        "stop": True,
        "operation": "Single Measurement",
        "phase": "stretching-high",
    }
    timed = base | {
        "timing": {"clock_stretch": {"source": "raw_scl_low", "scl_low_us": 1.0}}
    }
    assert decoder.content_hash([base]) == decoder.content_hash([timed])


def test_decoded_records_keep_relative_transaction_cadence():
    from conftest import _load_decoder

    decoder = _load_decoder()
    records = decoder.to_records(
        [
            {
                "start_ts": 100.0,
                "end_ts": 140.0,
                "addr": "0x44",
                "rw": "write",
                "addr_ack": True,
                "bytes": [],
                "stop": True,
            },
            {
                "start_ts": 200.0,
                "end_ts": 260.0,
                "addr": "0x44",
                "rw": "read",
                "addr_ack": True,
                "bytes": [],
                "stop": True,
            },
        ]
    )
    assert records[0]["timing"] == {"start_offset_us": 0.0, "duration_us": 40.0}
    assert records[1]["timing"] == {
        "start_offset_us": 100.0,
        "duration_us": 60.0,
        "gap_since_previous_us": 60.0,
    }


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
