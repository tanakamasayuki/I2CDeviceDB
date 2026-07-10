#!/usr/bin/env python3
"""Promote reviewed staging observation candidates into durable evidence.

The collector deliberately writes provisional JSON into ``collection/_staging``.
This tool gives a reviewed candidate a content-addressed capture name, copies the
raw/decoded pair, and writes a compact YAML observation that refers to them.
It never promotes scan captures.
"""

from __future__ import annotations

import argparse
import filecmp
import json
import shutil
import sys
from pathlib import Path

import yaml

import decode

REPO_ROOT = Path(__file__).resolve().parent.parent


def speed_key(bus_speed_hz: int) -> str:
    if bus_speed_hz % 1000 == 0:
        return f"{bus_speed_hz // 1000}k"
    return f"{bus_speed_hz}hz"


def artifact_path(candidate_path: Path, artifact: str) -> Path:
    raw_path = Path(artifact)
    resolved = (REPO_ROOT / raw_path).resolve()
    if REPO_ROOT not in resolved.parents:
        raise ValueError(f"artifact path escapes repository: {artifact}")
    if not resolved.is_file():
        raise ValueError(f"artifact does not exist: {artifact}")
    return resolved


def load_candidate(path: Path) -> tuple[dict, Path, Path]:
    candidate = json.loads(path.read_text(encoding="utf-8"))
    if candidate.get("schema") != "i2cdevicedb/observation-candidate/v0":
        raise ValueError(f"not an observation candidate v0: {path}")
    if candidate.get("probe") == "scan":
        raise ValueError("scan has no durable bus capture to curate")
    artifacts = candidate.get("artifacts") or {}
    return candidate, artifact_path(path, artifacts["raw"]), artifact_path(
        path, artifacts["decoded"]
    )


def build_curated(candidate: dict, raw: Path, decoded: Path) -> tuple[str, dict]:
    records = [json.loads(line) for line in decoded.read_text(encoding="utf-8").splitlines()]
    if not records:
        raise ValueError(f"decoded capture is empty: {decoded}")
    exact_hash = decode.content_hash(records)
    provenance = candidate.get("provenance") or {}
    speed = speed_key(int(provenance["bus_speed_hz"]))
    condition = candidate.get("condition", "nominal")
    target = candidate["target"]
    probe = candidate["probe"]
    profile_path = REPO_ROOT / "profiles" / f"{target}.yaml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8")) if profile_path.exists() else {}
    semantic_signature = decode.semantic_hash(
        records,
        profile.get("semantic_masks", []),
        profile.get("semantic_normalizations", []),
    )
    capture_key = f"{target}__{probe}__{speed}__{condition}__{exact_hash}"
    scenario_key = str(candidate["scenario"]).replace("/", "-")
    observation_id = f"{scenario_key}-{speed}-{condition}-{exact_hash}"

    observation = {
        "schema_version": 1,
        "id": observation_id,
        "kind": candidate["kind"],
        "target": target,
        "scenario": candidate["scenario"],
        "condition": condition,
        "semantic_signature": semantic_signature,
        "events": candidate.get("events", []),
        "captures": [
            {
                "key": capture_key,
                "exact_hash": exact_hash,
                "semantic_signature": semantic_signature,
                "raw": f"captures/raw/{capture_key}.sr",
                "decoded": f"captures/decoded/{capture_key}.jsonl",
            }
        ],
        "provenance": provenance,
    }
    if candidate.get("timing_features"):
        observation["timing_features"] = candidate["timing_features"]
    return capture_key, observation


def copy_artifact(source: Path, destination: Path, write: bool) -> None:
    if destination.exists():
        if not filecmp.cmp(source, destination, shallow=False):
            raise ValueError(f"existing durable artifact differs: {destination}")
        return
    if write:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def curate(path: Path, write: bool) -> tuple[Path, Path, Path]:
    candidate, raw, decoded = load_candidate(path)
    capture_key, observation = build_curated(candidate, raw, decoded)
    raw_out = REPO_ROOT / "captures" / "raw" / f"{capture_key}.sr"
    decoded_out = REPO_ROOT / "captures" / "decoded" / f"{capture_key}.jsonl"
    observation_out = REPO_ROOT / "observations" / candidate["target"] / f"{observation['id']}.yaml"
    copy_artifact(raw, raw_out, write)
    copy_artifact(decoded, decoded_out, write)
    rendered = yaml.safe_dump(observation, allow_unicode=True, sort_keys=False)
    if observation_out.exists() and observation_out.read_text(encoding="utf-8") != rendered:
        raise ValueError(f"existing observation differs: {observation_out}")
    if write:
        observation_out.parent.mkdir(parents=True, exist_ok=True)
        observation_out.write_text(rendered, encoding="utf-8")
    return raw_out, decoded_out, observation_out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path, nargs="+", help="staging observation JSON")
    parser.add_argument("--write", action="store_true", help="write durable captures/observations")
    args = parser.parse_args(argv)
    for path in args.candidate:
        raw, decoded, observation = curate(path, args.write)
        action = "curated" if args.write else "would curate"
        print(f"{action}: {raw.relative_to(REPO_ROOT)}")
        print(f"{action}: {decoded.relative_to(REPO_ROOT)}")
        print(f"{action}: {observation.relative_to(REPO_ROOT)}")
    if not args.write:
        print("dry run only; pass --write after review")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
