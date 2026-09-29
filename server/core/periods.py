"""
Report periods: the preset lengths and a chosen date range, and how finely to
show them.

Charts show every reading for up to ``RAW_DAYS``, hourly averages for up to
``HOURLY_DAYS`` and daily averages beyond that, so a six-month range stays
light. Dates are local calendar days in the display zone. Raw readings go
back 6 months (``core/history.py``); older months are on the Analysis page.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from core.timeutil import utc_timestamp

PRESETS: dict[str, int] = {"24 hours": 1, "7 days": 7, "30 days": 30}
DATE_RANGE = "Date range"
RAW_DAYS = 2
HOURLY_DAYS = 45


@dataclass(frozen=True)
class Period:
    """A period to report on."""

    label: str        # e.g. "7 days" or "Sep 1 – Sep 28"
    since_utc: str    # inclusive, YYYY-MM-DD HH:MM:SS
    until_utc: str    # exclusive
    days: float       # length, for the chart axis

    @property
    def detail(self) -> str:
        """``"raw"``, ``"hour"`` or ``"day"``: how finely to chart it."""
        if self.days <= RAW_DAYS:
            return "raw"
        return "hour" if self.days <= HOURLY_DAYS else "day"

    @property
    def rain_step(self) -> str:
        """``"hour"`` or ``"day"``: rain totals per hour for up to a week, per day beyond."""
        return "hour" if self.days <= 7 else "day"


def preset(label: str, now: datetime | None = None) -> Period:
    """A preset period ending now, e.g. ``preset("7 days")``."""
    now = now or datetime.now(timezone.utc)
    days = PRESETS[label]
    return Period(label, utc_timestamp(now - timedelta(days=days)), utc_timestamp(now + timedelta(seconds=1)), days)


def date_range(start: date, end: date, zone: str) -> Period:
    """
    Whole local days from ``start`` to ``end`` (inclusive; swapped if reversed).

    Args:
        start (date): First day.
        end (date): Last day.
        zone (str): IANA zone (or ``"UTC"``).

    Returns:
        Period: From ``start`` 00:00 to the midnight after ``end``, local time.
    """
    if end < start:
        start, end = end, start
    tz = ZoneInfo(zone)
    since = datetime(start.year, start.month, start.day, tzinfo=tz)
    after = end + timedelta(days=1)
    until = datetime(after.year, after.month, after.day, tzinfo=tz)
    if start == end:
        label = f"{start:%b} {start.day}, {start.year}"
    elif start.year == end.year:
        label = f"{start:%b} {start.day} – {end:%b} {end.day}, {end.year}"
    else:
        label = f"{start:%b} {start.day}, {start.year} – {end:%b} {end.day}, {end.year}"
    return Period(label, utc_timestamp(since), utc_timestamp(until), (end - start).days + 1)
