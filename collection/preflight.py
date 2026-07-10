#!/usr/bin/env python3
"""Validate the ENV III collection bench before running hardware pytest."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent

REQUIRED_ENV = (
    "TEST_SERIAL_PORT_ESP32S3",
    "TEST_I2C_SDA",
    "TEST_I2C_SCL",
    "TEST_UART_TX",
    "TEST_I2C_BUS_HZ",
    "TEST_PRODUCT",
    "TEST_SPECIMEN_ID",
    "SIGROK_DRIVER",
    "SIGROK_CH_UART_TX",
    "SIGROK_CH_SCL",
    "SIGROK_CH_SDA",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--offline",
        action="store_true",
        help="skip serial-port and connected logic-analyzer checks",
    )
    args = parser.parse_args()
    errors: list[str] = []
    warnings: list[str] = []

    missing = [name for name in REQUIRED_ENV if not os.getenv(name, "").strip()]
    if missing:
        errors.append("missing environment variables: " + ", ".join(missing))

    for command in ("arduino-cli", "sigrok-cli"):
        if not shutil.which(command):
            message = f"{command} not found on PATH"
            (warnings if args.offline and command == "sigrok-cli" else errors).append(message)

    product = os.getenv("TEST_PRODUCT", "").strip()
    if product:
        product_path = REPO_ROOT / "products" / f"{product}.yaml"
        if not product_path.exists():
            errors.append(f"product not found: {product_path}")
        else:
            obj = yaml.safe_load(product_path.read_text(encoding="utf-8")) or {}
            chips = [c.get("chip") for c in obj.get("components", []) if c.get("chip")]
            probes = [
                f"{chip}__characterize"
                for chip in chips
                if (ROOT / "sketches" / f"{chip}__characterize").is_dir()
            ]
            print(f"product: {product}; chips={chips}; characterization={probes}")
            if product == "m5stack-u001-c" and set(probes) != {
                "sht30__characterize",
                "qmp6988__characterize",
            }:
                errors.append("ENV III characterization probe set is incomplete")

    bus_hz = os.getenv("TEST_I2C_BUS_HZ", "").strip()
    if bus_hz:
        try:
            parsed_hz = int(bus_hz)
            if parsed_hz not in (100000, 400000):
                warnings.append(
                    f"TEST_I2C_BUS_HZ={parsed_hz}; pilot nominal runs are 100000/400000"
                )
        except ValueError:
            errors.append(f"TEST_I2C_BUS_HZ must be an integer, got {bus_hz!r}")

    if shutil.which("arduino-cli"):
        result = subprocess.run(
            ["arduino-cli", "core", "list"], capture_output=True, text=True, check=False
        )
        if "esp32:esp32" not in result.stdout or "3.3.10" not in result.stdout:
            errors.append("Arduino core esp32:esp32@3.3.10 is not installed")

    if not args.offline:
        serial = Path(os.getenv("TEST_SERIAL_PORT_ESP32S3", ""))
        if str(serial) and not serial.exists():
            errors.append(f"serial port does not exist: {serial}")

        if shutil.which("sigrok-cli"):
            driver = os.getenv("SIGROK_DRIVER", "fx2lafw")
            conn = os.getenv("SIGROK_CONN", "").strip()
            driver_spec = f"{driver}:conn={conn}" if conn else driver
            cmd = ["sigrok-cli", "--scan", "--driver", driver_spec]
            scan = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if scan.returncode != 0 or not scan.stdout.strip():
                detail = (scan.stderr or scan.stdout).strip()
                errors.append(f"logic analyzer not detected with {driver}: {detail}")
            else:
                print(scan.stdout.strip())

    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        print(f"preflight failed: {len(errors)} error(s)")
        return 1
    print("preflight passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
