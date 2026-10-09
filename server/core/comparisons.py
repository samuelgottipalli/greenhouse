"""
Period comparisons for the Analysis page: today against yesterday, this week
against last week, this month against last month.

For each, :func:`windows` gives the current period so far, the previous
period up to the same point (same time yesterday; same weekday and time last
week; same date and time last month, or its last day if it was shorter), and
the whole previous period. :func:`curves` returns both periods as averages on
a shared axis, for one chart: hours of the day (day), hours since Monday 00:00
(week) or the day of the month (month; complete days only, as today's average
so far would mislead). :func:`compare` gives like-for-like
figures: the current period so far against the previous one up to the same
point.

Weeks start on Monday. Everything uses the local calendar of the display zone,
and the raw readings (kept for 6 months; ``core/history.py``). Rain is
summed (totals per hour or day) instead of averaged.
"""
import calendar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from pandas import DataFrame, to_datetime

from core import db, history
from core.timeutil import utc_timestamp

KINDS = ("day", "week", "month")
STEP = {"day": "hour", "week": "hour", "month": "day"}  # how finely each comparison is charted


@dataclass(frozen=True)
class Windows:
    """The periods one comparison looks at (aware local datetimes)."""

    kind: str
    current_start: datetime
    now: datetime
    previous_start: datetime
    previous_same_point: datetime  # the previous period, up to where the current one is now
    previous_end: datetime         # the whole previous period ends here (= current_start)


def windows(kind: str, now: datetime, zone: str) -> Windows:
    """
    The current and previous periods for a comparison.

    Args:
        kind (str): ``"day"``, ``"week"`` or ``"month"``.
        now (datetime): Now (aware).
        zone (str): IANA zone.

    Returns:
        Windows: See the class.
    """
    tz = ZoneInfo(zone)
    local = now.astimezone(tz)
    midnight = datetime(local.year, local.month, local.day, tzinfo=tz)
    if kind == "day":
        start = midnight
        before = midnight - timedelta(days=1)
        before = datetime(before.year, before.month, before.day, tzinfo=tz)
        same_point = before + (local - start)
    elif kind == "week":
        monday = midnight - timedelta(days=local.weekday())
        start = datetime(monday.year, monday.month, monday.day, tzinfo=tz)
        last_monday = start - timedelta(days=7)
        before = datetime(last_monday.year, last_monday.month, last_monday.day, tzinfo=tz)
        same_point = before + (local - start)
    elif kind == "month":
        start = datetime(local.year, local.month, 1, tzinfo=tz)
        year, month = (local.year, local.month - 1) if local.month > 1 else (local.year - 1, 12)
        before = datetime(year, month, 1, tzinfo=tz)
        day = min(local.day, calendar.monthrange(year, month)[1])
        same_point = datetime(year, month, day, local.hour, local.minute, local.second, tzinfo=tz)
    else:
        raise ValueError(f"Unknown comparison {kind!r}")
    return Windows(kind, start, local, before, min(same_point, start), start)


def readings(source: str, device_id: int, measure: str, start: datetime, end: datetime,
             place: dict | None = None) -> DataFrame:
    """
    Raw readings of one measure in a period, with their times.

    Args:
        source (str): ``"greenhouse"`` or ``"weather"``.
        device_id (int): Controller (greenhouse only).
        measure (str): A key of ``history.MEASURES[source]``.
        start (datetime): From (aware), inclusive.
        end (datetime): To (aware), exclusive.
        place (dict | None): For weather: only readings for this location.

    Returns:
        DataFrame: ``time`` (aware, in ``start``'s zone) and ``value`` (stored
        units; light in lux; rain in mm per 15 minutes). Empty if none.
    """
    period = {"start": utc_timestamp(start.astimezone(timezone.utc)),
              "end": utc_timestamp(end.astimezone(timezone.utc))}
    if source == "greenhouse":
        data = db._read(
            "SELECT r.reading_utc AS t, r.value FROM sensor_readings r JOIN measures m ON m.measure_id = r.measure_id "
            "WHERE r.device_id = :device AND m.name = :name AND r.reading_utc >= :start AND r.reading_utc < :end "
            "ORDER BY r.reading_utc", dict(period, device=device_id, name=history.SENSOR_NAMES[measure]))
    else:
        column = history.WEATHER_COLUMNS[measure]
        where = ""
        if place is not None:
            where = " AND abs(latitude - :lat) <= :d AND abs(longitude - :lon) <= :d"
            from core.places import SAME_PLACE_DEGREES

            period.update(lat=place["latitude"], lon=place["longitude"], d=SAME_PLACE_DEGREES)
        data = db._read(
            f"SELECT measured_utc AS t, {column} AS value FROM weather_readings WHERE measured_utc >= :start "
            f"AND measured_utc < :end AND {column} IS NOT NULL{where} ORDER BY measured_utc", period)
    if data is None:
        return DataFrame({"time": [], "value": []})
    frame = DataFrame({"time": to_datetime(data["t"]).dt.tz_localize("UTC").dt.tz_convert(start.tzinfo),
                       "value": data["value"].astype(float)})
    if measure == "light":
        from core.light import raw_to_lux

        frame["value"] = frame["value"].map(raw_to_lux)
    return frame


def position(kind: str, moment, period_start: datetime) -> float:
    """
    Where a time sits on a comparison's shared axis.

    Returns:
        float: Hour of the day (day), hours since the week's Monday 00:00
        (week), or the day of the month (month).
    """
    if kind == "month":
        return float(moment.day)
    return (moment - period_start).total_seconds() / 3600


def curve(frame: DataFrame, kind: str, period_start: datetime, total: bool) -> DataFrame:
    """
    Averages (or totals, for rain) per hour or per day on the shared axis.

    Args:
        frame (DataFrame): From :func:`readings`.
        kind (str): The comparison.
        period_start (datetime): Start of this period (aware).
        total (bool): Sum instead of averaging.

    Returns:
        DataFrame: ``x`` and ``value``, one row per hour or day with readings.
    """
    if frame.empty:
        return DataFrame({"x": [], "value": []})
    step = frame["time"].dt.floor("h") if STEP[kind] == "hour" else frame["time"].dt.normalize()
    grouped = frame.groupby(step)["value"]
    values = grouped.sum() if total else grouped.mean()
    return DataFrame({"x": [position(kind, moment, period_start) for moment in values.index],
                      "value": values.round(3).to_numpy()})


def curves(source: str, device_id: int, measure: str, now: datetime, zone: str, kind: str,
           place: dict | None = None) -> tuple[DataFrame, Windows]:
    """
    Both periods of a comparison, ready to chart together.

    Returns:
        tuple[DataFrame, Windows]: ``period`` (``"current"`` or ``"previous"``),
        ``x`` and ``value``; and the windows used.
    """
    w = windows(kind, now, zone)
    total = measure == "rain"
    current = curve(readings(source, device_id, measure, w.current_start, w.now, place), kind, w.current_start, total)
    if kind == "month":
        # Today is only part-way through: its average (say, just the night hours) would mislead.
        current = current[current["x"] < w.now.day]
    previous = curve(readings(source, device_id, measure, w.previous_start, w.previous_end, place), kind,
                     w.previous_start, total)
    return (DataFrame({"period": ["current"] * len(current) + ["previous"] * len(previous),
                       "x": list(current["x"]) + list(previous["x"]),
                       "value": list(current["value"]) + list(previous["value"])}), w)


def compare(source: str, device_id: int, measure: str, now: datetime, zone: str, kind: str,
            place: dict | None = None) -> dict:
    """
    Like-for-like figures: the current period so far against the previous one
    up to the same point.

    Returns:
        dict: ``current`` and ``previous``, each ``history.statistics`` (with
        the total for rain) or None without readings.
    """
    w = windows(kind, now, zone)
    total = measure == "rain"
    now_values = readings(source, device_id, measure, w.current_start, w.now, place)["value"]
    then_values = readings(source, device_id, measure, w.previous_start, w.previous_same_point, place)["value"]
    return {"current": history.statistics(now_values, with_total=total),
            "previous": history.statistics(then_values, with_total=total)}
