"""Profile -> generated SHT30 P0 access API and emulator proof."""

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]


def _load_generator():
    tools_dir = str(REPO_ROOT / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    import generate

    return generate


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location("generated_sht30", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _captured_polling_medium_frame() -> bytes:
    capture = next((REPO_ROOT / "captures" / "decoded").glob("sht30*.jsonl"))
    for line in capture.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("phase") == "polling-medium" and record.get("rw") == "read":
            values = record["bytes"]
            if len(values) == 6:
                return bytes(int(value["value"], 16) for value in values)
    raise AssertionError("captured polling-medium frame not found")


def test_profile_generates_access_api_and_clock_stretch_emulator(tmp_path):
    generator = _load_generator()
    profile = generator.yaml.safe_load(
        (REPO_ROOT / "profiles" / "sht30.yaml").read_text(encoding="utf-8")
    )
    output = tmp_path / "sht30_p0.py"
    output.write_text(generator.generate_sht30(profile), encoding="utf-8")
    generated = _load_module(output)
    frame = _captured_polling_medium_frame()

    class Transport:
        def __init__(self):
            self.writes = []

        def write(self, data):
            self.writes.append(data)

        def read(self, length):
            assert length == 6
            return frame

    transport = Transport()
    value = generated.SHT30Access(transport).single_shot("medium")
    assert transport.writes == [bytes.fromhex("240B")]
    assert value.temperature_raw == int.from_bytes(frame[:2], "big")
    assert value.humidity_raw == int.from_bytes(frame[3:5], "big")

    emulator = generated.SHT30Emulator(
        temperature_raw=value.temperature_raw,
        humidity_raw=value.humidity_raw,
        conversion_us_by_repeatability={"high": 11007.75, "medium": 3058.75, "low": 1764.125},
    )
    emulator.write(bytes.fromhex("2C06"), now_us=0)
    response = emulator.read(now_us=0)
    assert response.scl_low_us == 11007.75
    assert response.data == frame
