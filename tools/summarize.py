#!/usr/bin/env python3
"""Derive timing distributions from curated observations.

Exact captures remain separate evidence. This tool groups observations by their
semantic signature and controlled condition, then reports a distribution rather
than turning a single timing sample into a profile constant.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import median

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_observations(root: Path, target: str | None = None) -> list[dict]:
    observations = []
    for path in sorted(root.glob("observations/**/*.yaml")):
        observation = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if target is None or observation.get("target") == target:
            observations.append(observation)
    return observations


def timing_distributions(observations: list[dict]) -> list[dict]:
    groups: dict[tuple, list[float]] = defaultdict(list)
    for observation in observations:
        base = (
            observation.get("target"),
            observation.get("scenario"),
            observation.get("condition"),
            observation.get("semantic_signature"),
            (observation.get("provenance") or {}).get("bus_speed_hz"),
        )
        for feature in observation.get("timing_features", []):
            if feature.get("type") != "clock_stretch" or "scl_low_us" not in feature:
                continue
            request = feature.get("request") or {}
            key = base + (
                feature.get("operation"),
                feature.get("phase"),
                request.get("command"),
            )
            groups[key].append(float(feature["scl_low_us"]))

    result = []
    for key, samples in sorted(groups.items()):
        target, scenario, condition, signature, speed, operation, phase, command = key
        result.append(
            {
                "target": target,
                "scenario": scenario,
                "condition": condition,
                "semantic_signature": signature,
                "bus_speed_hz": speed,
                "type": "clock_stretch",
                "operation": operation,
                "phase": phase,
                "request": {"command": command},
                "samples": len(samples),
                "min_us": min(samples),
                "median_us": median(samples),
                "max_us": max(samples),
            }
        )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", help="optional chip key")
    args = parser.parse_args(argv)
    result = {
        "schema": "i2cdevicedb/timing-summary/v0",
        "groups": timing_distributions(load_observations(REPO_ROOT, args.target)),
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
