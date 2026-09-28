"""
Pure helpers behind Reports › Outdoor weather: unit conversion and wind labels.

``weather_readings`` stores SI units (°C, mm, cm, km/h). The page shows
precipitation in cm (SI) or inches (US), matching the ``distance_short``
measure, snowfall in cm or inches, wind in km/h or mph.
"""
from pandas import DataFrame

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
