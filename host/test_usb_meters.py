#!/usr/bin/env python3
"""Probe USB-connected DL/T 645 meters and run read-only smoke tests.

Examples:
    python3 host/test_usb_meters.py
    python3 host/test_usb_meters.py --ports /dev/cu.usbserial-1120 /dev/cu.usbserial-1130
    python3 host/test_usb_meters.py --addr 557499000093 --baud 2400 --parity even

The script never sends DL/T 645 write commands.  Address discovery uses the
standard universal address request, followed by reads of phase-A voltage and
combined active energy.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass


HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "dlt645_usb.py")
DEFAULT_CODES = ("0x02010100", "0x00000000")
DEFAULT_MATRIX = ((2400, "even"), (1200, "even"), (2400, "none"), (1200, "none"))


@dataclass(frozen=True)
class Probe:
    port: str
    baud: int
    parity: str
    address: str | None
    discovery: str


def serial_ports() -> list[str]:
    """Return likely USB serial callout devices on macOS/Linux."""
    candidates = []
    for pattern in ("/dev/cu.usbserial-*", "/dev/ttyUSB*", "/dev/ttyACM*"):
        # glob is deliberately local so the script has no third-party deps.
        import glob

        candidates.extend(glob.glob(pattern))
    return sorted(set(candidates))


def run_cli(args: list[str]) -> tuple[list[dict], str]:
    completed = subprocess.run(
        [sys.executable, CLI, *args],
        text=True,
        capture_output=True,
        check=False,
    )
    rows: list[dict] = []
    for line in completed.stdout.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    diagnostics = completed.stderr.strip()
    if completed.returncode and not diagnostics:
        diagnostics = f"dlt645_usb exited with status {completed.returncode}"
    return rows, diagnostics


def discover(port: str, baud: int, parity: str, timeout: float) -> tuple[str | None, str]:
    rows, diagnostics = run_cli([
        "--port", port,
        "--baud", str(baud),
        "--parity", parity,
        "--version", "2007",
        "--discover-address",
        "--timeout", str(timeout),
    ])
    if rows and rows[-1].get("ok") and rows[-1].get("address"):
        return str(rows[-1]["address"]), "address response received"
    if rows:
        return None, str(rows[-1].get("error", "no valid address response"))
    return None, diagnostics or "no response"


def read_values(
    port: str,
    baud: int,
    parity: str,
    address: str,
    codes: tuple[str, ...],
    timeout: float,
) -> list[dict]:
    args = [
        "--port", port,
        "--baud", str(baud),
        "--parity", parity,
        "--version", "2007",
        "--addr", address,
        "--timeout", str(timeout),
    ]
    for code in codes:
        args.extend(("--code", code))
    rows, diagnostics = run_cli(args)
    if diagnostics:
        print(f"    diagnostic: {diagnostics}")
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ports", nargs="+", help="serial ports (default: auto-detect USB ports)")
    parser.add_argument("--addr", help="known meter address; skip address discovery")
    parser.add_argument("--baud", type=int, help="test only this baud rate")
    parser.add_argument("--parity", choices=("none", "even", "odd"), help="test only this parity")
    parser.add_argument("--timeout", type=float, default=1.5, help="per-request timeout in seconds")
    parser.add_argument("--codes", nargs="+", default=list(DEFAULT_CODES), help="data identifiers to read")
    parser.add_argument("--no-matrix", action="store_true", help="use only 2400/even")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ports = args.ports or serial_ports()
    if not ports:
        print("没有发现 USB 串口。请用 --ports /dev/cu.usbserial-XXXX 指定。")
        return 2

    matrix = [(args.baud, args.parity)] if args.baud and args.parity else list(DEFAULT_MATRIX)
    if args.baud and not args.parity or args.parity and not args.baud:
        print("--baud 和 --parity 必须同时指定。")
        return 2
    if args.no_matrix:
        matrix = [(2400, "even")]

    print("DL/T 645 USB 只读测试")
    print(f"端口: {', '.join(ports)}")
    print(f"探测参数: {', '.join(f'{b}/{p}' for b, p in matrix)}")

    probes: list[Probe] = []
    for port in ports:
        print(f"\n[{port}]")
        address = args.addr
        selected: tuple[int, str] | None = None
        if address:
            selected = (matrix[0][0], matrix[0][1])
            discovery = "address supplied by --addr"
        else:
            discovery = "no valid response"
            for baud, parity in matrix:
                print(f"  探测 {baud}/{parity} ... ", end="", flush=True)
                address, discovery = discover(port, baud, parity, args.timeout)
                if address:
                    selected = (baud, parity)
                    print(f"成功，地址 {address}")
                    break
                print(f"失败（{discovery}）")
        if not address or selected is None:
            probes.append(Probe(port, 0, "", None, discovery))
            print("  结论: 未收到有效 DL/T 645 电表响应")
            continue

        baud, parity = selected
        print(f"  读取 {baud}/{parity}, 地址 {address}")
        rows = read_values(port, baud, parity, address, tuple(args.codes), args.timeout)
        successes = 0
        for row in rows:
            name = row.get("data_name", row.get("data_identifier", "unknown"))
            if row.get("ok"):
                successes += 1
                print(f"    OK   {name}: {row.get('value')} {row.get('unit', '')}".rstrip())
            else:
                print(f"    FAIL {name}: {row.get('error', 'unknown error')}")
        print(f"  结论: {successes}/{len(args.codes)} 个读请求成功")
        probes.append(Probe(port, baud, parity, address, "read test complete"))

    print("\n汇总:")
    for probe in probes:
        status = "PASS" if probe.address else "FAIL"
        settings = f"{probe.baud}/{probe.parity}" if probe.baud else "-"
        print(f"  {status} {probe.port} ({settings}) {probe.address or probe.discovery}")
    return 0 if all(probe.address for probe in probes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
