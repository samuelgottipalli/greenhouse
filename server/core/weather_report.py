"""
Pure helpers behind Reports › Outdoor weather: unit conversion, wind labels
and rain rates.

``weather_readings`` stores SI units (°C, mm, cm, km/h). The page shows
precipitation in cm (SI) or inches (US), matching the ``distance_short``
measure, snowfall in cm or inches, wind in km/h or mph. The precipitation
gauge shows a rain rate (mm/h or in/h) and the day's total (mm or inches),
the usual units for rain.
"""
from pandas import DataFrame, Series, to_datetime

from core.conversions import (
    celsius_to_fahrenheit,
    cm_to_inches,
    degrees_to_compass_index,
    kmph_to_mph,
    mm_to_cm,
    mm_to_inches,
)
from core.weather_codes import wind_direction_descr

RAIN_COLUMNS = ["precipitation_mm", "rain_mm", "showers_mm"]


def to_display_units(data: DataFrame, units: str) -> DataFrame:
    """
    Convert a frame of ``weather_readings`` rows to the display units.

    Column names are kept (they name the stored unit); only values change.

    Args:
        data (DataFrame): Rows from ``db.recent_weather``.
        units (str): ``"SI"`` or ``"US"``.

    Returns:
        DataFrame: A converted copy.
    """
    data = data.copy()
    if units == "SI":
        for column in RAIN_COLUMNS:
            data[column] = data[column].map(mm_to_cm)
        return data
    for column in ("temperature_c", "apparent_temperature_c"):
        data[column] = data[column].map(celsius_to_fahrenheit)
    for column in RAIN_COLUMNS:
        data[column] = data[column].map(mm_to_inches)
    data["snowfall_cm"] = data["snowfall_cm"].map(cm_to_inches)
    data["wind_speed_kmh"] = data["wind_speed_kmh"].map(kmph_to_mph)
    return data


def wind_label(degrees: float, unit: str) -> str:
    """
    Describe a wind direction, e.g. ``"338.0 ° - NNW"``.

    Args:
        degrees (float): Direction the wind comes from, clockwise from north.
        unit (str): Unit label for degrees.

    Returns:
        str: Degrees plus the 16-point compass abbreviation.
    """
    return f"{degrees} {unit} - {wind_direction_descr[degrees_to_compass_index(degrees)]['short']}"


RAIN_INTERVAL_MINUTES = 15  # Open-Meteo's "current" precipitation is the sum of the preceding 15 minutes


def rain_rate(precipitation_mm: float, units: str) -> float:
    """
    Turn a 15-minute precipitation sum into a rate: mm/h (SI) or in/h (US).

    Args:
        precipitation_mm (float): Stored ``precipitation_mm`` (the preceding 15 minutes).
        units (str): ``"SI"`` or ``"US"``.

    Returns:
        float: Rate per hour, in display units.
    """
    per_hour = precipitation_mm * 60 / RAIN_INTERVAL_MINUTES
    return mm_to_inches(per_hour, 3) if units == "US" else round(per_hour, 2)


def rain_total(precipitation_mm: Series, units: str) -> float:
    """
    Add up 15-minute precipitation sums: mm (SI) or inches (US).

    Args:
        precipitation_mm (Series): Stored ``precipitation_mm`` values.
        units (str): ``"SI"`` or ``"US"``.

    Returns:
        float: Total, in display units.
    """
    total = float(precipitation_mm.fillna(0).sum())
    return mm_to_inches(total, 2) if units == "US" else round(total, 1)


def rain_units(units: str) -> tuple[str, str]:
    """Unit labels for a rain rate and a rain total: ``("mm/h", "mm")`` or ``("in/h", "in")``."""
    return ("in/h", "in") if units == "US" else ("mm/h", "mm")


HISTORY_MEASURES = ("temperature_c", "relative_humidity_pct", "wind_speed_kmh")


def history_frames(data: DataFrame, units: str, zone: str, detail: str, rain_step: str) -> tuple[DataFrame, DataFrame]:
    """
    Turn ``db.weather_history`` rows into what the history charts show.

    Args:
        data (DataFrame): ``measured_utc`` and the weather columns (raw or hourly).
        units (str): ``"SI"`` or ``"US"``.
        zone (str): Display zone.
        detail (str): ``"raw"``, ``"hour"`` or ``"day"`` (``Period.detail``): the
            rows as given, or daily averages for ``"day"``.
        rain_step (str): ``"hour"`` or ``"day"``: rain totals per hour or per day.

    Returns:
        tuple[DataFrame, DataFrame]: Measures (naive local ``time`` plus
        ``HISTORY_MEASURES`` in display units) and rain (``time`` and
        ``rain``: mm or inches per step).
    """
    frame = data.copy()
    frame["time"] = to_datetime(frame["measured_utc"]).dt.tz_localize("UTC").dt.tz_convert(zone).dt.tz_localize(None)
    rain = frame[["time", "precipitation_mm"]].copy()
    rain["time"] = rain["time"].dt.floor("h") if rain_step == "hour" else rain["time"].dt.normalize()
    rain = rain.groupby("time", as_index=False)["precipitation_mm"].sum()
    rain["rain"] = rain["precipitation_mm"].map(
        (lambda mm: mm_to_inches(mm, 3)) if units == "US" else (lambda mm: round(mm, 2)))
    measures = frame[["time", *HISTORY_MEASURES]].copy()
    if detail == "day":
        measures["time"] = measures["time"].dt.normalize()
        measures = measures.groupby("time", as_index=False).mean().round(2)
    if units == "US":
        measures["temperature_c"] = measures["temperature_c"].map(celsius_to_fahrenheit)
        measures["wind_speed_kmh"] = measures["wind_speed_kmh"].map(kmph_to_mph)
    return measures, rain[["time", "rain"]]
