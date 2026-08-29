#!/usr/bin/env python3
"""Unit tests for the read-only data store and outage detection."""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from web.datastore import DataStore, detect_outages, Sample  # noqa: E402

TZ = timezone(timedelta(hours=8))
METER = "123456789012"
SCHEMA = """
CREATE TABLE meter_readings (
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
);
CREATE TABLE outages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meter_address TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL
)
"""


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def make_db(rows) -> str:
    """Create a temporary store and insert ``(local_dt, data_name, value)`` rows."""
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    for dt, name, value in rows:
        conn.execute(
            "INSERT INTO meter_readings "
            "(recorded_at, meter_address, protocol, data_identifier, data_name, value, unit, ok, raw_hex) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (_utc(dt), METER, "DLT645-2007", "0x02010100", name, value, "V", 1, ""),
        )
    conn.commit()
    conn.close()
    return path


def at(day: str, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime.fromisoformat(f"{day}T{hour:02d}:{minute:02d}:{second:02d}").replace(tzinfo=TZ)


def sample(day: str, hour: int, minute: int, second: int, value: float) -> Sample:
    return Sample(at(day, hour, minute, second), value, "a")


class OutageDetectionTests(unittest.TestCase):
    def test_gap_between_readings_is_an_outage(self):
        samples = [sample("2026-08-24", 0, m, 0, 230.0) for m in range(0, 3)]  # 0:00-0:02
        samples.append(sample("2026-08-24", 0, 6, 0, 231.0))  # 4-minute gap
        outages = detect_outages(samples, gap_seconds=120.0, low_volts=30.0)
        self.assertEqual(len(outages), 1)
        self.assertAlmostEqual(outages[0].seconds, 240.0, delta=1.0)

    def test_low_voltage_reading_is_an_outage(self):
        samples = [
            sample("2026-08-24", 0, 0, 0, 230.0),
            sample("2026-08-24", 0, 0, 5, 2.0),  # below 30 V => outage
            sample("2026-08-24", 0, 0, 10, 230.0),
        ]
        outages = detect_outages(samples, gap_seconds=120.0, low_volts=30.0)
        self.assertEqual(len(outages), 1)
        self.assertAlmostEqual(outages[0].seconds, 5.0, delta=1.0)

    def test_leading_gap_is_not_an_outage(self):
        # First reading arrives long after midnight; no false positive.
        samples = [sample("2026-08-24", 1, 0, 0, 230.0), sample("2026-08-24", 1, 0, 5, 230.0)]
        outages = detect_outages(samples, gap_seconds=120.0, low_volts=30.0)
        self.assertEqual(outages, [])


class DataStoreTests(unittest.TestCase):
    def test_meters_and_days(self):
        path = make_db([
            (at("2026-08-24", 9, 0), "phase_a_voltage", 230.5),
            (at("2026-08-25", 9, 0), "phase_a_voltage", 231.0),
        ])
        store = DataStore(path, tz=TZ)
        self.assertEqual(store.meters(), [METER])
        self.assertEqual(store.days(METER), ["2026-08-25", "2026-08-24"])

    def test_missing_db_returns_empty(self):
        store = DataStore("/nonexistent/nowhere.sqlite3", tz=TZ)
        self.assertFalse(store.available())
        self.assertEqual(store.meters(), [])
        self.assertEqual(store.days(METER), [])

    def test_minute_buckets_average_values(self):
        path = make_db([
            (at("2026-08-24", 10, 0, 10), "phase_a_voltage", 230.0),
            (at("2026-08-24", 10, 0, 50), "phase_a_voltage", 232.0),
        ])
        store = DataStore(path, tz=TZ)
        series = store.daily_series(METER, "2026-08-24")
        self.assertEqual(series["phases"], ["a"])
        self.assertEqual(len(series["series"][0]["points"]), 1)
        self.assertAlmostEqual(series["series"][0]["points"][0][1], 231.0)

    def test_daily_stats_max_min(self):
        # One-minute spacing keeps the samples below the 120 s outage gap.
        path = make_db([
            (at("2026-08-24", 8, 0, 0), "phase_a_voltage", 220.0),
            (at("2026-08-24", 8, 1, 0), "phase_a_voltage", 245.0),
            (at("2026-08-24", 8, 2, 0), "phase_a_voltage", 210.0),
        ])
        store = DataStore(path, tz=TZ)
        stats = store.stats(METER, "2026-08-24")
        self.assertEqual(stats.sample_count, 3)
        self.assertEqual(stats.maximum.value, 245.0)
        self.assertEqual(stats.minimum.value, 210.0)
        self.assertEqual(stats.maximum.time.minute, 1)
        self.assertEqual(stats.minimum.time.minute, 2)
        self.assertEqual(stats.outage_count, 0)

    def test_stats_detects_outage_gap(self):
        path = make_db([
            (at("2026-08-24", 10, 0, 0), "phase_a_voltage", 230.0),
            (at("2026-08-24", 10, 5, 0), "phase_a_voltage", 230.0),  # 5-minute gap
        ])
        store = DataStore(path, tz=TZ)
        stats = store.stats(METER, "2026-08-24")
        self.assertEqual(stats.outage_count, 1)
        self.assertGreater(stats.outage_seconds, 0)

    def test_stats_merges_acquisition_layer_outages(self):
        # Gap-free samples plus one outage interval recorded by the acquisition
        # layer's ``outages`` table must both survive the merge.
        path = make_db([
            (at("2026-08-24", 8, 0, 0), "phase_a_voltage", 220.0),
            (at("2026-08-24", 8, 1, 0), "phase_a_voltage", 221.0),
        ])
        conn = sqlite3.connect(path)
        conn.execute(
            "INSERT INTO outages (meter_address, started_at, ended_at) VALUES (?, ?, ?)",
            (METER, _utc(at("2026-08-24", 8, 5, 0)), _utc(at("2026-08-24", 8, 9, 0))),
        )
        conn.commit()
        conn.close()
        store = DataStore(path, tz=TZ)
        stats = store.stats(METER, "2026-08-24")
        self.assertEqual(stats.outage_count, 1)
        self.assertAlmostEqual(stats.outage_seconds, 240.0, delta=1.0)


if __name__ == "__main__":
    unittest.main()
