import sqlite3
import tempfile
import unittest

from dlt645_database import SQLiteStore


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


if __name__ == "__main__":
    unittest.main()
