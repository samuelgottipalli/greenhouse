"""Tests for server/core/weather_report.py (S-05, S-07)."""
import pytest
from pandas import DataFrame

from core.weather_report import to_display_units, wind_label

ROW = {
    "temperature_c": 20.0, "apparent_temperature_c": 18.0, "precipitation_mm": 25.4,
    "rain_mm": 12.7, "showers_mm": 0.0, "snowfall_cm": 2.54, "wind_speed_kmh": 16.09344,
    "relative_humidity_pct": 40.0,
}


def test_si_units():
    out = to_display_units(DataFrame([ROW]), "SI").iloc[0]
    assert out["temperature_c"] == 20.0
    assert out["precipitation_mm"] == 2.54  # shown in cm
    assert out["snowfall_cm"] == 2.54
    assert out["wind_speed_kmh"] == 16.09344


def test_us_units():
    out = to_display_units(DataFrame([ROW]), "US").iloc[0]
    assert out["temperature_c"] == 68.0
    assert out["apparent_temperature_c"] == 64.4  # was computed from the converted temperature
    assert out["precipitation_mm"] == 1.0  # 25.4 mm = 1 in (was /29.4)
    assert out["rain_mm"] == 0.5
    assert out["snowfall_cm"] == 1.0  # 2.54 cm = 1 in (was /2.94)
    assert out["wind_speed_kmh"] == 10.0
    assert out["relative_humidity_pct"] == 40.0


def test_input_frame_not_modified():
    frame = DataFrame([ROW])
    to_display_units(frame, "US")
    assert frame.iloc[0]["temperature_c"] == 20.0


@pytest.mark.parametrize("degrees, text", [(0, "0 ° - N"), (350, "350 ° - N"), (338.0, "338.0 ° - NNW"), (90, "90 ° - E")])
def test_wind_label(degrees, text):
    assert wind_label(degrees, "°") == text


def test_rain_rate_from_a_15_minute_sum():
    from core.weather_report import rain_rate

    assert rain_rate(0.5, "SI") == 2.0  # 0.5 mm in 15 min = 2 mm/h
    assert rain_rate(6.35, "US") == 1.0  # 25.4 mm/h = 1 in/h
    assert rain_rate(0.0, "SI") == 0.0


def test_rain_total_and_units():
    from pandas import Series

    from core.weather_report import rain_total, rain_units

    assert rain_total(Series([0.2, 0.3, None, 0.5]), "SI") == 1.0
    assert rain_total(Series([12.7, 12.7]), "US") == 1.0
    assert rain_units("SI") == ("mm/h", "mm") and rain_units("US") == ("in/h", "in")


@pytest.mark.parametrize("code, night, icon", [
    (0, False, ":material/sunny:"), (0, True, ":material/clear_night:"),
    (2, True, ":material/partly_cloudy_night:"), (63, False, ":material/rainy:"),
    (73, False, ":material/weather_snowy:"), (99, False, ":material/weather_hail:"),
    (12345, False, ":material/cloud:"),
])
def test_weather_icons(code, night, icon):
    from core.weather_codes import weather_icon

    assert weather_icon(code, night) == icon


def test_every_weather_code_has_a_plain_label_and_a_real_icon():
    import re

    from streamlit.material_icon_names import ALL_MATERIAL_ICONS

    from core.weather_codes import weather_code_descr, weather_icon

    for code, label in weather_code_descr.items():
        assert re.fullmatch(r"[A-Za-z ]+", label), label  # no emoji
        for night in (False, True):
            name = weather_icon(code, night).split("/")[1].rstrip(":")
            assert name in ALL_MATERIAL_ICONS, name
