"""
Data retention: keep recent sensor readings in full, older ones as hourly averages.

Raw readings arrive every 5 minutes (about 315,000 rows a year for three
measures). :func:`roll_up` replaces readings older than a cut-off with one
row per device, measure and hour, holding the average and timestamped at
the start of the hour, which is how the dashboard's long charts show them
anyway. Outdoor weather older than the cut-off keeps only its on-the-hour
snapshot (the collector stores one every 15 minutes). Relay events are kept
in full: they are the audit trail, and small.

Measured with ``python -m scripts.retention --measure``: about 2.6 MB of
growth per device per year, down from 15.6 MB without retention.

The cut-off is rounded down to a whole hour, so an hour is never split, and
running it again changes nothing.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from core import db
from core.timeutil import utc_timestamp

log = logging.getLogger(__name__)

KEEP_RAW_DAYS = 90


def cutoff_for(keep_days: int, now: datetime | None = None) -> str:
    """
    Return the retention cut-off: ``keep_days`` ago, rounded down to the hour.

    Args:
        keep_days (int): Days of full-resolution readings to keep.
        now (datetime | None): Current time (aware); defaults to now.

    Returns:
        str: ``YYYY-MM-DD HH:00:00`` UTC.
    """
    moment = (now or datetime.now(timezone.utc)) - timedelta(days=keep_days)
    return utc_timestamp(moment.replace(minute=0, second=0, microsecond=0))


def roll_up(before_utc: str) -> dict[str, int] | None:
    """
    Replace readings older than a cut-off with hourly averages, in one transaction.

    Hours that already hold a single row at ``HH:00:00`` (already rolled up)
    are left alone.

    Args:
        before_utc (str): Cut-off, ``YYYY-MM-DD HH:00:00`` UTC (exclusive).

    Returns:
        dict[str, int] | None: ``removed`` raw sensor rows (off the hour),
        ``added`` hourly rows and ``weather_removed`` 15-minute weather rows;
        None on a database error (nothing changed).
    """
    hour = "substr(reading_utc, 1, 13) || ':00:00'"
    params = {"before": before_utc}
    try:
        with db.get_engine().begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS temp.hourly"))
            conn.execute(text(
                "CREATE TEMP TABLE hourly AS "
                f"SELECT device_id, measure_id, {hour} AS hour, round(avg(value), 3) AS value "
                "FROM sensor_readings WHERE reading_utc < :before "
                f"GROUP BY device_id, measure_id, {hour} "
                f"HAVING count(*) > 1 OR max(reading_utc) <> {hour}"
            ), params)
            # Every bucket that needs work is in temp.hourly, so drop all raw rows
            # that are not on the hour, then write the averages; INSERT OR REPLACE
            # overwrites a raw reading that happened to fall exactly on the hour.
            removed = conn.execute(text(
                "DELETE FROM sensor_readings WHERE reading_utc < :before "
                "AND substr(reading_utc, 15, 5) <> '00:00'"
            ), params).rowcount
            added = conn.execute(text(
                "INSERT OR REPLACE INTO sensor_readings (device_id, measure_id, reading_utc, value) "
                "SELECT device_id, measure_id, hour, value FROM temp.hourly"
            )).rowcount
            conn.execute(text("DROP TABLE temp.hourly"))
            weather = conn.execute(text(
                "DELETE FROM weather_readings WHERE measured_utc < :before "
                "AND substr(measured_utc, 15, 5) <> '00:00'"
            ), params).rowcount
    except SQLAlchemyError as err:
        log.error("Retention roll-up failed: %s", err)
        return None
    return {"removed": removed, "added": added, "weather_removed": weather}


def vacuum() -> bool:
    """
    Return freed space to the file system (rewrites the database file).

    Returns:
        bool: True on success.
    """
    try:
        with db.get_engine().connect() as conn:
            conn.execute(text("VACUUM"))
    except SQLAlchemyError as err:
        log.error("VACUUM failed: %s", err)
        return False
    return True
