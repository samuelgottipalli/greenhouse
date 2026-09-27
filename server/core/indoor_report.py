"""
Pure helpers behind the Home and Greenhouse Weather (indoor) pages: reading
ages, staleness and chart-ready history.
"""
from datetime import datetime

from pandas import DataFrame, to_datetime

from core.automation import READING_MAX_AGE
from core.conversions import celsius_to_fahrenheit
from core.timeutil import parse_utc_timestamp

PERIODS: dict[str, int] = {"24 hours": 1, "7 days": 7, "30 days": 30}
MEASURE_ORDER: list[str] = ["temperature", "humidity", "light_raw"]


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
    Convert a stored reading to display units (only temperature changes).

    Args:
        measure (str): Measure name.
        value (float): Stored value (°C for temperature).
        units (str): ``"SI"`` or ``"US"``.

    Returns:
        float: Value to show, rounded to 1 decimal place.
    """
    if measure == "temperature" and units == "US":
        return round(celsius_to_fahrenheit(value), 1)
    return round(float(value), 1)


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
