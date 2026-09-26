"""Tests for server/core/conversions.py."""
import pytest

from core import conversions as cv


@pytest.mark.parametrize(
    "celsius, fahrenheit",
    [(0, 32.0), (100, 212.0), (-40, -40.0), (18.5, 65.3), (32, 89.6)],
)
def test_temperature_round_trip(celsius, fahrenheit):
    assert cv.celsius_to_fahrenheit(celsius) == fahrenheit
    assert cv.fahrenheit_to_celsius(fahrenheit) == pytest.approx(celsius, abs=0.01)


def test_temperature_keeps_precision():
    # The retired Dash helpers returned int(round(...)) and lost this.
    assert cv.fahrenheit_to_celsius(cv.celsius_to_fahrenheit(18.5)) == 18.5


def test_temperature_delta_has_no_offset():
    assert cv.celsius_delta_to_fahrenheit(2) == 3.6
    assert cv.fahrenheit_delta_to_celsius(3.6) == 2.0


def test_speed():
    assert cv.kmph_to_mph(1.609344) == 1.0
    assert cv.mph_to_kmph(10) == 16.09


def test_lengths():
    assert cv.mm_to_cm(25) == 2.5
    assert cv.mm_to_inches(25.4) == 1.0
    assert cv.cm_to_inches(2.54) == 1.0
    assert cv.inches_to_cm(1) == 2.54


def test_ndigits():
    assert cv.celsius_to_fahrenheit(21.123, ndigits=0) == 70.0


@pytest.mark.parametrize(
    "degrees, index",
    [(0, 0), (11.24, 0), (11.26, 1), (90, 4), (180, 8), (270, 12),
     (348.74, 15), (348.76, 0), (359.9, 0), (360, 0), (-22.5, 15)],
)
def test_degrees_to_compass_index(degrees, index):
    assert cv.degrees_to_compass_index(degrees) == index


def test_compass_index_is_valid_key_for_every_degree():
    from core.weather_codes import wind_direction_descr

    for tenth in range(0, 3600):
        assert cv.degrees_to_compass_index(tenth / 10) in wind_direction_descr
