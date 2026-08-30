#!/usr/bin/env python3
"""Standard-library HTTP server and JSON API for the voltage-monitoring UI.

Pure ``http.server`` so it runs on the RDK X5 without any third-party package.
The request handler only translates between HTTP and the :class:`DataStore`;
all data and statistics logic lives in ``web.datastore``. Each API handler is a
module-level function taking ``(app, params)`` so it can be tested directly
without opening a socket.
"""

from __future__ import annotations

import json
import mimetypes
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .config import NOMINAL_VOLTS, SERVICE_NAME, SERVICE_VERSION, Config
from .datastore import DailyStats, DataStore

_PHASE_LABEL = {"a": "A相", "b": "B相", "c": "C相"}
_PHASE_COLOR = {"a": "#4f8cff", "b": "#34d399", "c": "#f59e0b"}


class Application:
    """Shared per-process context: config, data store and optional poller."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.store = DataStore(
            config.db_path,
            tz=config.tz,
            outage_gap_seconds=config.outage_gap_seconds,
            outage_low_volts=config.outage_low_volts,
        )
        self.started_at = time.time()
        self.poller = None
        if config.poll_tcp:
            from .poller import MeterPoller

            self.poller = MeterPoller(config)

    def uptime(self) -> float:
        return time.time() - self.started_at


# -------------------------------------------------------------------- payloads


def _iso(value) -> str:
    return value.isoformat(timespec="seconds")


def _stats_dict(stats: DailyStats) -> dict:
    maximum = minimum = None
    if stats.maximum is not None:
        maximum = {"value": stats.maximum.value, "time": _iso(stats.maximum.time),
                   "phase": stats.maximum.phase}
    if stats.minimum is not None:
        minimum = {"value": stats.minimum.value, "time": _iso(stats.minimum.time),
                   "phase": stats.minimum.phase}
    return {
        "date": stats.date,
        "samples": stats.sample_count,
        "max": maximum,
        "min": minimum,
        "outage_count": stats.outage_count,
        "outage_seconds": round(stats.outage_seconds, 1),
        "outages": [
            {"start": _iso(outage.start), "end": _iso(outage.end),
             "seconds": round(outage.seconds, 1)}
            for outage in stats.outages
        ],
    }


def _with_phase_meta(series: list[dict]) -> list[dict]:
    return [
        {"phase": item["phase"], "label": _PHASE_LABEL.get(item["phase"], item["phase"]),
         "color": _PHASE_COLOR.get(item["phase"], "#9ca3af"), "points": item["points"]}
        for item in series
    ]


# ------------------------------------------------------------------- handlers


def api_health(app: Application, params: dict) -> dict:
    meters = app.store.meters()
    latest_at = app.store.latest_sample_at()
    return {
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "ok": True,
        "uptime_seconds": round(app.uptime(), 1),
        "db": app.store.path,
        "db_available": app.store.available(),
        "polling": app.poller is not None,
        "meters": meters,
        "latest_at": _iso(latest_at) if latest_at else None,
        # Monitoring semantics the UI uses to draw the reference line and to
        # classify a reading as normal / low / high / outage.
        "nominal_volts": NOMINAL_VOLTS,
        "outage_low_volts": app.config.outage_low_volts,
        "outage_gap_seconds": app.config.outage_gap_seconds,
    }


def api_meters(app: Application, params: dict) -> dict:
    return {"meters": app.store.meters()}


def api_days(app: Application, params: dict) -> dict:
    meter = _require_meter(app, params)
    return {"meter": meter, "days": app.store.days(meter)}


def api_realtime(app: Application, params: dict) -> dict:
    meter = _require_meter(app, params)
    minutes = _int_param(params, "minutes", app.config.realtime_minutes)
    payload = app.store.recent_series(meter, minutes)
    payload["series"] = _with_phase_meta(payload["series"])
    # The board's clock is the authority for "now" on the live chart; the UI
    # compares sample timestamps against it, never against the phone's clock.
    payload["server_now"] = _iso(datetime.now(app.store.tz))
    return payload


def api_series(app: Application, params: dict) -> dict:
    meter = _require_meter(app, params)
    day = _str_param(params, "date")
    if day is None:
        raise ApiError(400, "missing required parameter: date")
    payload = app.store.daily_series(meter, day)
    payload["series"] = _with_phase_meta(payload["series"])
    return payload


def api_stats(app: Application, params: dict) -> dict:
    meter = _require_meter(app, params)
    if "date" in params:
        day = _str_param(params, "date")
        return _stats_dict(app.store.stats(meter, day))
    days = _int_param(params, "days", 7)
    items = [_stats_dict(stats) for stats in app.store.recent_stats(meter, days)]
    return {"meter": meter, "days": days, "items": items}


_API_ROUTES = {
    "/api/health": api_health,
    "/api/meters": api_meters,
    "/api/days": api_days,
    "/api/realtime": api_realtime,
    "/api/series": api_series,
    "/api/stats": api_stats,
}


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _require_meter(app: Application, params: dict) -> str:
    meter = _str_param(params, "meter")
    if not meter:
        available = app.store.meters()
        if not available:
            raise ApiError(400, "no meter data available and no 'meter' parameter given")
        meter = available[0]
    return meter


def _str_param(params: dict, name: str) -> str | None:
    values = params.get(name)
    return values[0] if values else None


def _int_param(params: dict, name: str, default: int) -> int:
    values = params.get(name)
    if not values:
        return default
    try:
        return int(values[0])
    except ValueError as exc:
        raise ApiError(400, f"parameter '{name}' must be an integer") from exc


# --------------------------------------------------------------------- server


class _Handler(BaseHTTPRequestHandler):
    server_version = f"{SERVICE_NAME}/{SERVICE_VERSION}"

    @property
    def app(self) -> Application:
        return self.server.application  # type: ignore[attr-defined]

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)
        try:
            if path in ("/", "/index.html"):
                self._serve_static("index.html")
            elif path.startswith("/static/"):
                self._serve_static(path[len("/static/"):])
            elif path in _API_ROUTES:
                self._send_json(200, _API_ROUTES[path](self.app, params))
            else:
                self._send_json(404, {"error": "not found"})
        except ApiError as exc:
            self._send_json(exc.status, {"error": exc.message})
        except Exception as exc:  # keep the server alive on unexpected input
            self._send_json(500, {"error": str(exc)})

    def _serve_static(self, relative: str) -> None:
        relative = relative.replace("\\", "/")
        if relative.startswith("/") or ".." in relative.split("/"):
            return self._send_json(404, {"error": "not found"})
        target = (self.app.config.static_dir / relative).resolve()
        if not target.is_file():
            return self._send_json(404, {"error": "not found"})
        data = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        # One compact line per request keeps the embedded console readable.
        print(f"[web] {self.address_string()} {format % args}")


class VoltageHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def create_server(config: Config) -> tuple[VoltageHTTPServer, Application]:
    app = Application(config)
    server = VoltageHTTPServer((config.host, config.port), _Handler)
    server.application = app  # type: ignore[attr-defined]
    return server, app


def run(config: Config) -> None:
    server, app = create_server(config)
    if app.poller is not None:
        app.poller.start()
        print(f"[web] polling meter {config.meter_address} via tcp {config.poll_tcp}")
    print(f"[web] {SERVICE_NAME} {SERVICE_VERSION} serving http://{config.host}:{config.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if app.poller is not None:
            app.poller.stop()
        server.server_close()
