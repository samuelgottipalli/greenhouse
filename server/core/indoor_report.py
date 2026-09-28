"""
Pure helpers behind the Home and Greenhouse Weather (indoor) pages: reading
ages, staleness, display values (light as estimated lux), chart-ready
history, highs and lows, and the readings table.
"""
from datetime import datetime

from pandas import DataFrame, to_datetime

from core.automation import READING_MAX_AGE
from core.conversions import celsius_to_fahrenheit
from core.light import raw_to_lux, round_lux
from core.timeutil import parse_utc_timestamp

PERIODS: dict[str, int] = {"24 hours": 1, "7 days": 7, "30 days": 30}
MEASURE_ORDER: list[str] = ["temperature", "humidity", "light_raw"]
LABELS: dict[str, str] = {"temperature": "Temperature", "humidity": "Humidity", "light_raw": "Light"}
LIGHT_UNIT: str = "lux"


def age_text(reading_utc: str, now: datetime) -> str:
    """
    Describe how long ago a reading was taken.

    Args:
        reading_utc (str): ``YYYY-MM-DD HH:MM:SS`` UTC.
        now (datetime): Current time, aware.

    Returns:
        str: e.g. ``"just now"``, ``"4 min ago"``, ``"3 h ago"``, ``"12 days ago"``.
    """
    minutes = int((now - parse_utc_timestamp(reading_utc)).total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 120:
        return f"{minutes} min ago"
    if minutes < 48 * 60:
        return f"{minutes // 60} h ago"
    return f"{minutes // 1440} days ago"


def is_stale(reading_utc: str, now: datetime) -> bool:
    """
    Tell whether a reading is too old for automation to use.

    Args:
        reading_utc (str): ``YYYY-MM-DD HH:MM:SS`` UTC.
        now (datetime): Current time, aware.

    Returns:
        bool: True if older than ``core.automation.READING_MAX_AGE``.
    """
    return now - parse_utc_timestamp(reading_utc) > READING_MAX_AGE


def display_value(measure: str, value: float, units: str) -> float:
    """
    Convert a stored reading to display units: °F for US temperature, and the
    raw light level to estimated lux (``core/light.py``).

    Args:
        measure (str): Measure name.
        value (float): Stored value (°C for temperature, raw 0-65535 for light).
        units (str): ``"SI"`` or ``"US"``.

    Returns:
        float: Value to show, rounded (1 decimal place; lux by size).
    """
    if measure == "temperature" and units == "US":
        return round(celsius_to_fahrenheit(value), 1)
    if measure == "light_raw":
        return round_lux(raw_to_lux(value))
    return round(float(value), 1)


def display_units(unit_labels: dict[str, str]) -> dict[str, str]:
    """
    Unit labels as shown on the pages (light in lux instead of raw counts).

    Args:
        unit_labels (dict[str, str]): From ``db.unit_labels``.

    Returns:
        dict[str, str]: Measure name to unit label.
    """
    labels = dict(unit_labels or {})
    labels["light_raw"] = LIGHT_UNIT
    return labels


def history_by_measure(history: DataFrame, units: str, zone: str) -> dict[str, DataFrame]:
    """
    Split readings into one time series per measure, in display units and zone.

    Args:
        history (DataFrame): Output of ``db.sensor_history`` (``measure``,
            ``reading_utc``, ``value``).
        units (str): ``"SI"`` or ``"US"``.
        zone (str): IANA zone (or ``"UTC"``) for the time axis.

    Returns:
        dict[str, DataFrame]: Measure name to a frame indexed by local time
        (naive, for charting) with one ``value`` column, in ``MEASURE_ORDER``.
    """
    frame = history.copy()
    frame["time"] = to_datetime(frame["reading_utc"]).dt.tz_localize("UTC").dt.tz_convert(zone).dt.tz_localize(None)
    frame["value"] = [display_value(m, v, units) for m, v in zip(frame["measure"], frame["value"])]
    series = {}
    for measure in MEASURE_ORDER:
        rows = frame[frame["measure"] == measure]
        if not rows.empty:
            series[measure] = rows.set_index("time")[["value"]]
    return series


def local_frame(history: DataFrame, units: str, zone: str) -> DataFrame:
    """
    Readings in display units with a naive local ``time`` column.

    Args:
        history (DataFrame): Output of ``db.sensor_history``.
        units (str): ``"SI"`` or ``"US"``.
        zone (str): IANA zone (or ``"UTC"``).

    Returns:
        DataFrame: ``measure``, ``time`` and ``value``.
    """
    frame = history.copy()
    frame["time"] = to_datetime(frame["reading_utc"]).dt.tz_localize("UTC").dt.tz_convert(zone).dt.tz_localize(None)
    frame["value"] = [display_value(m, v, units) for m, v in zip(frame["measure"], frame["value"])]
    return frame[["measure", "time", "value"]]


def high_low(frame: DataFrame) -> tuple[tuple[float, datetime], tuple[float, datetime]] | None:
    """
    The highest and lowest value in a series, with when they happened.

    Args:
        frame (DataFrame): Indexed by time, with a ``value`` column.

    Returns:
        tuple | None: ``((high, time), (low, time))``, or None if empty.
    """
    values = frame["value"].dropna()
    if values.empty:
        return None
    return (float(values.max()), values.idxmax()), (float(values.min()), values.idxmin())


def readings_table(history: DataFrame, units: str, zone: str, unit_labels: dict[str, str],
                   time_format: str = "12-hour") -> DataFrame:
    """
    One row per time, one column per measure, newest first.

    Args:
        history (DataFrame): Output of ``db.sensor_history``.
        units (str): ``"SI"`` or ``"US"``.
        zone (str): IANA zone (or ``"UTC"``).
        unit_labels (dict[str, str]): Measure name to unit label (``display_units``).
        time_format (str): ``"12-hour"`` or ``"24-hour"``.

    Returns:
        DataFrame: ``Time`` then e.g. ``Temperature (°F)``, ``Humidity (%)``,
        ``Light (lux)``; a measure missing at a time is left empty.
    """
    frame = local_frame(history, units, zone)
    table = frame.pivot_table(index="time", columns="measure", values="value", aggfunc="mean")
    columns = [m for m in MEASURE_ORDER if m in table.columns]
    table = table[columns].sort_index(ascending=False)
    table.columns = [f"{LABELS[m]} ({unit_labels.get(m, '')})".replace(" ()", "") for m in columns]
    when = "%a %b %d, %I:%M %p" if time_format != "24-hour" else "%a %b %d, %H:%M"
    table.insert(0, "Time", [t.strftime(when) for t in table.index])
    return table.reset_index(drop=True)
