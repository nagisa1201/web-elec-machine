#!/usr/bin/env python3
"""SQLite persistence for DL/T 645 polling results."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from dlt645_converter import format_address


class SQLiteStore:
    """Append-only local store for meter samples and communication errors."""

    def __init__(self, path: str) -> None:
        self.path = str(Path(path).expanduser())
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS meter_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recorded_at TEXT NOT NULL,
                meter_address TEXT NOT NULL,
                protocol TEXT NOT NULL,
                data_identifier TEXT,
                data_name TEXT,
                value REAL,
                value_text TEXT,
                unit TEXT,
                ok INTEGER NOT NULL,
                error TEXT,
                data_decoded TEXT,
                raw_hex TEXT NOT NULL
            )
            """
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_meter_readings_time "
            "ON meter_readings(meter_address, recorded_at)"
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_meter_readings_code "
            "ON meter_readings(meter_address, data_identifier, recorded_at)"
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS outages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                meter_address TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    def save(self, result: dict[str, Any]) -> None:
        """Persist one decoded response, timeout, or meter error response."""
        value = result.get("value")
        numeric_value: Optional[float]
        value_text: Optional[str]
        if isinstance(value, bool):
            numeric_value, value_text = None, str(value)
        elif isinstance(value, (int, float)):
            numeric_value, value_text = float(value), None
        elif value is None:
            numeric_value, value_text = None, None
        else:
            numeric_value, value_text = None, str(value)
        error = result.get("error")
        if error is None and result.get("error_code") is not None:
            error = f"meter error code 0x{int(result['error_code']):02X}"
        self.connection.execute(
            """
            INSERT INTO meter_readings (
                recorded_at, meter_address, protocol, data_identifier, data_name,
                value, value_text, unit, ok, error, data_decoded, raw_hex
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                result.get("address", "unknown"),
                result.get("protocol", "DLT645-unknown"),
                result.get("data_identifier") or result.get("requested_data_identifier"),
                result.get("data_name"),
                numeric_value,
                value_text,
                result.get("unit", ""),
                1 if result.get("ok") else 0,
                str(error) if error is not None else None,
                result.get("data_decoded"),
                result.get("raw", ""),
            ),
        )
        self.connection.commit()

    def save_outage(self, meter_address: str, started_at: datetime, ended_at: datetime) -> None:
        """Persist one power-outage interval detected by the acquisition loop."""
        self.connection.execute(
            "INSERT INTO outages (meter_address, started_at, ended_at) VALUES (?, ?, ?)",
            (
                meter_address,
                started_at.isoformat(timespec="milliseconds"),
                ended_at.isoformat(timespec="milliseconds"),
            ),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "SQLiteStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class OutageTracker:
    """Turn per-cycle poll success into persisted power-outage intervals.

    The acquisition loop calls :meth:`update` once per poll cycle, passing
    whether any reading in that cycle succeeded. A cycle with no successful
    reading means the meter stopped answering — the line went dead or the meter
    lost power — so the tracker records the failure and the subsequent
    recovery as one ``outages`` row through ``SQLiteStore.save_outage``.

    ``meter_address`` is the same wire-order ``bytes`` produced by
    ``dlt645_converter.parse_address``; it is converted to the conventional
    human-order string so it lines up with the ``meter_readings`` table.
    """

    def __init__(self, store: Optional[SQLiteStore], meter_address: bytes | str) -> None:
        self.store = store
        if isinstance(meter_address, (bytes, bytearray)):
            meter_address = format_address(bytes(meter_address))
        self.meter_address = meter_address
        self._outage_start: Optional[datetime] = None

    def update(self, ok: bool, timestamp: datetime) -> None:
        """Record one poll cycle and open/close the outage interval as needed."""
        if ok:
            self._close(timestamp)
        elif self._outage_start is None:
            self._outage_start = timestamp

    def finalize(self, timestamp: datetime) -> None:
        """Close any still-open interval; call once on shutdown."""
        self._close(timestamp)

    def _close(self, timestamp: datetime) -> None:
        if self._outage_start is None:
            return
        if self.store is not None and timestamp > self._outage_start:
            self.store.save_outage(self.meter_address, self._outage_start, timestamp)
        self._outage_start = None
