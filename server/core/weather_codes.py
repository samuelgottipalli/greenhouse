"""
Static lookup tables for displaying weather data.

* ``weather_code_descr``: WMO weather interpretation code (as returned by
  Open-Meteo) mapped to a plain label, and :func:`weather_icon` to a
  Material Symbols icon name for it.
* ``wind_direction_descr``: 16-point compass index (``degrees / 22.5``,
  0 = north) mapped to short and long direction names.
"""
# Weather Code Description
weather_code_descr: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow fall",
    73: "Moderate snow fall",
    75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Slight or moderate thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}

wind_direction_descr: dict[int, dict[str, str]] = {
    0: {"short": "N", "long": "North"},
    1: {"short": "NNE", "long": "North-northeast"},
    2: {"short": "NE", "long": "Northeast"},
    3: {"short": "ENE", "long": "East-northeast"},
    4: {"short": "E", "long": "East"},
    5: {"short": "ESE", "long": "East-southeast"},
    6: {"short": "SE", "long": "Southeast"},
    7: {"short": "SSE", "long": "South-southeast"},
    8: {"short": "S", "long": "South"},
    9: {"short": "SSW", "long": "South-southwest"},
    10: {"short": "SW", "long": "Southwest"},
    11: {"short": "WSW", "long": "West-southwest"},
    12: {"short": "W", "long": "West"},
    13: {"short": "WNW", "long": "West-northwest"},
    14: {"short": "NW", "long": "Northwest"},
    15: {"short": "NNW", "long": "North-northwest"},
}

# Material Symbols icon for each group of weather codes (day, night).
_ICONS: list[tuple[tuple[int, ...], str, str]] = [
    ((0,), "sunny", "clear_night"),
    ((1, 2), "partly_cloudy_day", "partly_cloudy_night"),
    ((3,), "cloud", "cloud"),
    ((45, 48), "foggy", "foggy"),
    ((51, 53, 61, 80), "rainy_light", "rainy_light"),
    ((55, 63, 65, 81, 82), "rainy", "rainy"),
    ((56, 57, 66, 67, 77), "weather_mix", "weather_mix"),
    ((71, 73, 75, 85, 86), "weather_snowy", "weather_snowy"),
    ((95,), "thunderstorm", "thunderstorm"),
    ((96, 99), "weather_hail", "weather_hail"),
]


def weather_icon(code: int, night: bool = False) -> str:
    """
    The Material Symbols icon for a WMO weather code, as a Streamlit shortcode.

    Args:
        code (int): WMO weather code.
        night (bool): Use the night version (moon instead of sun) where there is one.

    Returns:
        str: e.g. ``":material/partly_cloudy_day:"``; a cloud for unknown codes.
    """
    for codes, day_icon, night_icon in _ICONS:
        if code in codes:
            return f":material/{night_icon if night else day_icon}:"
    return ":material/cloud:"
