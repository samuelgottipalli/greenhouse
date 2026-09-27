"""
Weather Data report page: today's outdoor conditions from ``weather_readings``.

Shows date/time (refreshed every minute) and the latest Open-Meteo reading
(refreshed every 15 minutes): sunrise/sunset, temperature, humidity, weather
description, precipitation, wind speed and direction, with sparkline charts
for the day. Honours the units, time zone and date/time formats chosen on the
App Settings page.
"""
import zoneinfo
from datetime import datetime as dtt
from datetime import timedelta

import streamlit as st
from pandas import DataFrame, to_datetime
from streamlit.delta_generator import DeltaGenerator

from core import db
from core.weather_codes import weather_code_descr
from core.weather_report import to_display_units, wind_label
from ui import display_zone, page_setup

page_setup("Weather Data", layout="wide")
st.title(body="Weather Data")

TIME_COLUMNS = ["measured_utc", "sunrise_utc", "sunset_utc"]


def metric_with_delta(column, label: str, data: DataFrame, field: str, unit: str) -> None:
    """
    Show the latest value of a field, with the change since the previous
    reading and a sparkline when there is more than one reading.

    Args:
        column (DeltaGenerator): Streamlit column to draw in.
        label (str): Card title.
        data (DataFrame): Today's readings, oldest first (at least one row).
        field (str): Column to show.
        unit (str): Unit label appended to the value and delta.
    """
    latest = data.iloc[-1][field]
    delta = None
    if len(data) > 1:
        delta = f"{round(latest - data.iloc[-2][field], 2)} {unit}"
    column.metric(
        label=label,
        value=f"{latest} {unit}",
        delta=delta,
        delta_color="off",
        border=True,
        chart_data=data[[field]] if len(data) > 1 else None,
    )


@st.fragment(run_every=timedelta(minutes=15))
def get_weather_data(weathertoast: DeltaGenerator) -> None:
    """
    Load today's weather readings and render the metric cards.

    Runs as a fragment that re-executes every 15 minutes. Reads the most
    recent 216 rows (about 2 days at 15-minute intervals), converts times from
    UTC to the chosen zone, keeps today's rows and converts units. With no
    readings for today it says so and shows when the last reading was taken.

    Args:
        weathertoast (DeltaGenerator): Toast used to report progress.

    Raises:
        ValueError: If loading or rendering fails unexpectedly.
    """
    zone = display_zone()
    current_date = dtt.now(tz=zoneinfo.ZoneInfo(zone)).date()
    units = db.unit_labels(st.session_state["units"])
    time_format = "%I:%M %p" if st.session_state["time_format"] == "12-hour" else "%H:%M"

    try:
        data = db.recent_weather(limit=216)
        weathertoast.toast("Weather data fetched from DB", icon=":material/thumb_up:")
        if data is None:
            st.info("No weather readings yet. Is the weather collector running?")
            return
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

        data = to_display_units(data, st.session_state["units"])
        for column in TIME_COLUMNS:
            data[column] = data[column].dt.strftime(time_format)

        weathertoast.toast(body="Loading charts...", icon=":material/hourglass:")
        with st.container(border=True, horizontal=True):
            left, middle, right = st.columns(3)
            latest = data.iloc[-1]
            left.metric(label="Sunrise 🌅", value=str(latest["sunrise_utc"]), border=True)
            middle.metric(label="Sunset 🌇", value=str(latest["sunset_utc"]), border=True)
            metric_with_delta(left, "Temperature", data, "temperature_c", units["temperature"])
            metric_with_delta(middle, "Humidity", data, "relative_humidity_pct", units["humidity"])
            right.metric(
                label="Weather",
                value=weather_code_descr.get(int(latest["weather_code"]), "Unknown"),
                border=True,
            )
            metric_with_delta(right, "Precipitation", data, "precipitation_mm", units["distance_short"])
            metric_with_delta(left, "Wind Speed", data, "wind_speed_kmh", units["speed"])
            right.metric(
                label="Wind Direction",
                value=wind_label(latest["wind_direction_deg"], units["direction"]),
                border=True,
            )
            right.metric(label="Data last updated at", value=str(latest["measured_utc"]))

        if st.checkbox("Show raw data"):
            st.subheader("Raw data")
            st.write(data)

    except Exception as e:
        weathertoast.toast(
            f"Unable to fetch weather data from DB. Possibly due to a database error. Error: {e}",
            icon=":material/error:",
        )
        raise ValueError(f"Error fetching weather data: {e}") from e


@st.fragment(run_every=timedelta(minutes=1))
def update_datetime() -> None:
    """
    Render the current date and time in the user's zone and formats.

    Runs as a fragment that re-executes every minute.
    """
    current_datetime = dtt.now(tz=zoneinfo.ZoneInfo(display_zone()))
    date_formats = {
        "DD/MM/YYYY": "%d/%m/%Y",
        "MM/DD/YYYY": "%m/%d/%Y",
        "YYYY/MM/DD": "%Y/%m/%d",
    }
    display_date = current_datetime.strftime(
        date_formats.get(st.session_state["date_format"], "%A, %d %B %Y")
    )
    time_format = "%I:%M %p" if st.session_state["time_format"] == "12-hour" else "%H:%M"
    with st.container(border=True, horizontal=True):
        st.metric(label="Date", value=display_date)
        st.metric(label="Time", value=current_datetime.strftime(time_format))


update_datetime()
weathertoast: DeltaGenerator = st.toast(body="Fetching weather data...", icon=":material/hourglass:")
get_weather_data(weathertoast)
