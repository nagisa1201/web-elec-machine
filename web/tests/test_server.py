#!/usr/bin/env python3
"""Tests for the HTTP API handlers and the serving path (no external deps)."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from web.config import Config  # noqa: E402
from web.server import (  # noqa: E402
    ApiError,
    api_days,
    api_health,
    api_meters,
    api_realtime,
    api_series,
    api_stats,
    create_server,
)

TZ = timezone(timedelta(hours=8))
METER = "123456789012"
SCHEMA = """
CREATE TABLE meter_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT, recorded_at TEXT NOT NULL,
    meter_address TEXT NOT NULL, protocol TEXT NOT NULL, data_identifier TEXT,
    data_name TEXT, value REAL, value_text TEXT, unit TEXT, ok INTEGER NOT NULL,
    error TEXT, data_decoded TEXT, raw_hex TEXT NOT NULL
)
"""


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def make_db(rows) -> str:
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute(SCHEMA)
    for dt, name, value in rows:
        conn.execute(
            "INSERT INTO meter_readings "
            "(recorded_at, meter_address, protocol, data_identifier, data_name, value, unit, ok, raw_hex) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (_utc(dt), METER, "DLT645-2007", "0x02010100", name, value, "V", 1, ""),
        )
    conn.commit()
    conn.close()
    return path


def at(day: str, hour: int, minute: int = 0) -> datetime:
    return datetime.fromisoformat(f"{day}T{hour:02d}:{minute:02d}:00").replace(tzinfo=TZ)


def make_app(db_path):
    config = Config()
    config.db_path = db_path
    config.tz = TZ
    from web.server import Application

    return Application(config)


class ApiHandlerTests(unittest.TestCase):
    def test_health_without_data(self):
        app = make_app("/nonexistent/nope.sqlite3")
        payload = api_health(app, {})
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["db_available"])
        self.assertEqual(payload["meters"], [])

    def test_health_with_data(self):
        path = make_db([(at("2026-08-24", 9), "phase_a_voltage", 230.5)])
        app = make_app(path)
        payload = api_health(app, {})
        self.assertTrue(payload["db_available"])
        self.assertEqual(payload["meters"], [METER])
        self.assertIsNotNone(payload["latest_at"])

    def test_meters_and_days(self):
        path = make_db([(at("2026-08-24", 9), "phase_a_voltage", 230.5)])
        app = make_app(path)
        self.assertEqual(api_meters(app, {})["meters"], [METER])
        self.assertEqual(api_days(app, {"meter": [METER]})["days"], ["2026-08-24"])

    def test_realtime_requires_meter(self):
        app = make_app("/nonexistent/nope.sqlite3")
        with self.assertRaises(ApiError) as ctx:
            api_realtime(app, {})
        self.assertEqual(ctx.exception.status, 400)

    def test_series_requires_date(self):
        path = make_db([(at("2026-08-24", 9), "phase_a_voltage", 230.5)])
        app = make_app(path)
        with self.assertRaises(ApiError):
            api_series(app, {"meter": [METER]})

    def test_stats_returns_extrema(self):
        path = make_db([
            (at("2026-08-24", 8), "phase_a_voltage", 220.0),
            (at("2026-08-24", 12), "phase_a_voltage", 245.0),
        ])
        app = make_app(path)
        stats = api_stats(app, {"meter": [METER], "date": ["2026-08-24"]})
        self.assertEqual(stats["max"]["value"], 245.0)
        self.assertEqual(stats["min"]["value"], 220.0)


class ServerIntegrationTests(unittest.TestCase):
    def test_serves_api_static_and_blocks_traversal(self):
        path = make_db([(at("2026-08-24", 9), "phase_a_voltage", 230.5)])
        config = Config()
        config.host = "127.0.0.1"
        config.port = 0  # ephemeral
        config.db_path = path
        config.tz = TZ

        server, _ = create_server(config)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]
        base = f"http://127.0.0.1:{port}"
        try:
            with urllib.request.urlopen(base + "/api/health", timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertTrue(json.loads(response.read())["ok"])

            with urllib.request.urlopen(base + "/", timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertIn("无线电压监测系统", response.read().decode("utf-8"))

            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(base + "/static/../config.py", timeout=5)
            self.assertEqual(ctx.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
