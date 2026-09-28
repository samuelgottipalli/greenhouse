"""
Tests for the report-page building blocks: estimated lux (core/light.py and
scripts/calibrate_light.py), gauges (core/gauges.py), time charts
(core/charts.py) and the readings table (core/indoor_report.py).
"""
import math
import re

import pytest
from pandas import DataFrame, Timestamp, date_range

from core import charts, gauges, light
from core.indoor_report import display_units, high_low, readings_table


# --- light -------------------------------------------------------------------------


def test_lux_rises_with_the_raw_reading():
    values = [light.raw_to_lux(raw) for raw in (100, 5000, 20000, 40000, 60000, 65000)]
    assert values == sorted(values) and values[0] < 1 < values[-1]


def test_lux_edges():
    assert light.raw_to_lux(0) == 0.0  # no light, or no sensor
    assert light.raw_to_lux(-5) == 0.0
    assert light.raw_to_lux(65535) == light.LUX_MAX
    assert light.raw_to_lux(70000) == light.LUX_MAX


def test_lux_follows_the_ldr_formula():
    # Half scale: the LDR equals the fixed resistor (10 kΩ); with R10 = 10 kΩ that is exactly 10 lux.
    assert light.raw_to_lux(65535 / 2, fixed_ohms=10_000, r10_ohms=10_000, gamma=0.7) == pytest.approx(10.0)


def test_calibration_makes_the_reading_come_out_right():
    r10 = light.r10_from_reading(22437, 350.0)
    assert light.raw_to_lux(22437, r10_ohms=r10) == pytest.approx(350.0)
    with pytest.raises(ValueError):
        light.r10_from_reading(0, 100)
    with pytest.raises(ValueError):
        light.r10_from_reading(1000, 0)


@pytest.mark.parametrize("lux, text", [(1, "dark"), (50, "dim"), (500, "overcast"), (5000, "daylight"),
                                       (50_000, "full sun"), (1e9, "full sun")])
def test_light_level_names(lux, text):
    assert light.light_level_name(lux) == text


def test_round_lux():
    assert light.round_lux(3.14159) == 3.1
    assert light.round_lux(123.6) == 124.0
    assert light.round_lux(12_345) == 12_340.0


def test_calibrate_script_writes_setting(tmp_path, capsys):
    from scripts import calibrate_light

    env = tmp_path / ".env"
    env.write_text("LATITUDE=1\nLDR_R10_OHMS=1\n")
    assert calibrate_light.main(["22437", "350"], env_file=env) == 0
    lines = env.read_text().splitlines()
    assert lines[0] == "LATITUDE=1" and len([line for line in lines if line.startswith("LDR_R10_OHMS=")]) == 1
    r10 = float(lines[-1].split("=")[1])
    assert light.raw_to_lux(22437, r10_ohms=r10) == pytest.approx(350.0, rel=0.01)
    assert "now 350 lux" in capsys.readouterr().out
    assert calibrate_light.main(["0", "350"], env_file=env) == 1


# --- gauges ------------------------------------------------------------------------


def test_fraction():
    assert gauges.fraction(50, 0, 100) == 0.5
    assert gauges.fraction(-10, 0, 100) == 0.0 and gauges.fraction(500, 0, 100) == 1.0
    assert gauges.fraction(100, 1, 10_000, log=True) == pytest.approx(0.5)
    assert gauges.fraction(0, 1, 10_000, log=True) == 0.0


def test_gauge_svg_shows_value_zone_and_change():
    low, high, zones = gauges.greenhouse_temperature_zones("SI", 18, 32)
    svg = gauges.gauge_svg(25.04, "°C", low, high, zones, change=-1.3, title="Temperature")
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert "25 °C" in svg and "OK" in svg and "▼ -1.3 °C in 1 h" in svg
    assert svg.count("<path") == 3  # heater zone, OK, fan zone
    assert "currentColor" in svg  # text follows the light/dark theme


def test_gauge_needle_points_at_the_value():
    zones = [gauges.Zone(math.inf, gauges.GREEN, "any")]
    left = gauges.gauge_svg(0, "", 0, 100, zones)
    right = gauges.gauge_svg(100, "", 0, 100, zones)
    x_of = lambda svg: float(re.search(r'<line x1="100.0" y1="100.0" x2="([\d.]+)"', svg).group(1))  # noqa: E731
    assert x_of(left) < 50 < 150 < x_of(right)


def test_gauge_without_a_value_or_change():
    low, high, zones = gauges.humidity_zones()
    svg = gauges.gauge_svg(None, "%", low, high, zones)
    assert "--" in svg and "<line" not in svg and " in 1 h" not in svg
    steady = gauges.gauge_svg(40, "%", low, high, zones, change=0.0)
    assert "■ 0 % in 1 h" in steady


def test_gauge_escapes_text():
    svg = gauges.gauge_svg(1, "<b>", 0, 10, [gauges.Zone(math.inf, gauges.RED, "<script>")], title="a&b")
    assert "<script>" not in svg and "&lt;b&gt;" in svg and "a&amp;b" in svg


def test_zone_presets():
    low, high, zones = gauges.outdoor_temperature_zones("US")
    assert (low, high) == (-4.0, 113.0)
    assert [z.name for z in zones] == ["freezing", "cold", "cool", "mild", "warm", "hot"]
    assert gauges.zone_of(50.0, zones).name == "cool"
    _low, high, zones = gauges.wind_zones("US")
    assert high == pytest.approx(49.7, abs=0.1)
    assert gauges.zone_of(10, zones).name == "light" and gauges.zone_of(15, zones).name == "breezy"
    _low, _high, zones = gauges.humidity_zones(fan_on_pct=70)
    assert gauges.zone_of(75, zones).name == "fan zone" and gauges.zone_of(60, zones).name == "OK"
    _low, _high, zones = gauges.greenhouse_temperature_zones("US", 18, 32)
    assert gauges.zone_of(60, zones).name == "heater zone"  # 60 °F < 64.4 °F
    low, high, zones = gauges.light_zones()
    assert (low, high) == (1.0, 100_000.0) and gauges.zone_of(500, zones).name == "overcast"


def test_change_over_an_hour():
    times = date_range("2026-09-27 10:00", periods=13, freq="10min")
    frame = DataFrame({"time": times, "t": [20.0 + i * 0.1 for i in range(13)]})
    assert gauges.change_over(frame, "t") == pytest.approx(0.6)  # 12:00 vs 11:00
    assert gauges.change_over(frame.head(3), "t") is None  # less than an hour of data
    gap = DataFrame({"time": [Timestamp("2026-09-27 06:00"), Timestamp("2026-09-27 12:00")], "t": [1.0, 5.0]})
    assert gauges.change_over(gap, "t") is None  # the older reading is too old to compare


# --- charts -------------------------------------------------------------------------


@pytest.mark.parametrize("days, fmt12, fmt24", [(1, "%-I %p", "%H:%M"), (7, "%a %-d", "%a %-d"),
                                                (30, "%b %-d", "%b %-d")])
def test_axis_formats(days, fmt12, fmt24):
    assert charts.axis_format(days, "12-hour") == fmt12
    assert charts.axis_format(days, "24-hour") == fmt24


def test_time_chart_spec():
    frame = DataFrame({"time": date_range("2026-09-27 00:00", periods=4, freq="h"), "v": [1.0, 2.0, 3.0, 4.0]})
    spec = charts.time_chart(frame, "v", "°F", 1, "12-hour", height=150).to_dict()
    assert spec["encoding"]["x"]["axis"]["format"] == "%-I %p"
    assert spec["encoding"]["x"]["scale"]["type"] == "utc"
    assert spec["encoding"]["y"]["title"] == "°F"
    assert [t["field"] for t in spec["encoding"]["tooltip"]] == ["when", "value"]
    assert spec["height"] == 150


def test_chart_frame_keeps_local_wall_time():
    frame = DataFrame({"time": [Timestamp("2026-09-27 15:05")], "v": [1.0]})
    data = charts.chart_frame(frame, "v", "time", "12-hour")
    assert data["when"].iloc[0] == "Sun Sep 27, 3:05 PM"
    assert str(data["time"].iloc[0]) == "2026-09-27 15:05:00+00:00"  # shown as 3:05 PM on a UTC scale


# --- readings table ------------------------------------------------------------------


HISTORY = DataFrame({
    "measure": ["temperature", "humidity", "light_raw", "temperature", "humidity"],
    "reading_utc": ["2026-09-27 22:00:00"] * 3 + ["2026-09-27 22:05:00"] * 2,
    "value": [20.0, 40.0, 30000.0, 21.0, 41.0],
})


def test_readings_table_is_one_row_per_time():
    units = display_units({"temperature": "°F", "humidity": "% (RH)", "light_raw": "raw"})
    table = readings_table(HISTORY, "US", "America/Los_Angeles", units)
    assert list(table.columns) == ["Time", "Temperature (°F)", "Humidity (% (RH))", "Light (lux)"]
    assert list(table["Time"]) == ["Sun Sep 27, 03:05 PM", "Sun Sep 27, 03:00 PM"]  # newest first, local
    assert table.iloc[1]["Temperature (°F)"] == 68.0
    assert math.isnan(table.iloc[0]["Light (lux)"])  # no light reading at 3:05
    table24 = readings_table(HISTORY, "SI", "UTC", units, "24-hour")
    assert table24["Time"].iloc[0] == "Sun Sep 27, 22:05"


def test_high_low():
    series = DataFrame({"value": [3.0, 9.0, 1.0]}, index=date_range("2026-09-27", periods=3, freq="h"))
    (top, top_at), (bottom, bottom_at) = high_low(series)
    assert (top, str(top_at)) == (9.0, "2026-09-27 01:00:00")
    assert (bottom, str(bottom_at)) == (1.0, "2026-09-27 02:00:00")
    assert high_low(DataFrame({"value": []})) is None
