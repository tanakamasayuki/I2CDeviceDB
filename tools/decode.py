#!/usr/bin/env python3
"""Compact I2C decoder: sigrok jsontrace -> decoded transactions (Level2 + Level4).

Input is either a sigrok ``.sr`` capture (this runs sigrok-cli to produce the
jsontrace intermediate) or an already-decoded ``*.jsontrace.json``. The jsontrace
is a transient intermediate — verbose, bit-level, and regenerable from the .sr —
so it is never persisted; this tool collapses it to a compact transaction list.

The i2c and uart protocol decoders share one timebase in the jsontrace, which is
what lets us map UART markers (CASE_BEGIN/PHASE/CASE_END on the LA-observed line)
onto the I2C transactions by time (Level4). See docs/DATA_MODEL.ja.md.

Output: JSONL, one transaction per line. Absolute timestamps are intentionally
dropped (they vary every run and must not affect the content hash / identity);
timing-focused conditions would add timing features here later.

Usage:
    python tools/decode.py capture.sr            # runs sigrok, prints JSONL
    python tools/decode.py capture.jsontrace.json -o decoded.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# sigrok decoder invocation (same as the collection harness).
DECODERS = [
    "-P", "uart:rx=UART_TX:baudrate=115200:format=ascii",
    "-P", "i2c:scl=SCL:sda=SDA",
]

ADDR_RE = re.compile(r"^Address (write|read): ([0-9A-Fa-f]+)$")
DATA_RE = re.compile(r"^Data (write|read): ([0-9A-Fa-f]+)$")
MARKER_RE = re.compile(
    r"(CASE_BEGIN|CASE_END|PHASE|INPUT|RESULT)\s*"
    r"(.*?)(?=CASE_BEGIN|CASE_END|PHASE|INPUT|RESULT|$)"
)


# --------------------------------------------------------------------------- #
# input
# --------------------------------------------------------------------------- #
def sigrok_cli() -> str:
    return os.getenv("SIGROK_CLI", "sigrok-cli")


def load_events(input_path: Path) -> list[dict]:
    """Return the jsontrace traceEvents, decoding a .sr on the fly if needed."""
    if input_path.suffix == ".sr":
        cmd = [sigrok_cli(), "-i", str(input_path), *DECODERS,
               "--protocol-decoder-jsontrace"]
        with tempfile.NamedTemporaryFile("w+b", suffix=".json") as tmp:
            subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=tmp,
                           stderr=subprocess.PIPE, check=True)
            tmp.seek(0)
            return json.load(tmp)["traceEvents"]
    with input_path.open(encoding="utf-8") as fh:
        return json.load(fh)["traceEvents"]


# --------------------------------------------------------------------------- #
# I2C transactions (Level2)
# --------------------------------------------------------------------------- #
def parse_transactions(events: list[dict]) -> list[dict]:
    evs = sorted(
        (e for e in events
         if e.get("pid") == "i2c-1" and e.get("tid") == "Address/Data"
         and e.get("ph") == "B"),
        key=lambda e: e["ts"],
    )
    txns: list[dict] = []
    cur: dict | None = None
    pending = None  # "addr" or int index into bytes, awaiting its ACK/NACK

    def close(stop: bool):
        nonlocal cur, pending
        if cur is not None:
            cur["stop"] = stop
            txns.append(cur)
        cur = None
        pending = None

    for e in evs:
        name = str(e["name"])
        if name.startswith("Start"):
            close(stop=False)  # a Start before Stop is a repeated start
            cur = {"start_ts": e["ts"], "addr": None, "rw": None,
                   "addr_ack": None, "bytes": []}
            pending = None
            continue
        if cur is None:
            continue
        m = ADDR_RE.match(name)
        if m:
            cur["rw"] = m.group(1)
            cur["addr"] = "0x%02X" % int(m.group(2), 16)
            pending = "addr"
            continue
        m = DATA_RE.match(name)
        if m:
            cur["bytes"].append({"value": "0x%02X" % int(m.group(2), 16), "ack": None})
            pending = len(cur["bytes"]) - 1
            continue
        if name in ("ACK", "NACK"):
            ack = name == "ACK"
            if pending == "addr":
                cur["addr_ack"] = ack
            elif isinstance(pending, int):
                cur["bytes"][pending]["ack"] = ack
            pending = None
            continue
        if name == "Stop":
            close(stop=True)
    close(stop=False)
    return txns


# --------------------------------------------------------------------------- #
# UART markers (Level4)
# --------------------------------------------------------------------------- #
def parse_markers(events: list[dict]) -> list[dict]:
    """Reconstruct the marker stream and locate CASE_BEGIN/CASE_END/PHASE.

    The ascii UART decoder drops control chars (no newline events), so lines run
    together (``...SweepCASE_END...``). We rebuild the printable char stream with
    per-char timestamps and split on the controlled marker keywords, not newlines.
    """
    chars = sorted(
        (e for e in events
         if e.get("pid") == "uart-1" and e.get("tid") == "RX" and e.get("ph") == "B"
         and isinstance(e.get("name"), str) and len(e["name"]) == 1),
        key=lambda e: e["ts"],
    )
    text = "".join(e["name"] for e in chars)
    ts_at = [e["ts"] for e in chars]

    markers: list[dict] = []
    for m in MARKER_RE.finditer(text):
        arg = m.group(2).strip()
        markers.append({"ts": ts_at[m.start()], "kind": m.group(1), "arg": arg})
    return markers


def annotate(txns: list[dict], markers: list[dict]) -> None:
    """Assign operation/phase to each transaction by timestamp (in place)."""
    for t in txns:
        ts = t["start_ts"]
        op = phase = None
        for mk in markers:
            if mk["ts"] > ts:
                break
            if mk["kind"] == "CASE_BEGIN":
                op, phase = mk["arg"], None
            elif mk["kind"] == "CASE_END":
                if mk["arg"] == op:
                    op = phase = None
            elif mk["kind"] == "PHASE":
                phase = mk["arg"]
        t["operation"] = op
        t["phase"] = phase


# --------------------------------------------------------------------------- #
# output
# --------------------------------------------------------------------------- #
def to_records(txns: list[dict]) -> list[dict]:
    """Content records: no absolute timestamps (not part of identity)."""
    return [
        {
            "i": i,
            "addr": t["addr"],
            "rw": t["rw"],
            "addr_ack": t["addr_ack"],
            "bytes": t["bytes"],
            "stop": t["stop"],
            "operation": t.get("operation"),
            "phase": t.get("phase"),
        }
        for i, t in enumerate(txns)
    ]


def content_hash(records: list[dict]) -> str:
    blob = json.dumps([{k: v for k, v in r.items() if k != "i"} for r in records],
                      sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def summarize(records: list[dict]) -> dict:
    acked = [r["addr"] for r in records if r["addr_ack"]]
    ops = sorted({r["operation"] for r in records if r["operation"]})
    return {
        "transactions": len(records),
        "ack_addresses": acked,
        "operations": ops,
        "content_hash": content_hash(records),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="sigrok jsontrace/.sr -> decoded I2C JSONL")
    ap.add_argument("input", type=Path, help="capture .sr or *.jsontrace.json")
    ap.add_argument("-o", "--output", type=Path, help="write JSONL here (default: stdout)")
    args = ap.parse_args(argv)

    events = load_events(args.input)
    txns = parse_transactions(events)
    annotate(txns, parse_markers(events))
    records = to_records(txns)

    lines = "\n".join(json.dumps(r, separators=(",", ":")) for r in records)
    if args.output:
        args.output.write_text(lines + "\n", encoding="utf-8")
    else:
        print(lines)

    summary = summarize(records)
    print(json.dumps(summary, indent=2), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
