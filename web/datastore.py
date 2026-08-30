#!/usr/bin/env python3
"""Read-only data access and statistics over the DL/T 645 SQLite store.

This module is deliberately independent of the HTTP and acquisition layers so
it can be unit tested without a server or a meter. It only ever ``SELECT``s;
the acquisition layer (``host/dlt645_usb.py --poll --db`` or ``web.poller``)
owns writes. Every timestamp is converted to the configured local timezone so
that "a day" means a local calendar day on the board.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

VOLTAGE_NAMES = ("phase_a_voltage", "phase_b_voltage", "phase_c_voltage")
_PHASE_BY_NAME = {
    "phase_a_voltage": "a",
    "phase_b_voltage": "b",
    "phase_c_voltage": "c",
}
_PHASE_ORDER = ("a", "b", "c")


@dataclass(frozen=True)
class Sample:
    """One voltage reading, timestamped in the configured local timezone."""

    timestamp: datetime
    value: float
    phase: str  # 'a' | 'b' | 'c'


@dataclass(frozen=True)
class Outage:
    """A single period of power loss."""

    start: datetime
    end: datetime
    seconds: float


@dataclass(frozen=True)
class Extremum:
    """A maximum or minimum reading and when it happened."""

    value: float
    time: datetime
    phase: str


@dataclass(frozen=True)
class DailyStats:
    """Aggregated view of one local day's voltage behaviour."""

    date: str
    sample_count: int
    maximum: Optional[Extremum]
    minimum: Optional[Extremum]
    outage_count: int
    outage_seconds: float
    outages: tuple[Outage, ...]


def detect_outages(
    samples: list[Sample],
    *,
    gap_seconds: float,
    low_volts: float,
    end: Optional[datetime] = None,
    ongoing: bool = False,
) -> list[Outage]:
    """Find power-outage intervals in a time-ordered list of samples.

    A region counts as an outage when either:

    * two consecutive readings are separated by more than ``gap_seconds`` —
      a live meter reports every few seconds, so a long silence means the line
      went dead, or
    * a reading drops below ``low_volts`` V (near zero on a 220 V line).

    A gap before the first reading is *not* treated as an outage: it is
    indistinguishable from the monitor being switched off. A trailing
    low-voltage run is closed at ``end`` when one is supplied.

    When ``ongoing`` is True the observation is still live up to ``end`` (the
    current day), so a reading-free tail longer than ``gap_seconds`` is also
    reported as an outage still in progress at ``end`` — the meter has stopped
    answering *now*, rather than the day simply having no data yet.
    """
    ordered = sorted(samples, key=lambda s: s.timestamp)
    outages: list[Outage] = []
    in_outage = False
    outage_start: Optional[datetime] = None

    def close(at: datetime) -> None:
        nonlocal in_outage, outage_start
        if in_outage:
            outages.append(Outage(outage_start, at, (at - outage_start).total_seconds()))
            in_outage = False
            outage_start = None

    previous: Optional[datetime] = None
    for sample in ordered:
        now = sample.timestamp
        if previous is not None:
            gap = (now - previous).total_seconds()
            if gap > gap_seconds and not in_outage:
                in_outage = True
                outage_start = previous
        if sample.value < low_volts:
            if not in_outage:
                in_outage = True
                outage_start = now
        else:
            close(now)
        previous = now

    if end is not None and previous is not None:
        if ongoing and not in_outage and (end - previous).total_seconds() > gap_seconds:
            in_outage = True
            outage_start = previous
    if in_outage and end is not None:
        close(end)
    return outages


def _merge_outages(*groups: list[Outage]) -> list[Outage]:
    """Merge several outage lists into non-overlapping intervals.

    Acquisition-layer outages (from the ``outages`` table) may overlap the
    gap / low-voltage outages inferred locally, so both are normalised here
    into a single, sorted, non-overlapping sequence for ``stats`` to sum.
    """
    ordered = sorted((outage for group in groups for outage in group), key=lambda o: o.start)
    merged: list[Outage] = []
    for outage in ordered:
        if merged and outage.start <= merged[-1].end:
            if outage.end > merged[-1].end:
                last = merged[-1]
                merged[-1] = Outage(last.start, outage.end, (outage.end - last.start).total_seconds())
        else:
            merged.append(outage)
    return merged


class DataStore:
    """Read-only facade over the shared ``meter_readings`` SQLite table."""

    def __init__(
        self,
        path: str,
        tz: timezone | None = None,
        *,
        outage_gap_seconds: float = 120.0,
        outage_low_volts: float = 30.0,
    ) -> None:
        self.path = str(Path(path).expanduser())
        self.tz = tz or timezone(timedelta(hours=8))
        self.outage_gap_seconds = outage_gap_seconds
        self.outage_low_volts = outage_low_volts

    # ------------------------------------------------------------------ utils

    def available(self) -> bool:
        """Whether the backing database exists and is readable."""
        return os.path.exists(self.path)

    def _localize(self, iso: str) -> datetime:
        return datetime.fromisoformat(iso).astimezone(self.tz)

    def _utc_iso(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat(timespec="milliseconds")

    def _tz_modifier(self) -> str:
        minutes = int(self.tz.utcoffset(None).total_seconds() // 60)
        return f"{minutes:+d} minutes"

    def _connect(self) -> sqlite3.Connection:
        # Read-only URI so a busy writer (WAL mode) never blocks readers.
        connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    def _query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return connection.execute(sql, params).fetchall()

    def _day_bounds(self, day: str) -> tuple[datetime, datetime]:
        start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=self.tz)
        return start, start + timedelta(days=1)

    # ----------------------------------------------------------------- queries

    def meters(self) -> list[str]:
        """Meter addresses that have at least one valid voltage reading."""
        if not self.available():
            return []
        rows = self._query(
            "SELECT DISTINCT meter_address FROM meter_readings "
            "WHERE data_name IN (?,?,?) AND ok = 1 AND value IS NOT NULL "
            "ORDER BY meter_address",
            VOLTAGE_NAMES,
        )
        return [row["meter_address"] for row in rows]

    def days(self, meter: str) -> list[str]:
        """Local calendar days holding voltage data, newest first."""
        if not self.available():
            return []
        rows = self._query(
            "SELECT DISTINCT date(recorded_at, ?) AS day FROM meter_readings "
            "WHERE meter_address = ? AND data_name IN (?,?,?) "
            "AND ok = 1 AND value IS NOT NULL ORDER BY day DESC",
            (self._tz_modifier(), meter, *VOLTAGE_NAMES),
        )
        return [row["day"] for row in rows]

    def latest_sample_at(self) -> Optional[datetime]:
        """Local timestamp of the newest row in the store, if any."""
        if not self.available():
            return None
        rows = self._query("SELECT recorded_at FROM meter_readings ORDER BY id DESC LIMIT 1")
        return self._localize(rows[0]["recorded_at"]) if rows else None

    def samples(self, meter: str, start: datetime, end: datetime) -> list[Sample]:
        """Valid voltage samples in the local ``[start, end)`` interval."""
        if not self.available():
            return []
        rows = self._query(
            "SELECT recorded_at, value, data_name FROM meter_readings "
            "WHERE meter_address = ? AND data_name IN (?,?,?) "
            "AND ok = 1 AND value IS NOT NULL "
            "AND recorded_at >= ? AND recorded_at < ? "
            "ORDER BY recorded_at ASC",
            (meter, *VOLTAGE_NAMES, self._utc_iso(start), self._utc_iso(end)),
        )
        return [
            Sample(self._localize(row["recorded_at"]), float(row["value"]),
                   _PHASE_BY_NAME[row["data_name"]])
            for row in rows
        ]

    def outages(self, meter: str, start: datetime, end: datetime) -> list[Outage]:
        """Outage intervals recorded by the acquisition layer, clipped to the window."""
        if not self.available():
            return []
        try:
            rows = self._query(
                "SELECT started_at, ended_at FROM outages "
                "WHERE meter_address = ? AND started_at < ? AND ended_at > ? "
                "ORDER BY started_at ASC",
                (meter, self._utc_iso(end), self._utc_iso(start)),
            )
        except sqlite3.OperationalError:
            # The ``outages`` table is created by the acquisition layer; a store
            # written by an older or simpler collector may lack it. Treat that as
            # "no acquisition-layer intervals to merge" rather than failing stats.
            return []
        result: list[Outage] = []
        for row in rows:
            started = self._localize(row["started_at"])
            ended = self._localize(row["ended_at"])
            if started < start:
                started = start
            if ended > end:
                ended = end
            if ended > started:
                result.append(Outage(started, ended, (ended - started).total_seconds()))
        return result

    # ----------------------------------------------------------------- series

    def recent_series(self, meter: str, minutes: int = 60) -> dict:
        """Raw samples over the last ``minutes`` for the live chart."""
        end = datetime.now(self.tz) + timedelta(seconds=1)
        start = end - timedelta(minutes=minutes)
        samples = self.samples(meter, start, end)
        return {
            "meter": meter,
            "minutes": minutes,
            "phases": sorted({sample.phase for sample in samples}),
            "series": self._to_series(samples, bucket_minutes=0),
        }

    def daily_series(self, meter: str, day: str) -> dict:
        """Minute-averaged samples for one local day (the history chart)."""
        start, end = self._day_bounds(day)
        samples = self.samples(meter, start, end)
        return {
            "meter": meter,
            "date": day,
            "phases": sorted({sample.phase for sample in samples}),
            "series": self._to_series(samples, bucket_minutes=1),
        }

    def _to_series(self, samples: list[Sample], bucket_minutes: int) -> list[dict]:
        """Group samples into per-phase ``[iso_timestamp, value]`` series."""
        buckets: dict[str, dict[datetime, list[float]]] = {p: {} for p in _PHASE_ORDER}
        for sample in samples:
            key = sample.timestamp
            if bucket_minutes:
                key = datetime(key.year, key.month, key.day, key.hour, key.minute, tzinfo=key.tzinfo)
            buckets[sample.phase].setdefault(key, []).append(sample.value)

        result: list[dict] = []
        for phase in _PHASE_ORDER:
            grouped = buckets[phase]
            if not grouped:
                continue
            points = [
                [key.isoformat(timespec="seconds"), round(sum(values) / len(values), 2)]
                for key, values in sorted(grouped.items())
            ]
            result.append({"phase": phase, "points": points})
        return result

    # ---------------------------------------------------------------- statistics

    def stats(self, meter: str, day: str, now: Optional[datetime] = None) -> DailyStats:
        """Daily maximum/minimum voltage and power-outage totals.

        For the current day the observation window ends at "now" rather than
        midnight, so a meter that has gone silent (still in progress) is
        reported as an ongoing outage instead of being silently dropped.
        ``now`` is injectable so tests can pin the observation instant.
        """
        start, day_end = self._day_bounds(day)
        if now is None:
            now = datetime.now(self.tz)
        ongoing = now < day_end
        end = now if ongoing else day_end
        samples = self.samples(meter, start, end)

        maximum = minimum = None
        if samples:
            highest = max(samples, key=lambda s: s.value)
            lowest = min(samples, key=lambda s: s.value)
            maximum = Extremum(highest.value, highest.timestamp, highest.phase)
            minimum = Extremum(lowest.value, lowest.timestamp, lowest.phase)

        outages = _merge_outages(
            detect_outages(
                samples,
                gap_seconds=self.outage_gap_seconds,
                low_volts=self.outage_low_volts,
                end=end,
                ongoing=ongoing,
            ),
            self.outages(meter, start, end),
        )
        return DailyStats(
            date=day,
            sample_count=len(samples),
            maximum=maximum,
            minimum=minimum,
            outage_count=len(outages),
            outage_seconds=sum(outage.seconds for outage in outages),
            outages=tuple(outages),
        )

    def recent_stats(self, meter: str, days: int = 7) -> list[DailyStats]:
        """Stats for the most recent ``days`` calendar days that have data."""
        return [self.stats(meter, day) for day in self.days(meter)[:days]]
