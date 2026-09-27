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
