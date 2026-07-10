"""Extract timing features from raw sigrok captures.

Protocol-decoder JSON Trace contains semantic I2C events, but not every SCL
level transition. Timing features such as clock stretching therefore derive
from the raw ``.sr`` capture via a transient VCD export. The VCD is never
persisted.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def _sigrok_cli() -> str:
    return os.getenv("SIGROK_CLI", "sigrok-cli")


def export_vcd(capture: Path) -> str:
    """Export a raw sigrok capture to transient VCD text."""
    result = subprocess.run(
        [_sigrok_cli(), "-i", str(capture), "-O", "vcd"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout.decode("utf-8")


def scl_low_intervals(vcd: str, minimum_us: float = 50.0) -> list[dict]:
    """Return SCL LOW spans long enough to be clock-stretch candidates."""
    scl_code: str | None = None
    for line in vcd.splitlines():
        fields = line.split()
        if len(fields) >= 5 and fields[0] == "$var" and fields[-2] == "SCL":
            scl_code = fields[3]
            break
    if scl_code is None:
        raise ValueError("VCD does not contain an SCL signal")

    now_ns = 0
    level: str | None = None
    low_started_ns: int | None = None
    intervals: list[dict] = []
    for line in vcd.splitlines():
        fields = line.split()
        if not fields:
            continue
        if fields[0].startswith("#"):
            now_ns = int(fields[0][1:])
            fields = fields[1:]
        for value in fields:
            if len(value) < 2 or value[1:] != scl_code or value[0] not in "01":
                continue
            next_level = value[0]
            if next_level == "0" and level != "0":
                low_started_ns = now_ns
            elif next_level == "1" and level == "0" and low_started_ns is not None:
                duration_us = (now_ns - low_started_ns) / 1000.0
                if duration_us >= minimum_us:
                    intervals.append(
                        {
                            "start_us": low_started_ns / 1000.0,
                            "end_us": now_ns / 1000.0,
                            "duration_us": duration_us,
                        }
                    )
            level = next_level
    return intervals


def clock_stretch_features(
    capture: Path, markers: list[dict], transactions: list[dict] | None = None
) -> list[dict]:
    """Associate raw SCL LOW spans with marker windows and read transactions.

    When ``transactions`` is supplied, the matching read transaction receives
    the waveform-derived fact in ``timing.clock_stretch``. Absolute timestamps
    remain in memory only and are not emitted in decoded JSONL.
    """
    intervals = scl_low_intervals(export_vcd(capture))
    features: list[dict] = []
    operation: str | None = None
    phase: str | None = None
    for i, marker in enumerate(markers):
        if marker["kind"] == "CASE_BEGIN":
            operation, phase = marker["arg"], None
            continue
        if marker["kind"] == "CASE_END":
            if marker["arg"] == operation:
                operation, phase = None, None
            continue
        if marker["kind"] == "PHASE":
            phase = marker["arg"]
            continue
        if marker["kind"] != "INPUT":
            continue
        try:
            input_value = json.loads(marker["arg"])
        except json.JSONDecodeError:
            continue
        if input_value.get("clock_stretch") is not True:
            continue
        result_ts = next(
            (
                later["ts"]
                for later in markers[i + 1:]
                if later["kind"] in {"RESULT", "CASE_END"}
            ),
            None,
        )
        if result_ts is None:
            continue
        candidates = [
            interval
            for interval in intervals
            if interval["start_us"] >= marker["ts"]
            and interval["end_us"] <= result_ts
        ]
        if not candidates:
            continue
        longest = max(candidates, key=lambda interval: interval["duration_us"])
        feature = {
            "type": "clock_stretch",
            "source": "raw_scl_low",
            "scl_low_us": longest["duration_us"],
            "request": input_value,
        }
        if operation:
            feature["operation"] = operation
        if phase:
            feature["phase"] = phase
            if phase.startswith("stretching-"):
                feature["repeatability"] = phase.removeprefix("stretching-")
        if transactions is not None:
            reads = [
                transaction
                for transaction in transactions
                if transaction.get("rw") == "read"
                and transaction.get("phase") == phase
                and transaction["start_ts"] <= longest["start_us"]
                <= transaction.get("end_ts", float("inf"))
            ]
            if reads:
                reads[0].setdefault("timing", {})["clock_stretch"] = {
                    "source": "raw_scl_low",
                    "scl_low_us": longest["duration_us"],
                }
        features.append(feature)
    return features
