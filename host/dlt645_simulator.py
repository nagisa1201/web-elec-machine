#!/usr/bin/env python3
"""Small deterministic DL/T 645 TCP meter simulator for local testing."""

from __future__ import annotations

import argparse
import socketserver
import sys
from typing import Optional

from dlt645_converter import Frame, FrameDecoder, parse_address


SIMULATOR_ADDRESS = parse_address("123456789012")


def _encode_bcd(value: int, byte_length: int) -> bytes:
    digits = f"{value:0{byte_length * 2}d}"[-byte_length * 2 :][::-1]
    result = bytearray()
    for index in range(0, len(digits), 2):
        decoded = int(digits[index]) | (int(digits[index + 1]) << 4)
        result.append((decoded + 0x33) & 0xFF)
    return bytes(result)


def _response(frame: Frame, version: str, code: int) -> bytes:
    width = 2 if version == "1997" else 4
    if version == "2007" and code == 0x02010100:
        # A-phase voltage: 230.5 V, encoded with one decimal place.
        payload = _encode_bcd(2305, 2)
    elif version == "1997" and code == 0xB621:
        # A-phase current: 12.34 A, encoded with two decimal places.
        payload = _encode_bcd(1234, 2)
    else:
        payload = _encode_bcd(123456, 3 if version == "2007" else 2)

    body = bytearray([0x68])
    body.extend(frame.address_wire)
    body.extend((0x68, 0x81 if version == "1997" else 0x91, width + len(payload)))
    body.extend(bytes(((code >> (8 * index)) & 0xFF) + 0x33 for index in range(width)))
    body.extend(payload)
    body.extend((sum(body) & 0xFF, 0x16))
    return bytes(body)


def _address_response() -> bytes:
    body = bytearray([0x68])
    body.extend(SIMULATOR_ADDRESS)
    body.extend((0x68, 0x93, 6))
    body.extend((byte + 0x33) & 0xFF for byte in SIMULATOR_ADDRESS)
    body.extend((sum(body) & 0xFF, 0x16))
    return bytes(body)


def _make_handler(version: str):
    class Handler(socketserver.BaseRequestHandler):
        def handle(self) -> None:
            decoder = FrameDecoder()
            while True:
                chunk = self.request.recv(4096)
                if not chunk:
                    return
                for frame in decoder.feed(chunk):
                    width = 2 if version == "1997" else 4
                    if version == "2007" and (frame.control & 0x1F) == 0x13:
                        self.request.sendall(_address_response())
                        continue
                    if frame.control & 0x1F != (0x01 if version == "1997" else 0x11):
                        continue
                    if len(frame.data) < width:
                        continue
                    code = int.from_bytes(bytes((byte - 0x33) & 0xFF for byte in frame.data[:width]), "little")
                    self.request.sendall(_response(frame, version, code))

    return Handler


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8899)
    parser.add_argument("--version", choices=("1997", "2007"), default="2007")
    args = parser.parse_args(argv)
    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True

    try:
        with Server((args.host, args.port), _make_handler(args.version)) as server:
            print(f"DL/T 645-{args.version} simulator listening on {args.host}:{args.port}", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        return 130
    except OSError as exc:
        print(f"dlt645_simulator: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
