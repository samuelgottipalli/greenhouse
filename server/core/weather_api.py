"""
Open-Meteo client: fetch current conditions and turn them into a
``weather_readings`` row.

``WEATHER_API`` in ``.env`` is a URL template with ``{LATITUDE}`` and
``{LONGITUDE}`` placeholders. It must not request a ``timezone``, so that the
API returns UTC times.
"""
import logging

from requests import get

from core import settings
from core.timeutil import from_open_meteo

log = logging.getLogger(__name__)

REQUEST_TIMEOUT_S = 10

WeatherResponse = dict[str, str | int | float | dict[str, str | int | float | list[str]]]


def fetch_weather() -> WeatherResponse | None:
    """
    Call the Open-Meteo API for the configured location.

    Returns:
        dict | None: Decoded JSON response, or None if configuration is missing
        or the request fails.
    """
    if not settings.WEATHER_API or not settings.LATITUDE or not settings.LONGITUDE:
        log.error("WEATHER_API, LATITUDE and LONGITUDE must be set in .env")
        return None
    url = settings.WEATHER_API.format(LATITUDE=settings.LATITUDE, LONGITUDE=settings.LONGITUDE)
    try:
        response = get(url, timeout=REQUEST_TIMEOUT_S)
        response.raise_for_status()
    except Exception as err:
        log.error("Weather API request failed: %s", err)
        return None
    return response.json()


def clean_data(data: WeatherResponse | None) -> dict[str, str | int | float] | None:
    """
    Flatten an Open-Meteo response into one ``weather_readings`` row.

    Times are converted to ``YYYY-MM-DD HH:MM:SS`` UTC; only today's
    sunrise/sunset are kept.

    Args:
        data (dict | None): Output of :func:`fetch_weather`.

    Returns:
        dict[str, str | int | float] | None: Column name to value, or None if
        ``data`` is empty.

    Raises:
        KeyError: If the response is missing an expected field.
    """
    if not data:
        log.warning("No weather data to clean")
        return None
    current = data["current"]
    return {
        "measured_utc": from_open_meteo(current["time"]),
        "latitude": float(data["latitude"]),
        "longitude": float(data["longitude"]),
        "elevation_m": data["elevation"],
        "temperature_c": current["temperature"],
        "apparent_temperature_c": current["apparent_temperature"],
        "relative_humidity_pct": current["relative_humidity_2m"],
        "precipitation_mm": current["precipitation"],
        "rain_mm": current["rain"],
        "showers_mm": current["showers"],
        "snowfall_cm": current["snowfall"],
        "weather_code": int(current["weather_code"]),
        "wind_speed_kmh": current["wind_speed_10m"],
        "wind_direction_deg": current["wind_direction_10m"],
        "sunrise_utc": from_open_meteo(data["daily"]["sunrise"][0]),
        "sunset_utc": from_open_meteo(data["daily"]["sunset"][0]),
    }
