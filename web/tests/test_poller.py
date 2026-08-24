#!/usr/bin/env python3
"""End-to-end test of the poller against the host TCP meter simulator.

This proves the decoupling works: the web poller reuses the host frame
converter and SQLite store and reads real values from a simulated meter.
"""

from __future__ import annotations

import os
import socketserver
import sqlite3
import sys
import tempfile
import threading
import time
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_HOST = os.path.join(_ROOT, "host")
for _p in (_ROOT, _HOST):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from web.config import Config  # noqa: E402
from web.poller import MeterPoller, TcpMeter  # noqa: E402
from dlt645_converter import parse_address  # noqa: E402
from dlt645_database import SQLiteStore  # noqa: E402
from dlt645_simulator import _make_handler  # noqa: E402


class _Simulator:
    def __init__(self):
        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True

        self.server = Server(("127.0.0.1", 0), _make_handler("2007"))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        return self.server.server_address[1]

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class PollerTests(unittest.TestCase):
    def test_single_read_against_simulator(self):
        sim = _Simulator()
        try:
            config = Config()
            config.poll_tcp = f"127.0.0.1:{sim.port}"
            config.meter_address = "123456789012"
            poller = MeterPoller(config, log=lambda _m: None)
            meter = TcpMeter("127.0.0.1", sim.port, timeout=1.5)
            try:
                address = parse_address("123456789012")
                results = list(poller._read(meter, address, 0x02010100))
            finally:
                meter.close()
            self.assertTrue(results[0]["ok"])
            self.assertAlmostEqual(results[0]["value"], 230.5)
            self.assertEqual(results[0]["data_name"], "phase_a_voltage")
        finally:
            sim.close()

    def test_poller_loop_writes_to_store(self):
        sim = _Simulator()
        fd, db_path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(fd)
        try:
            config = Config()
            config.poll_tcp = f"127.0.0.1:{sim.port}"
            config.meter_address = "123456789012"
            config.poll_interval = 0.2
            config.db_path = db_path
            SQLiteStore(db_path).close()  # create the table before the loop starts
            poller = MeterPoller(config, log=lambda _m: None)
            poller.start()

            deadline = time.time() + 6
            found = False
            while time.time() < deadline:
                conn = sqlite3.connect(db_path)
                count = conn.execute(
                    "SELECT COUNT(*) FROM meter_readings "
                    "WHERE data_name = 'phase_a_voltage' AND ok = 1"
                ).fetchone()[0]
                conn.close()
                if count > 0:
                    found = True
                    break
                time.sleep(0.1)

            poller.stop()
            poller.join(timeout=3)
            self.assertTrue(found, "poller never wrote a valid phase-A reading")
        finally:
            sim.close()


if __name__ == "__main__":
    unittest.main()
