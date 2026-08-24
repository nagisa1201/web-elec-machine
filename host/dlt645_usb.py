#!/usr/bin/env python3
"""Read and decode DL/T 645 data through a USB serial adapter."""

from __future__ import annotations

import argparse
import json
import os
import select
import socket
import sys
import termios
import time
from typing import Callable, Optional

from dlt645_converter import (
    FrameDecoder,
    ProtocolError,
    build_read_address_request,
    build_read_request,
    decode_frame,
    data_point,
    parse_address,
    parse_code,
    read_codes,
)
from dlt645_database import SQLiteStore


_BAUD = {
    1200: termios.B1200,
    2400: termios.B2400,
    4800: termios.B4800,
    9600: termios.B9600,
    19200: termios.B19200,
    38400: termios.B38400,
    57600: termios.B57600,
    115200: termios.B115200,
}


class SerialPort:
    def __init__(self, path: str, baud: int, parity: str) -> None:
        if baud not in _BAUD:
            raise ValueError(f"unsupported baud rate {baud}; choose from {sorted(_BAUD)}")
        if parity not in ("none", "even", "odd"):
            raise ValueError("parity must be none, even, or odd")
        self.path = path
        self.fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        attrs = termios.tcgetattr(self.fd)
        attrs[0] = 0
        attrs[1] = 0
        attrs[2] = termios.CLOCAL | termios.CREAD | termios.CS8
        if parity == "even":
            attrs[2] |= termios.PARENB
        elif parity == "odd":
            attrs[2] |= termios.PARENB | termios.PARODD
        attrs[3] = 0
        attrs[4] = _BAUD[baud]
        attrs[5] = _BAUD[baud]
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 1
        termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
        termios.tcflush(self.fd, termios.TCIOFLUSH)

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self) -> "SerialPort":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def write(self, payload: bytes) -> None:
        view = memoryview(payload)
        while view:
            _, writable, _ = select.select([], [self.fd], [], 1.0)
            if not writable:
                raise TimeoutError("USB serial write timed out")
            written = os.write(self.fd, view)
            view = view[written:]

    def read(self, timeout: float) -> bytes:
        readable, _, _ = select.select([self.fd], [], [], max(0.0, timeout))
        if not readable:
            return b""
        try:
            return os.read(self.fd, 4096)
        except BlockingIOError:
            return b""


class TcpPort:
    """TCP transport for desktop or remote DL/T 645 simulators."""

    def __init__(self, host: str, port: int) -> None:
        self.sock = socket.create_connection((host, port), timeout=5.0)
        self.sock.setblocking(False)

    def close(self) -> None:
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def __enter__(self) -> "TcpPort":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def write(self, payload: bytes) -> None:
        view = memoryview(payload)
        while view:
            _, writable, _ = select.select([], [self.sock], [], 1.0)
            if not writable:
                raise TimeoutError("TCP write timed out")
            written = self.sock.send(view)
            view = view[written:]

    def read(self, timeout: float) -> bytes:
        readable, _, _ = select.select([self.sock], [], [], max(0.0, timeout))
        if not readable:
            return b""
        try:
            return self.sock.recv(4096)
        except (BlockingIOError, ConnectionResetError):
            return b""


def _print(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=True, separators=(",", ":")), flush=True)


def _debug(enabled: bool, direction: str, payload: bytes) -> None:
    if enabled:
        print(f"{direction} {payload.hex(' ').upper()}", file=sys.stderr, flush=True)


def _emit(result: dict, on_result: Optional[Callable[[dict], None]]) -> None:
    _print(result)
    if on_result is not None:
        on_result(result)


def _requested_metadata(result: dict, code: int, version: str) -> dict:
    """Attach the requested identifier metadata to errors and timeouts."""
    point = data_point(code, version)
    result.setdefault("requested_data_identifier", f"0x{code:08X}" if version == "2007" else f"0x{code:04X}")
    if point is not None:
        result.setdefault("data_name", point.name)
        result.setdefault("unit", point.unit)
    result.setdefault("protocol", f"DLT645-{version}")
    return result


def listen(port: SerialPort, version: str, debug: bool) -> None:
    decoder = FrameDecoder()
    while True:
        chunk = port.read(1.0)
        if not chunk:
            continue
        _debug(debug, "RX", chunk)
        for frame in decoder.feed(chunk):
            try:
                _print(decode_frame(frame, version))
            except ProtocolError as exc:
                _print({"ok": False, "error": str(exc), "raw": frame.raw.hex().upper()})


def request(
    port: SerialPort,
    address: bytes,
    codes: list[int],
    version: str,
    preamble: int,
    timeout: float,
    debug: bool,
    on_result: Optional[Callable[[dict], None]] = None,
) -> list[dict]:
    decoder = FrameDecoder()
    results: list[dict] = []
    for code in codes:
        frame = build_read_request(address, code, version, preamble)
        _debug(debug, "TX", frame)
        port.write(frame)
        deadline = time.monotonic() + timeout
        found = False
        while time.monotonic() < deadline:
            chunk = port.read(min(0.2, deadline - time.monotonic()))
            if not chunk:
                continue
            _debug(debug, "RX", chunk)
            for response in decoder.feed(chunk):
                if response.address_wire != address:
                    if debug:
                        print(
                            f"IGNORED response address {response.address}; expected {address[::-1].hex().upper()}",
                            file=sys.stderr,
                            flush=True,
                        )
                    continue
                width = 2 if version == "1997" else 4
                if not (response.control & 0x40) and len(response.data) >= width:
                    response_code = int.from_bytes(
                        bytes((byte - 0x33) & 0xFF for byte in response.data[:width]),
                        "little",
                    )
                    if response_code != code:
                        if debug:
                            print(
                                f"IGNORED response identifier 0x{response_code:X}; expected 0x{code:X}",
                                file=sys.stderr,
                                flush=True,
                            )
                        continue
                try:
                    decoded = decode_frame(response, version, code)
                except ProtocolError as exc:
                    decoded = _requested_metadata({"ok": False, "error": str(exc), "raw": response.raw.hex().upper()}, code, version)
                else:
                    decoded = _requested_metadata(decoded, code, version)
                _emit(decoded, on_result)
                results.append(decoded)
                found = True
                break
            if found:
                break
        if not found:
            timeout_result = _requested_metadata(
                {
                    "ok": False,
                    "error": "response timeout",
                    "data_identifier": f"0x{code:08X}" if version == "2007" else f"0x{code:04X}",
                },
                code,
                version,
            )
            _emit(timeout_result, on_result)
            results.append(timeout_result)
    return results


def discover_address(port: SerialPort, preamble: int, timeout: float, debug: bool) -> None:
    """Ask a single DL/T 645-2007 meter to report its communication address."""
    decoder = FrameDecoder()
    payload = build_read_address_request(preamble)
    _debug(debug, "TX", payload)
    port.write(payload)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        chunk = port.read(min(0.2, deadline - time.monotonic()))
        if not chunk:
            continue
        _debug(debug, "RX", chunk)
        for response in decoder.feed(chunk):
            if (response.control & 0x1F) != 0x13 or not (response.control & 0x80):
                if debug:
                    print(f"IGNORED non-address response {response.raw.hex(' ').upper()}", file=sys.stderr, flush=True)
                continue
            result = {
                "ok": not bool(response.control & 0x40),
                "protocol": "DLT645-2007",
                "address": response.address,
                "address_wire": response.address_wire.hex().upper(),
                "control": f"0x{response.control:02X}",
                "raw": response.raw.hex().upper(),
            }
            if response.control & 0x40:
                result["error"] = "meter rejected read-address request"
            _print(result)
            return
    _print({"ok": False, "error": "address discovery timeout"})


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    transport = parser.add_mutually_exclusive_group()
    transport.add_argument("--port", help="USB serial device, e.g. /dev/ttyUSB0 or /dev/cu.usbserial-XXXX")
    transport.add_argument("--tcp", metavar="HOST:PORT", help="TCP endpoint for a software meter simulator")
    parser.add_argument("--baud", type=int, default=2400, help="baud rate (default: 2400)")
    parser.add_argument("--parity", choices=("none", "even", "odd"), default="none", help="serial parity (default: none)")
    parser.add_argument("--version", choices=("1997", "2007"), default="2007")
    parser.add_argument("--addr", help="meter address in human order, e.g. 123456789012")
    parser.add_argument("--code", action="append", help="read data identifier; repeat for multiple codes")
    parser.add_argument("--all", action="store_true", help="read every enabled identifier in the built-in catalog")
    parser.add_argument("--poll", action="store_true", help="repeat active reads until Ctrl-C")
    parser.add_argument("--interval", type=float, default=5.0, help="seconds between polling cycles (default: 5)")
    parser.add_argument("--db", help="SQLite database path for active read results")
    parser.add_argument("--list-codes", action="store_true", help="list built-in identifiers and exit")
    parser.add_argument("--discover-address", action="store_true", help="query one DL/T 645-2007 meter for its communication address")
    parser.add_argument("--preamble", type=int, default=4, help="number of FE bytes before requests (default: 4)")
    parser.add_argument("--timeout", type=float, default=1.5, help="response timeout in seconds")
    parser.add_argument("--hex", dest="hex_frame", help="decode a hexadecimal frame without opening a serial port")
    parser.add_argument("--debug", action="store_true", help="print raw sent and received bytes to standard error")
    args = parser.parse_args(argv)

    if args.list_codes:
        for point_code in read_codes(args.version, include_all=True):
            point = data_point(point_code, args.version)
            _print({
                "protocol": f"DLT645-{args.version}",
                "data_identifier": f"0x{point_code:08X}" if args.version == "2007" else f"0x{point_code:04X}",
                "data_name": point.name if point else None,
                "unit": point.unit if point else "",
                "scale": point.scale if point else None,
            })
        return 0

    if args.hex_frame:
        decoder = FrameDecoder()
        try:
            frames = decoder.feed(bytes.fromhex(args.hex_frame))
            for frame in frames:
                _print(decode_frame(frame, args.version))
        except (ValueError, ProtocolError) as exc:
            parser.error(str(exc))
        return 0

    if not args.port and not args.tcp:
        parser.error("--port or --tcp is required unless --hex is used")
    if args.discover_address and args.code:
        parser.error("--discover-address cannot be used with --code")
    if args.discover_address and (args.all or args.poll or args.db):
        parser.error("--discover-address cannot be combined with --all, --poll, or --db")
    if args.all and args.code:
        parser.error("--all cannot be combined with --code; use --code to select identifiers")
    if args.poll and args.discover_address:
        parser.error("--poll cannot be combined with --discover-address")
    if args.interval <= 0:
        parser.error("--interval must be greater than zero")
    if args.discover_address and args.version != "2007":
        parser.error("--discover-address is available only for DL/T 645-2007")
    if (args.code or args.all or args.poll) and not args.addr:
        parser.error("--addr is required for active reads")
    try:
        address = parse_address(args.addr) if args.addr else None
        codes = [parse_code(value, args.version) for value in args.code or []]
        if args.all:
            codes = list(read_codes(args.version, include_all=True))
        elif args.poll and not codes:
            codes = list(read_codes(args.version, include_all=False))
        if args.tcp:
            host, separator, port_text = args.tcp.rpartition(":")
            if not separator or not host or not port_text.isdigit():
                parser.error("--tcp must be formatted as HOST:PORT")
            connection = TcpPort(host, int(port_text))
        else:
            connection = SerialPort(args.port, args.baud, args.parity)
        with connection as port:
            if args.discover_address:
                discover_address(port, args.preamble, args.timeout, args.debug)
            elif codes:
                store = SQLiteStore(args.db) if args.db else None
                try:
                    if args.poll:
                        while True:
                            cycle_started = time.monotonic()
                            request(
                                port,
                                address,
                                codes,
                                args.version,
                                args.preamble,
                                args.timeout,
                                args.debug,
                                store.save if store else None,
                            )
                            elapsed = time.monotonic() - cycle_started
                            delay = args.interval - elapsed
                            if delay > 0:
                                time.sleep(delay)
                            elif args.debug:
                                print(
                                    f"poll cycle took {elapsed:.3f}s, longer than interval {args.interval:.3f}s",
                                    file=sys.stderr,
                                    flush=True,
                                )
                    else:
                        request(
                            port,
                            address,
                            codes,
                            args.version,
                            args.preamble,
                            args.timeout,
                            args.debug,
                            store.save if store else None,
                        )
                finally:
                    if store:
                        store.close()
            else:
                listen(port, args.version, args.debug)
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, TimeoutError) as exc:
        print(f"dlt645_usb: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
