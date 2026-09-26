"""
Static lookup tables for displaying weather data.

* ``weather_code_descr``: WMO weather interpretation code (as returned by
  Open-Meteo) mapped to a label with an emoji.
* ``wind_direction_descr``: 16-point compass index (``degrees / 22.5``,
  0 = north) mapped to short and long direction names.
"""
# Weather Code Description
weather_code_descr: dict[int, str] = {
    0: "Clear sky ☀️",
    1: "Mainly clear 🌤️",
    2: "Partly cloudy 🌤️",
    3: "Overcast ☁️",
    45: "Fog 🌫️",
    48: "Depositing rime fog 🌫️",
    51: "Light drizzle ☔",
    53: "Moderate drizzle ☔",
    55: "Dense drizzle 🌧️",
    56: "Light freezing drizzle 🌨️",
    57: "Dense freezing drizzle 🌨️",
    61: "Slight rain ☔",
    63: "Moderate rain ☔",
    65: "Heavy rain 🌧️",
    66: "Light freezing rain 🌨️",
    67: "Heavy freezing rain 🌨️",
    71: "Slight snow fall ❄️",
    73: "Moderate snow fall ❄️",
    75: "Heavy snow fall 🌨️",
    77: "Snow grains 🌨️",
    80: "Slight rain showers ☔",
    81: "Moderate rain showers ☔",
    82: "Violent rain showers 🌧️",
    85: "Slight snow showers ❄️",
    86: "Heavy snow showers 🌨️",
    95: "Slight or moderate thunderstorm ⛈️",
    96: "Thunderstorm with slight hail ⛈️⚪",
    99: "Thunderstorm with heavy hail ⛈️⚪",
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