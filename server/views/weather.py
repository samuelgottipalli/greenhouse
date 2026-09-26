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
from core.weather_codes import weather_code_descr, wind_direction_descr
from ui import display_zone, page_setup

page_setup("Weather Data", layout="wide")
st.title(body="Weather Data")

TIME_COLUMNS = ["measured_utc", "sunrise_utc", "sunset_utc"]


def metric_with_delta(column, label: str, data: DataFrame, field: str, unit: str) -> None:
    """
    Show the latest value of a field with its change since the previous reading.

    Args:
        column (DeltaGenerator): Streamlit column to draw in.
        label (str): Card title.
        data (DataFrame): Today's readings, oldest first.
        field (str): Column to show.
        unit (str): Unit label appended to the value and delta.
    """
    latest, previous = data.iloc[-1][field], data.iloc[-2][field]  # S-04: needs 2 rows
    column.metric(
        label=label,
        value=f"{latest} {unit}",
        delta=f"{round(latest - previous, 2)} {unit}",
        delta_color="off",
        border=True,
        chart_data=data[[field]],
    )


@st.fragment(run_every=timedelta(minutes=15))
def get_weather_data(weathertoast: DeltaGenerator) -> None:
    """
    Load today's weather readings and render the metric cards.

    Runs as a fragment that re-executes every 15 minutes. Reads the most
    recent 216 rows (about 2 days at 15-minute intervals), converts times from
    UTC to the chosen zone, keeps today's rows and converts units.

    Args:
        weathertoast (DeltaGenerator): Toast used to report progress.

    Raises:
        ValueError: If loading or rendering fails, including when there are
            fewer than two readings for today.
    """
    zone = display_zone()
    current_date = dtt.now(tz=zoneinfo.ZoneInfo(zone)).date()
    units = db.unit_labels(st.session_state["units"])

    try:
        data = db.recent_weather(limit=216)
        weathertoast.toast("Weather data fetched from DB", icon=":material/thumb_up:")
        if data is None:
            return
        for column in TIME_COLUMNS:
            data[column] = to_datetime(data[column]).dt.tz_localize("UTC").dt.tz_convert(zone)
        data = data[data["measured_utc"].dt.date == current_date].sort_values(by="measured_utc")

        # S-07: apparent temperature and the US rain/snow factors are wrong.
        if st.session_state["units"] == "SI":
            data["rain_mm"] = round(data["rain_mm"] / 10, 2)
            data["showers_mm"] = round(data["showers_mm"] / 10, 2)
            data["precipitation_mm"] = round(data["precipitation_mm"] / 10, 2)
        else:
            data["temperature_c"] = round((data["temperature_c"] * 9 / 5) + 32, 2)
            data["apparent_temperature_c"] = round((data["temperature_c"] * 9 / 5) + 32, 2)
            data["rain_mm"] = round(data["rain_mm"] / 10 / 2.94, 2)
            data["showers_mm"] = round(data["showers_mm"] / 10 / 2.94, 2)
            data["precipitation_mm"] = round(data["precipitation_mm"] / 10 / 2.94, 2)
            data["snowfall_cm"] = round(data["snowfall_cm"] / 2.94, 2)
            data["wind_speed_kmh"] = round(data["wind_speed_kmh"] / 1.609, 2)

        time_format = "%I:%M %p" if st.session_state["time_format"] == "12-hour" else "%H:%M"
        for column in TIME_COLUMNS:
            data[column] = data[column].dt.strftime(time_format)

        weathertoast.toast(body="Loading charts...", icon=":material/hourglass:")
        with st.container(border=True, horizontal=True):
            left, middle, right = st.columns(3)
            latest = data.iloc[-1]  # S-04: fails when there are no readings today
            left.metric(label="Sunrise \U0001f305", value=str(latest["sunrise_utc"]), border=True)
            middle.metric(label="Sunset \U0001f307", value=str(latest["sunset_utc"]), border=True)
            metric_with_delta(left, "Temperature", data, "temperature_c", units["temperature"])
            metric_with_delta(middle, "Humidity", data, "relative_humidity_pct", units["humidity"])
            weathercode = latest["weather_code"]
            if weathercode in weather_code_descr:
                right.metric(label="Weather", value=weather_code_descr[weathercode], border=True)
            else:
                st.metric(label="Weather", value="Unknown", border=True)
            metric_with_delta(right, "Precipitation", data, "precipitation_mm", units["distance_short"])
            metric_with_delta(left, "Wind Speed", data, "wind_speed_kmh", units["speed"])
            direction = latest["wind_direction_deg"]
            right.metric(
                label="Wind Direction",
                # S-05: 348.75-360 degrees gives key 16, which does not exist.
                value=f"{direction} {units['direction']} - "
                + wind_direction_descr[round(direction / 22.5, 0)].get("short"),
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
