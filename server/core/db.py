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


# --- Device telemetry (written by services/ingest.py) ----------------------


def insert_sensor_readings(
    values: dict[str, float],
    reading_utc: str,
    device_id: int = settings.DEVICE_ID,
) -> int | None:
    """
    Store one timestamped set of sensor values, skipping duplicates.

    The device may resend queued telemetry after a reconnect, so a reading
    that is already stored (same device, measure and time) is ignored.

    Args:
        values (dict[str, float]): Measure name (e.g. ``"temperature"``) to value.
        reading_utc (str): ``YYYY-MM-DD HH:MM:SS`` UTC.
        device_id (int): Reporting device.

    Returns:
        int | None: Number of new rows, or None on a database error (including
        an unknown measure name, in which case nothing is stored).
    """
    rows = [{"device_id": device_id, "measure": name, "at": reading_utc, "value": float(value)}
            for name, value in values.items()]
    if not rows:
        return 0
    try:
        with get_engine().begin() as conn:
            inserted = 0
            for row in rows:
                result = conn.execute(text(
                    "INSERT OR IGNORE INTO sensor_readings (device_id, measure_id, reading_utc, value) "
                    "SELECT :device_id, measure_id, :at, :value FROM measures WHERE name = :measure"
                ), row)
                if result.rowcount == 0 and conn.execute(
                    text("SELECT 1 FROM measures WHERE name = :measure"), row
                ).first() is None:
                    raise ValueError(f"Unknown measure {row['measure']!r}")
                inserted += result.rowcount
    except (SQLAlchemyError, ValueError) as err:
        log.error("Storing readings failed: %s", err)
        return None
    return inserted


def record_relay_state(
    relay_id: int,
    state: int,
    source: str,
    event_utc: str,
    device_id: int = settings.DEVICE_ID,
) -> bool | None:
    """
    Log a relay state reported by the device, unless it is already the latest.

    The web app and automation log their own commands, and the device echoes
    every change (and repeats retained states on reconnect), so an event is
    only added when the reported state differs from the last logged one.

    Args:
        relay_id (int): Relay number, 1-8.
        state (int): 1 on, 0 off.
        source (str): ``"auto"``, ``"web"`` or ``"device"``.
        event_utc (str): ``YYYY-MM-DD HH:MM:SS`` UTC.
        device_id (int): Reporting device.

    Returns:
        bool | None: True if logged, False if it matched the latest state,
        None on a database error.
    """
    current = _read(
        "SELECT state FROM relay_events WHERE device_id = :device_id AND relay_id = :relay_id "
        "ORDER BY event_utc DESC, event_id DESC LIMIT 1",
        {"device_id": device_id, "relay_id": int(relay_id)},
        none_if_empty=False,
    )
    if current is None:
        return None
    if not current.empty and int(current.iloc[0]["state"]) == int(state):
        return False
    return log_relay_event(relay_id, state, source, device_id=device_id, event_utc=event_utc) or None


def set_device_status(status: str, updated_utc: str, device_id: int = settings.DEVICE_ID) -> bool:
    """
    Record a device's online/offline status.

    Args:
        status (str): ``"online"`` or ``"offline"``.
        updated_utc (str): ``YYYY-MM-DD HH:MM:SS`` UTC.
        device_id (int): Device.

    Returns:
        bool: True if stored.
    """
    return _write([(
        "INSERT INTO device_status VALUES (:device_id, :status, :at) "
        "ON CONFLICT (device_id) DO UPDATE SET status = excluded.status, updated_utc = excluded.updated_utc",
        {"device_id": device_id, "status": status, "at": updated_utc},
    )])


def device_status(device_id: int = settings.DEVICE_ID) -> dict[str, str] | None:
    """
    Read a device's last reported status.

    Args:
        device_id (int): Device.

    Returns:
        dict[str, str] | None: ``status`` and ``updated_utc``, or None if the
        device never reported (or on error).
    """
    data = _read(
        "SELECT status, updated_utc FROM device_status WHERE device_id = :device_id",
        {"device_id": device_id},
    )
    return None if data is None else data.iloc[0].to_dict()


# --- Display preferences ------------------------------------------------------


def read_preferences() -> dict[str, str]:
    """
    Read the stored dashboard preferences.

    Returns:
        dict[str, str]: Key to value; empty if none are stored or on error.
    """
    data = _read("SELECT key, value FROM app_preferences")
    return {} if data is None else dict(zip(data["key"], data["value"]))


def save_preferences(preferences: dict[str, str]) -> bool:
    """
    Store dashboard preferences, replacing values for the given keys.

    Args:
        preferences (dict[str, str]): Key to value.

    Returns:
        bool: True if stored.
    """
    if not preferences:
        return True
    return _write([(
        "INSERT INTO app_preferences VALUES (:key, :value) "
        "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        [{"key": k, "value": str(v)} for k, v in preferences.items()],
    )])
