"""
Monthly summaries for the Analysis page, and the monthly job that makes
them and trims old readings.

Raw readings are kept for ``KEEP_RAW_MONTHS`` (6) whole months. Each finished
month is summarised per measure into ``monthly_stats``: the number of
samples, mean, median, quartiles (25th and 75th percentiles), the 2.5th and
97.5th percentiles (the middle 95 %), minimum and maximum; for rain also the
month's total. Summaries are small and kept for good, so the Analysis page
can compare a month with the same month last year without the raw data.

:func:`run_monthly` does the work and only what is missing, so it is safe to
run at any time and as often as needed. It is scheduled for the 1st of each
month and again shortly after every start of the server, which catches up a
1st that was missed while the computer was off (``greenhouse-retention.timer``;
``run_all.py`` on Windows and macOS).

Months follow the local calendar of ``settings.TIMEZONE``.

What is summarised (``MEASURES``):

* **greenhouse**, per controller: temperature (°C), humidity (%), light
  (estimated lux, from the raw light reading);
* **weather**: temperature (°C), humidity (%), wind speed (km/h), and rain as
  daily totals (mm per day), whose sum is the month's total.
"""
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from pandas import DataFrame, Series, to_datetime
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from core import db, settings
from core.timeutil import utc_timestamp

log = logging.getLogger(__name__)

KEEP_RAW_MONTHS = 6
BACKUP_DIR: Path = settings.SERVER_DIR / "data" / "backups"
BACKUPS_KEPT = 3
STAT_COLUMNS = ("samples", "mean", "median", "p2_5", "p25", "p75", "p97_5", "minimum", "maximum", "total")
# source -> measure -> (label, stored unit); see the module docstring.
MEASURES: dict[str, dict[str, tuple[str, str]]] = {
    "greenhouse": {"temperature": ("Temperature", "°C"), "humidity": ("Humidity", "%"), "light": ("Light", "lux")},
    "weather": {"temperature": ("Temperature", "°C"), "humidity": ("Humidity", "%"),
                "wind": ("Wind speed", "km/h"), "rain": ("Rain per day", "mm")},
}
SENSOR_NAMES = {"temperature": "temperature", "humidity": "humidity", "light": "light_raw"}
WEATHER_COLUMNS = {"temperature": "temperature_c", "humidity": "relative_humidity_pct",
                   "wind": "wind_speed_kmh", "rain": "precipitation_mm"}
WEATHER_DEVICE = 0
STATE_KEYS = {"month": "history_summarised_through", "utc": "history_job_utc", "result": "history_job_result"}


# --- months ------------------------------------------------------------------------


def month_key(day: date) -> str:
    """``"YYYY-MM"`` for a date."""
    return f"{day.year:04d}-{day.month:02d}"


def add_months(month: str, count: int) -> str:
    """Move a ``"YYYY-MM"`` month by ``count`` months (negative goes back)."""
    year, number = int(month[:4]), int(month[5:7]) - 1 + count
    return f"{year + number // 12:04d}-{number % 12 + 1:02d}"


def month_range(first: str, last: str) -> list[str]:
    """Every month from ``first`` to ``last``, inclusive."""
    months = []
    while first <= last:
        months.append(first)
        first = add_months(first, 1)
    return months


def month_bounds(month: str, zone: str | None = None) -> tuple[str, str]:
    """
    A local calendar month as UTC timestamps.

    Args:
        month (str): ``"YYYY-MM"``.
        zone (str | None): IANA zone (default ``settings.TIMEZONE``).

    Returns:
        tuple[str, str]: Start (inclusive) and end (exclusive), ``YYYY-MM-DD HH:MM:SS`` UTC.
    """
    tz = ZoneInfo(zone or settings.TIMEZONE)
    start = datetime(int(month[:4]), int(month[5:7]), 1, tzinfo=tz)
    following = add_months(month, 1)
    end = datetime(int(following[:4]), int(following[5:7]), 1, tzinfo=tz)
    return utc_timestamp(start), utc_timestamp(end)


def current_month(now: datetime | None = None, zone: str | None = None) -> str:
    """This month in the local calendar."""
    moment = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(zone or settings.TIMEZONE))
    return month_key(moment.date())


def month_of(timestamp_utc: str, zone: str | None = None) -> str:
    """The local month of a ``YYYY-MM-DD HH:MM:SS`` UTC timestamp."""
    moment = datetime.strptime(timestamp_utc, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return current_month(moment, zone)


# --- samples and statistics -----------------------------------------------------------


def samples(source: str, device_id: int, measure: str, start_utc: str, end_utc: str,
            zone: str | None = None) -> Series:
    """
    The raw values of one measure in a period, in stored units (see ``MEASURES``).

    Args:
        source (str): ``"greenhouse"`` or ``"weather"``.
        device_id (int): Controller (ignored for weather).
        measure (str): A key of ``MEASURES[source]``.
        start_utc (str): Start, inclusive.
        end_utc (str): End, exclusive.
        zone (str | None): For rain's daily totals (local days).

    Returns:
        Series: The values; empty if there are none.
    """
    period = {"start": start_utc, "end": end_utc}
    if source == "greenhouse":
        data = db._read(
            "SELECT r.value FROM sensor_readings r JOIN measures m ON m.measure_id = r.measure_id "
            "WHERE r.device_id = :device AND m.name = :name AND r.reading_utc >= :start AND r.reading_utc < :end",
            dict(period, device=device_id, name=SENSOR_NAMES[measure]),
        )
        if data is None:
            return Series(dtype=float)
        values = data["value"].astype(float)
        if measure == "light":
            from core.light import raw_to_lux

            values = values.map(raw_to_lux)
        return values.reset_index(drop=True)
    column = WEATHER_COLUMNS[measure]
    data = db._read(
        f"SELECT measured_utc, {column} AS value FROM weather_readings "
        f"WHERE measured_utc >= :start AND measured_utc < :end AND {column} IS NOT NULL",
        period,
    )
    if data is None:
        return Series(dtype=float)
    if measure != "rain":
        return data["value"].astype(float).reset_index(drop=True)
    # Rain: each reading is the preceding 15 minutes; the sample is each local day's total.
    local = to_datetime(data["measured_utc"]).dt.tz_localize("UTC").dt.tz_convert(zone or settings.TIMEZONE)
    return data["value"].astype(float).groupby(local.dt.date).sum().reset_index(drop=True)


def statistics(values: Series, with_total: bool = False) -> dict | None:
    """
    Summarise values: count, mean, median, quartiles, middle 95 %, min and max.

    Args:
        values (Series): Numbers.
        with_total (bool): Also their sum (rain).

    Returns:
        dict | None: Keys ``STAT_COLUMNS``; None for no values.
    """
    values = values.dropna()
    if values.empty:
        return None
    quantiles = values.quantile([0.025, 0.25, 0.5, 0.75, 0.975])
    return {
        "samples": int(values.size), "mean": round(float(values.mean()), 3),
        "median": round(float(quantiles[0.5]), 3), "p2_5": round(float(quantiles[0.025]), 3),
        "p25": round(float(quantiles[0.25]), 3), "p75": round(float(quantiles[0.75]), 3),
        "p97_5": round(float(quantiles[0.975]), 3), "minimum": round(float(values.min()), 3),
        "maximum": round(float(values.max()), 3),
        "total": round(float(values.sum()), 3) if with_total else None,
    }


def month_statistics(source: str, device_id: int, measure: str, month: str, zone: str | None = None) -> dict | None:
    """Statistics of one measure over one local month, from the raw readings (None without any)."""
    start, end = month_bounds(month, zone)
    return statistics(samples(source, device_id, measure, start, end, zone), with_total=measure == "rain")


# --- stored summaries -----------------------------------------------------------------


def stored(source: str, device_id: int, measure: str, first: str, last: str) -> DataFrame | None:
    """
    Stored monthly summaries from ``first`` to ``last`` (``"YYYY-MM"``, inclusive).

    Returns:
        DataFrame | None: ``month`` and the ``STAT_COLUMNS``; None if none.
    """
    return db._read(
        "SELECT month, " + ", ".join(STAT_COLUMNS) + " FROM monthly_stats WHERE source = :source "
        "AND device_id = :device AND measure = :measure AND month >= :first AND month <= :last ORDER BY month",
        {"source": source, "device": device_id if source == "greenhouse" else WEATHER_DEVICE, "measure": measure,
         "first": first, "last": last},
    )


def save(source: str, device_id: int, measure: str, month: str, stats: dict, now: datetime | None = None) -> bool:
    """Store (or replace) one month's summary."""
    row = dict(stats, source=source, device_id=device_id, measure=measure, month=month,
               computed_utc=utc_timestamp(now or datetime.now(timezone.utc)))
    columns = ", ".join(row)
    return db._write([(f"INSERT OR REPLACE INTO monthly_stats ({columns}) VALUES ("
                       + ", ".join(f":{name}" for name in row) + ")", row)])


def year_view(source: str, device_id: int, measure: str, now: datetime | None = None,
              zone: str | None = None) -> DataFrame | None:
    """
    The last 13 months of one measure: this month (so far, from the raw
    readings) and the 12 before it (stored summaries; a finished month not yet
    summarised is worked out from its raw readings).

    Returns:
        DataFrame | None: ``month``, the ``STAT_COLUMNS`` and ``live`` (True for
        the current month), oldest first; None without any data.
    """
    this = current_month(now, zone)
    first = add_months(this, -12)
    rows = {}
    kept = stored(source, device_id, measure, first, add_months(this, -1))
    if kept is not None:
        for record in kept.to_dict("records"):
            rows[record["month"]] = dict(record, live=False)
    for month in month_range(first, this):
        if month in rows and month != this:
            continue
        stats = month_statistics(source, device_id, measure, month, zone)
        if stats:
            rows[month] = dict(stats, month=month, live=month == this)
    if not rows:
        return None
    return DataFrame([rows[month] for month in sorted(rows)])


# --- the monthly job ------------------------------------------------------------------


def earliest_month(zone: str | None = None) -> str | None:
    """The local month of the oldest raw reading (greenhouse or weather), or None."""
    data = db._read("SELECT min(t) AS t FROM (SELECT min(reading_utc) AS t FROM sensor_readings "
                    "UNION ALL SELECT min(measured_utc) FROM weather_readings)", none_if_empty=False)
    if data is None or data["t"].isna().all():
        return None
    return month_of(str(data["t"].iloc[0]), zone)


def series() -> list[tuple[str, int, str]]:
    """Every (source, device, measure) that gets summaries: each controller's, and the weather's."""
    devices = sorted(db.list_devices() or {})
    return ([("greenhouse", device, measure) for device in devices for measure in MEASURES["greenhouse"]]
            + [("weather", WEATHER_DEVICE, measure) for measure in MEASURES["weather"]])


def summarised(source: str, device_id: int, measure: str) -> set[str]:
    """Months already summarised for one series."""
    data = db._read("SELECT month FROM monthly_stats WHERE source = :s AND device_id = :d AND measure = :m",
                    {"s": source, "d": device_id, "m": measure})
    return set() if data is None else set(data["month"])


def backup(folder: Path, month: str, keep: int = BACKUPS_KEPT) -> Path:
    """
    Copy the database before readings are deleted, keeping the newest ``keep`` copies.

    Returns:
        Path: The new backup.
    """
    from core import migrations

    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"before-monthly-trim-{month}.db"
    target.unlink(missing_ok=True)
    conn = migrations.connect(settings.sqlite_path(settings.DB_URL))
    try:
        migrations.backup_to(conn, target)
    finally:
        conn.close()
    for old in sorted(folder.glob("before-monthly-trim-*.db"))[:-keep]:
        old.unlink()
    return target


def delete_before(cutoff_utc: str) -> dict[str, int] | None:
    """Delete raw greenhouse and weather readings older than a cut-off, in one transaction."""
    try:
        with db.get_engine().begin() as conn:
            sensor = conn.execute(text("DELETE FROM sensor_readings WHERE reading_utc < :c"),
                                  {"c": cutoff_utc}).rowcount
            weather = conn.execute(text("DELETE FROM weather_readings WHERE measured_utc < :c"),
                                   {"c": cutoff_utc}).rowcount
    except SQLAlchemyError as err:
        log.error("Deleting old readings failed: %s", err)
        return None
    return {"sensor_rows": sensor, "weather_rows": weather}


def run_monthly(now: datetime | None = None, keep_months: int = KEEP_RAW_MONTHS, zone: str | None = None,
                backup_dir: Path | None = None) -> dict:
    """
    Summarise every finished month that isn't yet, then delete raw readings
    older than ``keep_months`` whole months, but only months that are summarised.

    Safe to run at any time: a second run finds nothing to do. Before deleting
    anything the database is copied to ``backup_dir`` (default
    ``BACKUP_DIR``, ``server/data/backups``).

    Args:
        now (datetime | None): Current time (aware); default now.
        keep_months (int): Whole months of raw readings to keep, besides this one.
        zone (str | None): IANA zone for the months (default ``settings.TIMEZONE``).
        backup_dir (Path | None): Where to copy the database first.

    Returns:
        dict: ``summarised`` (list of ``"source/device/measure/month"``),
        ``deleted`` (row counts, or None), ``cutoff_utc``, ``backup`` (path or
        None) and ``ok``.
    """
    now = now or datetime.now(timezone.utc)
    this = current_month(now, zone)
    last_finished = add_months(this, -1)
    first = earliest_month(zone)
    report = {"summarised": [], "deleted": None, "cutoff_utc": None, "backup": None, "ok": True}
    if first is not None:
        for source, device, measure in series():
            done = summarised(source, device, measure)
            for month in month_range(first, last_finished):
                if month in done:
                    continue
                stats = month_statistics(source, device, measure, month, zone)
                if stats is None:
                    continue
                if not save(source, device, measure, month, stats, now):
                    report["ok"] = False
                    log.error("Could not store the summary of %s %s %s %s", source, device, measure, month)
                    continue
                report["summarised"].append(f"{source}/{device}/{measure}/{month}")

    keep_from = add_months(this, -keep_months)
    cutoff, _ = month_bounds(keep_from, zone)
    report["cutoff_utc"] = cutoff
    old = db._read("SELECT count(*) AS n FROM (SELECT 1 FROM sensor_readings WHERE reading_utc < :c "
                   "UNION ALL SELECT 1 FROM weather_readings WHERE measured_utc < :c)", {"c": cutoff},
                   none_if_empty=False)
    to_delete = 0 if old is None else int(old["n"].iloc[0])
    if report["ok"] and to_delete:
        folder = backup_dir or BACKUP_DIR
        report["backup"] = str(backup(folder, this))
        report["deleted"] = delete_before(cutoff)
        report["ok"] = report["deleted"] is not None
        if report["ok"]:
            from core.retention import vacuum

            vacuum()
    db.save_preferences({STATE_KEYS["month"]: last_finished, STATE_KEYS["utc"]: utc_timestamp(now),
                         STATE_KEYS["result"]: "ok" if report["ok"] else "failed"})
    return report


def last_run() -> dict:
    """When the monthly job last ran and how it went (for the Analysis page)."""
    preferences = db.read_preferences()
    return {name: preferences.get(key) for name, key in STATE_KEYS.items()}
