"""
All database reads and writes for the web app and background services.

One SQLAlchemy engine is created per process and reused (SQLite foreign keys
are switched on for every connection). Read functions return a DataFrame, or
``None`` if the query failed or found no rows. Write functions return True on
success and False on a database error. Errors are logged, not raised.

Schema: ``core/schema.sql``. Timestamp and unit conventions: ``core/timeutil.py``.
"""
import logging
from functools import lru_cache

from pandas import DataFrame, read_sql
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.exc import SQLAlchemyError

from core import settings
from core.timeutil import utc_timestamp

log = logging.getLogger(__name__)

PROFILES: tuple[str, str] = ("current", "default")
RELAY_SOURCES: tuple[str, ...] = ("auto", "web", "device")


@lru_cache(maxsize=None)
def get_engine(url: str | None = None) -> Engine:
    """
    Return the shared engine for a database URL, creating it on first use.

    Args:
        url (str | None): SQLAlchemy URL. Defaults to ``settings.DB_URL``.

    Returns:
        Engine: Cached engine.
    """
    engine = create_engine(url or settings.DB_URL)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_conn, _record):
            dbapi_conn.execute("PRAGMA foreign_keys = ON")

    return engine


def _read(sql: str, params: dict | None = None, none_if_empty: bool = True) -> DataFrame | None:
    """
    Run a SELECT and return the rows.

    Args:
        sql (str): Query with ``:name`` parameters.
        params (dict | None): Parameter values.
        none_if_empty (bool): Return None instead of an empty DataFrame.

    Returns:
        DataFrame | None: Rows, or None on error (or when empty, if requested).
    """
    try:
        with get_engine().connect() as conn:
            data = read_sql(text(sql), conn, params=params or {})
    except (SQLAlchemyError, ValueError) as err:
        log.error("Query failed: %s", err)
        return None
    if none_if_empty and data.empty:
        return None
    return data


def _write(statements: list[tuple[str, dict | list[dict]]]) -> bool:
    """
    Run several write statements in one transaction.

    Args:
        statements (list[tuple[str, dict | list[dict]]]): SQL text and its
            parameters (a list of dicts runs the statement once per dict).

    Returns:
        bool: True if everything committed, False if it was rolled back.
    """
    try:
        with get_engine().begin() as conn:
            for sql, params in statements:
                conn.execute(text(sql), params)
    except (SQLAlchemyError, ValueError) as err:
        log.error("Write failed: %s", err)
        return False
    return True


# --- Reference data ----------------------------------------------------------


def unit_labels(units: str) -> dict[str, str] | None:
    """
    Return the display unit for each measure.

    Args:
        units (str): ``"SI"`` for metric units; anything else selects US units.

    Returns:
        dict[str, str] | None: Measure name (e.g. ``"temperature"``) to unit
        label (e.g. ``"°F"``), or None on error.
    """
    column = "si_unit" if units == "SI" else "us_unit"
    data = _read(f"SELECT name, {column} AS unit FROM measures")
    return None if data is None else dict(zip(data["name"], data["unit"]))


def relay_names(device_id: int = settings.DEVICE_ID) -> dict[int, str] | None:
    """
    Return the relay names of a device.

    Args:
        device_id (int): Device to read.

    Returns:
        dict[int, str] | None: Relay number to name, or None on error.
    """
    data = _read(
        "SELECT relay_id, name FROM relays WHERE device_id = :device_id ORDER BY relay_id",
        {"device_id": device_id},
    )
    return None if data is None else dict(zip(data["relay_id"], data["name"]))


# --- Automation settings -----------------------------------------------------


def read_thresholds(profile: str = "current", device_id: int = settings.DEVICE_ID) -> DataFrame | None:
    """
    Read the automation thresholds.

    Args:
        profile (str): ``"current"`` (in use) or ``"default"`` (factory).
        device_id (int): Device to read.

    Returns:
        DataFrame | None: Columns ``name`` (e.g. ``fan_on_temp_c``),
        ``relay_id``, ``value`` and ``buffer``; None on error or if empty.
    """
    return _read(
        "SELECT name, relay_id, value, buffer FROM thresholds "
        "WHERE device_id = :device_id AND profile = :profile ORDER BY name",
        {"device_id": device_id, "profile": profile},
    )


def read_watering_schedule(profile: str = "current", device_id: int = settings.DEVICE_ID) -> DataFrame | None:
    """
    Read the daily watering slots.

    Args:
        profile (str): ``"current"`` or ``"default"``.
        device_id (int): Device to read.

    Returns:
        DataFrame | None: Columns ``slot``, ``relay_id``, ``start_local``
        (``HH:MM``) and ``duration_min``; None on error or if empty.
    """
    return _read(
        "SELECT slot, relay_id, start_local, duration_min FROM watering_schedule "
        "WHERE device_id = :device_id AND profile = :profile ORDER BY slot",
        {"device_id": device_id, "profile": profile},
    )


def save_settings(
    thresholds: dict[str, tuple[float, float]],
    schedule: dict[int, tuple[str, int]],
    device_id: int = settings.DEVICE_ID,
) -> bool:
    """
    Update the current thresholds and watering slots in one transaction.

    Only the names and slots passed in are changed; others (e.g. the light
    threshold, which the UI does not edit) are kept.

    Args:
        thresholds (dict[str, tuple[float, float]]): Threshold name to
            ``(value, buffer)``; temperatures in °C.
        schedule (dict[int, tuple[str, int]]): Slot number to
            ``(start_local "HH:MM", duration_min)``.
        device_id (int): Device to update.

    Returns:
        bool: True if saved, False if nothing was changed because of an error
        (including an unknown name or slot).
    """
    threshold_rows = [
        {"device_id": device_id, "name": name, "value": float(value), "buffer": float(buffer)}
        for name, (value, buffer) in thresholds.items()
    ]
    slot_rows = [
        {"device_id": device_id, "slot": slot, "start": start, "minutes": int(minutes)}
        for slot, (start, minutes) in schedule.items()
    ]
    statements = []
    if threshold_rows:
        statements.append((
            "UPDATE thresholds SET value = :value, buffer = :buffer "
            "WHERE device_id = :device_id AND profile = 'current' AND name = :name",
            threshold_rows,
        ))
    if slot_rows:
        statements.append((
            "UPDATE watering_schedule SET start_local = :start, duration_min = :minutes "
            "WHERE device_id = :device_id AND profile = 'current' AND slot = :slot",
            slot_rows,
        ))
    expected = len(threshold_rows) + len(slot_rows)
    try:
        with get_engine().begin() as conn:
            changed = sum(
                conn.execute(text(sql), row).rowcount for sql, rows in statements for row in rows
            )
            if changed != expected:
                raise ValueError(f"Expected to update {expected} rows, matched {changed}")
    except (SQLAlchemyError, ValueError) as err:
        log.error("Saving settings failed: %s", err)
        return False
    return True


def restore_default_settings(device_id: int = settings.DEVICE_ID) -> bool:
    """
    Copy the default thresholds and watering slots over the current ones.

    Args:
        device_id (int): Device to reset.

    Returns:
        bool: True if restored, False on a database error.
    """
    params = {"device_id": device_id}
    return _write([
        ("DELETE FROM thresholds WHERE device_id = :device_id AND profile = 'current'", params),
        (
            "INSERT INTO thresholds SELECT device_id, 'current', name, relay_id, value, buffer "
            "FROM thresholds WHERE device_id = :device_id AND profile = 'default'",
            params,
        ),
        ("DELETE FROM watering_schedule WHERE device_id = :device_id AND profile = 'current'", params),
        (
            "INSERT INTO watering_schedule SELECT device_id, 'current', slot, relay_id, "
            "start_local, duration_min FROM watering_schedule "
            "WHERE device_id = :device_id AND profile = 'default'",
            params,
        ),
    ])


# --- Sensor readings and relay events ---------------------------------------


def latest_sensor_readings(device_id: int = settings.DEVICE_ID) -> DataFrame | None:
    """
    Read the most recent value of every measure a device has reported.

    Args:
        device_id (int): Device to read.

    Returns:
        DataFrame | None: Columns ``measure``, ``reading_utc`` and ``value``,
        one row per measure; None on error or if there are no readings.
    """
    return _read(
        "SELECT m.name AS measure, r.reading_utc, r.value "
        "FROM sensor_readings r JOIN measures m USING (measure_id) "
        "WHERE r.device_id = :device_id AND r.reading_utc = ("
        "  SELECT max(reading_utc) FROM sensor_readings "
        "  WHERE device_id = r.device_id AND measure_id = r.measure_id) "
        "ORDER BY m.name",
        {"device_id": device_id},
    )


def latest_relay_states(device_id: int = settings.DEVICE_ID) -> DataFrame | None:
    """
    Read the last logged event of every relay that has one.

    Args:
        device_id (int): Device to read.

    Returns:
        DataFrame | None: Columns ``relay_id``, ``relay`` (name), ``state``
        (1 on, 0 off), ``source`` and ``event_utc``; None on error or if no
        events exist.
    """
    return _read(
        "SELECT r.relay_id, r.name AS relay, e.state, e.source, e.event_utc "
        "FROM relays r JOIN relay_events e "
        "  ON e.device_id = r.device_id AND e.relay_id = r.relay_id "
        "WHERE r.device_id = :device_id AND e.event_id = ("
        "  SELECT event_id FROM relay_events "
        "  WHERE device_id = r.device_id AND relay_id = r.relay_id "
        "  ORDER BY event_utc DESC, event_id DESC LIMIT 1) "
        "ORDER BY r.relay_id",
        {"device_id": device_id},
    )


def log_relay_event(
    relay_id: int,
    state: int,
    source: str,
    device_id: int = settings.DEVICE_ID,
    event_utc: str | None = None,
) -> bool:
    """
    Append a relay change to ``relay_events``.

    Args:
        relay_id (int): Relay number, 1-8.
        state (int): 1 for on, 0 for off.
        source (str): ``"auto"``, ``"web"`` or ``"device"``.
        device_id (int): Device the relay belongs to.
        event_utc (str | None): ``YYYY-MM-DD HH:MM:SS`` UTC; defaults to now.

    Returns:
        bool: True if logged, False on a database error or invalid value.
    """
    return _write([(
        "INSERT INTO relay_events (device_id, relay_id, event_utc, state, source) "
        "VALUES (:device_id, :relay_id, :event_utc, :state, :source)",
        {
            "device_id": device_id,
            "relay_id": int(relay_id),
            "event_utc": event_utc or utc_timestamp(),
            "state": int(state),
            "source": source,
        },
    )])


# --- Weather ----------------------------------------------------------------


def recent_weather(limit: int = 216) -> DataFrame | None:
    """
    Read the most recent outdoor weather readings, newest first.

    Args:
        limit (int): Maximum number of rows (216 is about 2 days at 15 minutes).

    Returns:
        DataFrame | None: All ``weather_readings`` columns; None on error or if
        the table is empty.
    """
    return _read(
        "SELECT * FROM weather_readings ORDER BY measured_utc DESC LIMIT :limit",
        {"limit": limit},
    )


def insert_weather(row: dict[str, str | int | float | None] | None) -> bool:
    """
    Store one outdoor weather reading.

    Args:
        row (dict | None): Column name to value, as built by
            ``weather_api.clean_data``.

    Returns:
        bool: True if inserted; False if ``row`` is empty or the insert failed
        (e.g. a reading for that time already exists).
    """
    if not row:
        return False
    columns = ", ".join(row)
    values = ", ".join(f":{name}" for name in row)
    return _write([(f"INSERT INTO weather_readings ({columns}) VALUES ({values})", row)])
