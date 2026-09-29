"""
Reports › Outdoor weather tab: today's outdoor conditions from ``weather_readings``.

Shows when the data was last updated, then two even rows of four (the page
reloads itself when a new reading arrives, see ``ui.auto_refresh``):

* Cards for the conditions, sunrise, sunset and hours of daylight, each with
  a Material Symbols icon.
* **Gauges** for temperature, humidity, precipitation (as a rain rate) and
  wind speed, each with the change over the last hour, one short line
  (feels-like, today's range, today's rain, wind direction) and a chart of the day
  underneath (``core/gauges.py``, ``core/charts.py``).

The date and time are shown above the tabs by ``views/reports.py``. Honours
the units, time zone and date/time formats chosen on Settings › Display.
"""
import zoneinfo
from datetime import datetime as dtt

import streamlit as st
from pandas import DataFrame, to_datetime

from core import db, places
from core.charts import time_chart
from core.conversions import degrees_to_compass_index
from core.gauges import (
    change_over,
    format_number,
    gauge_svg,
    humidity_zones,
    outdoor_temperature_zones,
    precipitation_zones,
    wind_zones,
)
from core.weather_codes import weather_code_descr, weather_icon, wind_direction_descr
from core.weather_report import rain_rate, rain_total, rain_units, to_display_units
from ui import display_zone, last_updated, time_pattern


TIME_COLUMNS = ["measured_utc", "sunrise_utc", "sunset_utc"]


def daylight_text(sunrise: dtt, sunset: dtt) -> str:
    """Hours of daylight between sunrise and sunset, e.g. ``"11 h 42 min"``."""
    minutes = max(int((sunset - sunrise).total_seconds() // 60), 0)
    return f"{minutes // 60} h {minutes % 60:02d} min"


def summary_cards(latest, time_format: str) -> None:
    """
    The row of cards above the gauges: conditions, sunrise, sunset, daylight.

    Args:
        latest: The newest reading (times still as local datetimes).
        time_format (str): ``strftime`` pattern for times.
    """
    code = int(latest["weather_code"])
    night = not (latest["sunrise_utc"] <= latest["measured_utc"] < latest["sunset_utc"])
    cards = [
        (f"{weather_icon(code, night)} Conditions", weather_code_descr.get(code, "Unknown")),
        (":material/wb_twilight: Sunrise", latest["sunrise_utc"].strftime(time_format)),
        (":material/nights_stay: Sunset", latest["sunset_utc"].strftime(time_format)),
        (":material/sunny: Daylight", daylight_text(latest["sunrise_utc"], latest["sunset_utc"])),
    ]
    for column, (label, value) in zip(st.columns(len(cards)), cards):
        column.metric(label=label, value=value, border=True)


def gauge_card(column, label: str, data: DataFrame, field: str, unit: str, dial: tuple, color: str,
               note: str, decimals: int = 1) -> None:
    """
    One gauge card: title, gauge with the last hour's change, a line about
    the day, and a chart of the day.

    Args:
        column (DeltaGenerator): Column to draw in.
        label (str): Card title (also the gauge's accessible title).
        data (DataFrame): Today's readings in display units, oldest first.
        field (str): Column to show.
        unit (str): Unit label.
        dial (tuple): ``(low, high, zones)`` from a ``*_zones`` preset.
        color (str): Chart line colour.
        note (str): Caption under the gauge.
        decimals (int): Decimal places for the value.
    """
    low, high, zones = dial
    value = float(data.iloc[-1][field])
    with column.container(border=True):
        st.markdown(f"**{label}**")
        st.markdown(gauge_svg(value, unit, low, high, zones, change=change_over(data, field), decimals=decimals,
                              title=f"{label}: {format_number(value, decimals)} {unit}"), unsafe_allow_html=True)
        st.caption(note)
        if len(data) > 1:
            st.altair_chart(time_chart(data, field, unit, 1, st.session_state["time_format"], color=color,
                                       height=150, decimals=decimals), use_container_width=True)


def render() -> None:
    """
    Draw this section (called by its tabbed page).

    Reads the most recent 216 rows (about 2 days at 15-minute intervals),
    converts times from UTC to the chosen zone, keeps today's rows and
    converts units. With no readings for today it says so and shows when the
    last reading was taken.
    """
    zone = display_zone()
    current_date = dtt.now(tz=zoneinfo.ZoneInfo(zone)).date()
    units = st.session_state["units"]
    labels = db.unit_labels(units)
    time_format = time_pattern(st.session_state["time_format"])

    place = places.current()
    if place is None:
        st.info("Choose the greenhouse's location first: [Settings › Location](/settings?tab=location).",
                icon=":material/location_on:")
        return
    data = db.recent_weather(limit=216)
    if data is not None:
        # Only this location's readings (earlier ones may be for a place chosen before).
        data = data[[places.near(lat, lon, place) for lat, lon in zip(data["latitude"], data["longitude"])]]
    if data is None or data.empty:
        st.info(f"No weather readings for {place['name']} yet. The first one arrives within 15 minutes "
                "(is the weather collector running?).")
        return
    newest_utc = str(data["measured_utc"].max())
    for column in TIME_COLUMNS:
        data[column] = to_datetime(data[column]).dt.tz_localize("UTC").dt.tz_convert(zone)
    last_reading = data["measured_utc"].max()
    data = data[data["measured_utc"].dt.date == current_date].sort_values(by="measured_utc")
    if data.empty:
        st.info(
            "No weather readings yet today. The last one was taken "
            f"{last_reading.strftime('%Y-%m-%d ' + time_format)}. Is the weather collector running?"
        )
        return

    last_updated(newest_utc, f"{place['name']} · from Open-Meteo")
    rate_unit, total_unit = rain_units(units)
    total = rain_total(data["precipitation_mm"], units)
    data["rain_rate"] = data["precipitation_mm"].map(lambda mm: rain_rate(mm, units))
    data = to_display_units(data, units)
    data["time"] = data["measured_utc"].dt.tz_localize(None)  # local wall time, for charts
    latest = data.iloc[-1]

    summary_cards(latest, time_format)

    temp_unit = labels["temperature"]
    compass = wind_direction_descr[degrees_to_compass_index(float(latest["wind_direction_deg"]))]
    columns = st.columns(4)
    gauge_card(columns[0], "Temperature", data, "temperature_c", temp_unit, outdoor_temperature_zones(units),
               "#ef4444", f"Feels like {format_number(latest['apparent_temperature_c'])} {temp_unit}")
    gauge_card(columns[1], "Humidity", data, "relative_humidity_pct", labels["humidity"], humidity_zones(),
               "#3b82f6", f"Today {format_number(data['relative_humidity_pct'].min(), 0)}–"
               f"{format_number(data['relative_humidity_pct'].max(), 0)} %")
    gauge_card(columns[2], "Precipitation", data, "rain_rate", rate_unit, precipitation_zones(units),
               "#06b6d4", f"Today's total {format_number(total, 2)} {total_unit}",
               decimals=2 if units == "US" else 1)
    gauge_card(columns[3], "Wind speed", data, "wind_speed_kmh", labels["speed"], wind_zones(units),
               "#22c55e", f"From the {compass['long'].lower()}")

    if st.checkbox("Show raw data"):
        st.subheader("Raw data")
        st.write(data)
