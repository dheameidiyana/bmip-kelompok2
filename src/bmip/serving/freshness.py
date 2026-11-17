"""Freshness policy for the serving tier (W1-D).

Two different things are called "stale" in the platform and they must not be
confused:

* ``freshness.status`` is about the **age of the data** relative to its SLO.
* the ``X-Data-Stale`` HTTP header is about the **serving path** falling back
  from the lake to PostgreSQL.

This module only owns the first one. It is pure so it can be unit-tested
without a database, and it supports a replay clock (``BMIP_AS_OF``) that is
always echoed in the response so nobody mistakes replay time for wall time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

OK = "ok"
WARN = "warn"
STALE = "stale"
UNKNOWN = "unknown"

STATUSES = (OK, WARN, STALE, UNKNOWN)


def now_utc(as_of: datetime | None = None) -> datetime:
    return as_of or datetime.now(UTC)


def parse_as_of(raw: str | None) -> datetime | None:
    """Parse BMIP_AS_OF; an empty or invalid value means the wall clock."""
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def hour_end(window_start: datetime) -> datetime:
    """A one-hour bar that starts at T is only complete at T + 1 hour."""
    return window_start + timedelta(hours=1)


def classify(age_seconds: float | None, slo_seconds: int) -> str:
    """ok inside the SLO, warn inside twice the SLO, stale beyond it."""
    if age_seconds is None:
        return UNKNOWN
    if slo_seconds <= 0:
        return UNKNOWN
    age = max(float(age_seconds), 0.0)
    if age <= slo_seconds:
        return OK
    if age <= 2 * slo_seconds:
        return WARN
    return STALE


@dataclass(frozen=True)
class Freshness:
    metric: str
    data_ts: datetime | None
    age_seconds: float | None
    slo_seconds: int
    status: str
    as_of: datetime
    clock: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "data_ts": iso(self.data_ts),
            "age_seconds": None
            if self.age_seconds is None
            else round(self.age_seconds, 3),
            "slo_seconds": self.slo_seconds,
            "status": self.status,
            "as_of": iso(self.as_of),
            "clock": self.clock,
        }


def compute(
    metric: str,
    data_ts: datetime | None,
    slo_seconds: int,
    *,
    now: datetime | None = None,
    clock: str = "live",
) -> Freshness:
    as_of = now_utc(now)
    age: float | None = None
    if data_ts is not None:
        if data_ts.tzinfo is None:
            data_ts = data_ts.replace(tzinfo=UTC)
        age = (as_of - data_ts).total_seconds()
    return Freshness(
        metric=metric,
        data_ts=data_ts,
        age_seconds=age,
        slo_seconds=slo_seconds,
        status=classify(age, slo_seconds),
        as_of=as_of,
        clock=clock,
    )


def clock_for(explicit: datetime | None) -> tuple[datetime, str]:
    """Return the effective clock and its label (``live`` or ``replay``)."""
    if explicit is not None:
        return explicit, "replay"
    return now_utc(), "live"


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
