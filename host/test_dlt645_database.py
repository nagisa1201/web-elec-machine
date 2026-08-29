import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from dlt645_converter import parse_address
from dlt645_database import OutageTracker, SQLiteStore


class DatabaseTests(unittest.TestCase):
    def test_save_numeric_and_error_rows(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as database:
            with SQLiteStore(database.name) as store:
                store.save({
                    "ok": True,
                    "protocol": "DLT645-2007",
                    "address": "123456789012",
                    "data_identifier": "0x02010100",
                    "data_name": "phase_a_voltage",
                    "value": 226.6,
                    "unit": "V",
                    "data_decoded": "9955",
                    "raw": "6816",
                })
                store.save({
                    "ok": False,
                    "protocol": "DLT645-2007",
                    "address": "123456789012",
                    "requested_data_identifier": "0x02010200",
                    "data_name": "phase_b_voltage",
                    "error": "response timeout",
                    "raw": "",
                })
            rows = sqlite3.connect(database.name).execute(
                "select data_name, value, unit, ok, error from meter_readings order by id"
            ).fetchall()
        self.assertEqual(rows[0][0:4], ("phase_a_voltage", 226.6, "V", 1))
        self.assertEqual(rows[1][0], "phase_b_voltage")
        self.assertEqual(rows[1][3:], (0, "response timeout"))


class OutageTrackerTests(unittest.TestCase):
    def test_cycles_without_readings_are_recorded_as_one_outage(self):
        t0 = datetime(2026, 8, 24, 10, 0, 0, tzinfo=timezone.utc)
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as database:
            with SQLiteStore(database.name) as store:
                tracker = OutageTracker(store, parse_address("123456789012"))
                tracker.update(True, t0)  # healthy cycle
                tracker.update(False, t0 + timedelta(seconds=5))  # outage starts
                tracker.update(False, t0 + timedelta(seconds=10))
                tracker.update(True, t0 + timedelta(seconds=30))  # recovery
            rows = sqlite3.connect(database.name).execute(
                "select meter_address, started_at, ended_at from outages"
            ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "123456789012")
        self.assertEqual(rows[0][1], "2026-08-24T10:00:05.000+00:00")
        self.assertEqual(rows[0][2], "2026-08-24T10:00:30.000+00:00")

    def test_finalize_closes_open_outage(self):
        t0 = datetime(2026, 8, 24, 10, 0, 0, tzinfo=timezone.utc)
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as database:
            with SQLiteStore(database.name) as store:
                tracker = OutageTracker(store, parse_address("123456789012"))
                tracker.update(True, t0)
                tracker.update(False, t0 + timedelta(seconds=5))
                tracker.finalize(t0 + timedelta(seconds=60))
            rows = sqlite3.connect(database.name).execute(
                "select started_at, ended_at from outages"
            ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "2026-08-24T10:00:05.000+00:00")
        self.assertEqual(rows[0][1], "2026-08-24T10:01:00.000+00:00")

    def test_without_store_is_a_silent_noop(self):
        tracker = OutageTracker(None, parse_address("123456789012"))
        t0 = datetime(2026, 8, 24, 10, 0, 0, tzinfo=timezone.utc)
        tracker.update(False, t0)  # must not raise
        tracker.update(True, t0 + timedelta(seconds=5))
        tracker.finalize(t0 + timedelta(seconds=10))


if __name__ == "__main__":
    unittest.main()
