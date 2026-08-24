#!/usr/bin/env python3
"""Runtime configuration for the voltage-monitoring web server.

Every tunable lives here so the HTTP, data and acquisition layers stay free of
magic numbers. Values are resolved from (highest precedence first):

1. command-line flags
2. ``WEB_*`` environment variables
3. the defaults below
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from pathlib import Path

SERVICE_NAME = "voltage-monitor"
SERVICE_VERSION = "1.0.0"

# Defaults shared with the README examples.
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8080
DEFAULT_DB = "meter_readings.sqlite3"
DEFAULT_TZ = "+08:00"  # board timezone (Asia/Shanghai)
DEFAULT_MINUTES = 60  # realtime window
DEFAULT_OUTAGE_GAP = 120.0  # seconds without a reading => outage
DEFAULT_OUTAGE_LOW = 30.0  # V below which a reading counts as outage
DEFAULT_POLL_INTERVAL = 5.0
DEFAULT_TIMEOUT = 1.5

# DL/T 645-2007 data identifiers for the three phase voltages.
PHASE_VOLTAGE_CODES = (0x02010100, 0x02010200, 0x02010300)


def parse_timezone(text: str) -> timezone:
    """Parse a fixed-offset timezone such as ``+08:00`` or ``-5``."""
    text = text.strip()
    if text.lower() in ("utc", "z", "+00:00", "0"):
        return timezone.utc
    sign = 1
    if text[:1] in "+-":
        if text[:1] == "-":
            sign = -1
        text = text[1:]
    if ":" in text:
        hours, minutes = text.split(":", 1)
        offset_minutes = int(hours) * 60 + int(minutes)
    else:
        offset_minutes = int(float(text) * 60)
    return timezone(sign * timedelta(minutes=offset_minutes))


@dataclass
class Config:
    """All settings for one server process."""

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    db_path: str = DEFAULT_DB
    tz: timezone = field(default_factory=lambda: parse_timezone(DEFAULT_TZ))

    # Optional in-process acquisition (a meter or simulator reachable over TCP).
    poll_tcp: str | None = None
    meter_address: str | None = None
    poll_interval: float = DEFAULT_POLL_INTERVAL
    poll_timeout: float = DEFAULT_TIMEOUT
    protocol: str = "2007"
    phases: str = "a"  # "a", "ab", or "abc"

    # Monitoring semantics.
    realtime_minutes: int = DEFAULT_MINUTES
    outage_gap_seconds: float = DEFAULT_OUTAGE_GAP
    outage_low_volts: float = DEFAULT_OUTAGE_LOW

    static_dir: Path = field(default_factory=lambda: Path(__file__).parent / "static")

    @property
    def poll_host(self) -> tuple[str, int] | None:
        """Return ``(host, port)`` when ``poll_tcp`` is set, else ``None``."""
        if not self.poll_tcp:
            return None
        host, sep, port = self.poll_tcp.rpartition(":")
        if not sep or not host or not port.isdigit():
            raise ValueError("--poll-tcp must look like HOST:PORT")
        return host, int(port)

    @classmethod
    def from_args(cls, argv: list[str] | None = None) -> "Config":
        parser = build_parser()
        args = parser.parse_args(argv)

        if args.poll_tcp and not args.meter:
            parser.error("--meter is required when --poll-tcp is set")

        cfg = cls()
        cfg.host = args.host or os.environ.get("WEB_HOST", cfg.host)
        cfg.port = args.port if args.port is not None else int(os.environ.get("WEB_PORT", cfg.port))
        cfg.db_path = args.db or os.environ.get("WEB_DB", cfg.db_path)
        cfg.tz = parse_timezone(args.tz or os.environ.get("WEB_TZ", DEFAULT_TZ))

        cfg.poll_tcp = args.poll_tcp or os.environ.get("WEB_POLL_TCP")
        cfg.meter_address = args.meter or os.environ.get("WEB_METER")
        cfg.poll_interval = args.interval if args.interval is not None else cfg.poll_interval
        cfg.poll_timeout = args.timeout if args.timeout is not None else cfg.poll_timeout
        cfg.protocol = args.version or cfg.protocol
        cfg.phases = args.phases or cfg.phases
        if cfg.phases not in ("a", "ab", "abc"):
            parser.error("--phases must be one of: a, ab, abc")

        cfg.realtime_minutes = args.minutes if args.minutes is not None else cfg.realtime_minutes
        cfg.outage_gap_seconds = args.outage_gap if args.outage_gap is not None else cfg.outage_gap_seconds
        cfg.outage_low_volts = args.outage_low if args.outage_low is not None else cfg.outage_low_volts

        # Validate the TCP endpoint shape eagerly so a typo fails fast.
        if cfg.poll_tcp:
            cfg.poll_host
        return cfg


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="web",
        description="Embedded voltage-monitoring web server for the RDK X5.",
    )
    server = parser.add_argument_group("server")
    server.add_argument("--host", help=f"bind address (default {DEFAULT_HOST})")
    server.add_argument("--port", type=int, help=f"listen port (default {DEFAULT_PORT})")
    server.add_argument("--db", help=f"SQLite readings path (default {DEFAULT_DB})")
    server.add_argument("--tz", help=f"board timezone offset, e.g. +08:00 (default {DEFAULT_TZ})")

    monitor = parser.add_argument_group("monitoring")
    monitor.add_argument("--minutes", type=int, help=f"realtime window in minutes (default {DEFAULT_MINUTES})")
    monitor.add_argument("--outage-gap", type=float, dest="outage_gap",
                         help=f"seconds without a reading that counts as an outage (default {DEFAULT_OUTAGE_GAP})")
    monitor.add_argument("--outage-low", type=float, dest="outage_low",
                         help=f"voltage in V below which a reading counts as an outage (default {DEFAULT_OUTAGE_LOW})")

    poll = parser.add_argument_group("acquisition (optional)")
    poll.add_argument("--poll-tcp", metavar="HOST:PORT",
                      help="poll a DL/T 645 meter or simulator reachable over TCP")
    poll.add_argument("--meter", help="meter address in human order, e.g. 123456789012")
    poll.add_argument("--interval", type=float, help=f"poll interval in seconds (default {DEFAULT_POLL_INTERVAL})")
    poll.add_argument("--timeout", type=float, help=f"meter response timeout in seconds (default {DEFAULT_TIMEOUT})")
    poll.add_argument("--version", choices=("1997", "2007"), help="DL/T 645 protocol version (default 2007)")
    poll.add_argument("--phases", choices=("a", "ab", "abc"),
                      help="which phase voltages to poll: a, ab, or abc (default a)")
    return parser
