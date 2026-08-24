#!/usr/bin/env python3
"""Optional in-process DL/T 645 acquisition thread.

RS485 serial acquisition belongs to the host CLI (``host/dlt645_usb.py
--poll --db``), which is already Linux-native. This poller covers the other
common case on the board — a meter or simulator reachable over TCP — so a
single ``python -m web`` command can fill the shared SQLite store end to end
without a USB adapter.

It reuses the host frame converter and store rather than re-implementing the
protocol; it only adds the small transport loop the CLI does not expose as a
library.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
from typing import Callable, Iterator, Optional

# Make the sibling ``host`` package importable without touching it.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HOST_DIR = os.path.join(_REPO_ROOT, "host")
if _HOST_DIR not in sys.path:
    sys.path.insert(0, _HOST_DIR)

from dlt645_converter import (  # noqa: E402
    FrameDecoder,
    ProtocolError,
    build_read_request,
    decode_frame,
    format_address,
    parse_address,
)
from dlt645_database import SQLiteStore  # noqa: E402

# Phase A is present on single-phase home meters; B/C are optional. The host
# meter returns error 0x03 for the B/C voltage identifiers, so phase A is the
# safe default and B/C are only polled when explicitly requested.
_PHASE_CODES = {
    "a": (0x02010100,),
    "ab": (0x02010100, 0x02010200),
    "abc": (0x02010100, 0x02010200, 0x02010300),
}


class TcpMeter:
    """Minimal TCP transport for a DL/T 645 meter or simulator."""

    def __init__(self, host: str, port: int, timeout: float = 1.5) -> None:
        self.sock = socket.create_connection((host, port), timeout=5.0)
        self.sock.settimeout(timeout)

    def write(self, payload: bytes) -> None:
        self.sock.sendall(payload)

    def read(self, timeout: float) -> bytes:
        self.sock.settimeout(timeout)
        try:
            return self.sock.recv(4096)
        except socket.timeout:
            return b""

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class MeterPoller(threading.Thread):
    """Poll one meter on a fixed interval and append results to SQLite."""

    def __init__(
        self,
        config,
        on_sample: Optional[Callable[[dict], None]] = None,
        log: Callable[[str], None] = print,
    ) -> None:
        super().__init__(name="meter-poller", daemon=True)
        self.config = config
        self.on_sample = on_sample
        self.log = log
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        host, port = self.config.poll_host
        address = parse_address(self.config.meter_address)
        codes = _PHASE_CODES.get(self.config.phases, _PHASE_CODES["a"])
        meter = TcpMeter(host, port, self.config.poll_timeout)
        store = SQLiteStore(self.config.db_path)
        try:
            while not self._stop_event.is_set():
                cycle_started = time.monotonic()
                for code in codes:
                    if self._stop_event.is_set():
                        break
                    for result in self._read(meter, address, code):
                        store.save(result)
                        if self.on_sample is not None and result.get("ok"):
                            self.on_sample(result)
                elapsed = time.monotonic() - cycle_started
                self._stop_event.wait(max(0.0, self.config.poll_interval - elapsed))
        except OSError as exc:
            self.log(f"poller stopped: {exc}")
        finally:
            meter.close()
            store.close()

    def _read(self, meter: TcpMeter, address: bytes, code: int) -> Iterator[dict]:
        """Send one read request and yield the decoded response (or an error)."""
        decoder = FrameDecoder()
        meter.write(build_read_request(address, code, self.config.protocol, preamble_count=4))
        deadline = time.monotonic() + self.config.poll_timeout
        while time.monotonic() < deadline:
            chunk = meter.read(min(0.2, deadline - time.monotonic()))
            if not chunk:
                continue
            for response in decoder.feed(chunk):
                if response.address_wire != address:
                    continue
                try:
                    result = decode_frame(response, self.config.protocol, code)
                except ProtocolError as exc:
                    result = {
                        "ok": False,
                        "error": str(exc),
                        "raw": response.raw.hex().upper(),
                        "address": format_address(address),
                        "data_identifier": f"0x{code:08X}",
                    }
                result.setdefault("address", format_address(address))
                yield result
                return
        yield {
            "ok": False,
            "error": "response timeout",
            "address": format_address(address),
            "data_identifier": f"0x{code:08X}",
        }
