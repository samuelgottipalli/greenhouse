from pandas import DataFrame, to_datetime
import streamlit as st
from streamlit.connections.sql_connection import SQLConnection
from streamlit.delta_generator import DeltaGenerator
from config import weather_code_descr
from datetime import timedelta, datetime as dtt, timezone
import zoneinfo
import local_utils as lu

st.set_page_config(
    page_title="Weather Data",
    page_icon=r"images\favicon.png",
    layout="wide",
)
st.logo(image=r"images\favicon.png", icon_image=r"images\favicon.png", size="large")
st.title(body="Weather Data")


@st.fragment(run_every=timedelta(minutes=15))
def get_weather_data(weathertoast: DeltaGenerator):
    """
    Fetch weather data from the database.
    """
    if "timezone" not in st.session_state:
        st.session_state["timezone"] = "Local"

    if st.session_state["timezone"] == "Local":
        if "timezone_offset" not in st.session_state:
            st.session_state["timezone_offset"] = "America/Los_Angeles"

    if st.session_state["timezone"] == "UTC":
        current_datetime: dtt = dtt.now(tz=timezone.utc)
    else:
        current_datetime = dtt.now(
            tz=zoneinfo.ZoneInfo(key=st.session_state["timezone_offset"])
        )
    current_date = current_datetime.date()

    if "units" not in st.session_state:
        st.session_state["units"] = "US"
    units: None | DataFrame = lu.get_units(units=st.session_state["units"])

    conn = st.connection("greenhouse", type="sql")
    try:
        data: DataFrame = conn.query(
            sql="""select
                        *
                    from
                        weather_data
                    order by
                        MEASURE_DATE DESC
                    LIMIT 216;""",
        )
        weathertoast.toast("Weather data fetched from DB", icon=":material/thumb_up:")
        if isinstance(data, DataFrame) and len(data) > 0:

            data["MEASURE_DATE"] = to_datetime(data["MEASURE_DATE"])
            data["SUNRISE_TIME"] = to_datetime(data["SUNRISE_TIME"])
            data["SUNSET_TIME"] = to_datetime(data["SUNSET_TIME"])
            if st.session_state["timezone"] == "Local":
                data["MEASURE_DATE"] = data["MEASURE_DATE"].dt.tz_localize("UTC")
                data["MEASURE_DATE"] = data["MEASURE_DATE"].dt.tz_convert(
                    st.session_state["timezone_offset"]
                )
                data["SUNRISE_TIME"] = data["SUNRISE_TIME"].dt.tz_localize("UTC")
                data["SUNRISE_TIME"] = data["SUNRISE_TIME"].dt.tz_convert(
                    st.session_state["timezone_offset"]
                )
                data["SUNSET_TIME"] = data["SUNSET_TIME"].dt.tz_localize("UTC")
                data["SUNSET_TIME"] = data["SUNSET_TIME"].dt.tz_convert(
                    st.session_state["timezone_offset"]
                )
            data = data[data["MEASURE_DATE"].dt.date == current_date]
            data = data.sort_values(by="MEASURE_DATE")

            if st.session_state["units"] == "SI":
                unit_col = "siunit"
                data["RAIN"] = round(data["RAIN"] / 10, 2)
                data["SHOWERS"] = round(data["SHOWERS"] / 10, 2)
                data["PRECIPITATION"] = round(data["PRECIPITATION"] / 10, 2)
            else:
                unit_col = "englishunit"
                data["TEMPERATURE"] = round((data["TEMPERATURE"] * 9 / 5) + 32, 2)
                data["APPARENT_TEMPERATURE"] = round((data["TEMPERATURE"] * 9 / 5) + 32, 2)
                data["RAIN"] = round(data["RAIN"] / 10 / 2.94, 2)
                data["SHOWERS"] = round(data["SHOWERS"] / 10 / 2.94, 2)
                data["PRECIPITATION"] = round(data["PRECIPITATION"] / 10 / 2.94, 2)
                data["SNOWFALL"] = round(data["SNOWFALL"] / 2.94,2)
                data["WIND_SPEED"] = round(data["WIND_SPEED"] / 1.609,2)

            if "time_format" not in st.session_state:
                st.session_state["time_format"] = "12-hour"
            if st.session_state["time_format"] == "12-hour":
                data["MEASURE_DATE"] = data["MEASURE_DATE"].dt.strftime("%I:%M %p")
                data["SUNRISE_TIME"] = data["SUNRISE_TIME"].dt.strftime("%I:%M %p")
                data["SUNSET_TIME"] = data["SUNSET_TIME"].dt.strftime("%I:%M %p")
            else:
                data["MEASURE_DATE"] = data["MEASURE_DATE"].dt.strftime("%H:%M")
                data["SUNRISE_TIME"] = data["SUNRISE_TIME"].dt.strftime("%H:%M")
                data["SUNSET_TIME"] = data["SUNSET_TIME"].dt.strftime("%H:%M")
            weathertoast.toast(
                body="Loading charts...", icon=":material/hourglass:"
            )
            metrics_container = st.container(border=True, horizontal=True)
            with metrics_container:
                left, middle, right = st.columns(3)
                left.metric(
                    label="Sunrise 🌅",
                    value=str(data.iloc[-1]["SUNRISE_TIME"]),
                    border=True,
                )
                middle.metric(
                    label="Sunset 🌇", value=str(data.iloc[-1]["SUNSET_TIME"]), border=True
                )

                left.metric(
                    label="Temperature",
                    value=str(data.iloc[-1]["TEMPERATURE"])
                    + " "
                    + str(
                        units.loc[
                            units["measurename"] == "temperature", unit_col
                        ].values[0]
                    ),
                    delta=str(
                        round(
                            data.iloc[-1]["TEMPERATURE"] - data.iloc[-2]["TEMPERATURE"],
                            2,
                        )
                    )
                    + " "
                    + str(
                        units.loc[
                            units["measurename"] == "temperature", unit_col
                        ].values[0]
                    ),
                    delta_color="off",
                    border=True,
                    chart_data=data[["TEMPERATURE"]],
                )
                middle.metric(
                    label="Humidity",
                    value=str(data.iloc[-1]["RELATIVE_HUMIDITY"])
                    + " "
                    + str(
                        units.loc[units["measurename"] == "humidity", unit_col].values[
                            0
                        ]
                    ),
                    delta=str(
                        round(
                            data.iloc[-1]["RELATIVE_HUMIDITY"]
                            - data.iloc[-2]["RELATIVE_HUMIDITY"],
                            2,
                        )
                    )
                    + " "
                    + str(
                        units.loc[units["measurename"] == "humidity", unit_col].values[
                            0
                        ]
                    ),
                    delta_color="off",
                    border=True,
                    chart_data=data[["RELATIVE_HUMIDITY"]],
                )
                weathercode = data.iloc[-1]["WEATHER_CODE"]
                if weathercode in weather_code_descr:
                    right.metric(
                        label="Weather",
                        value=weather_code_descr[weathercode],
                        border=True,
                    )
                else:
                    st.metric(label="Weather", value="Unknown", border=True)
                right.metric(
                    label="Precipitation",
                    value=str(data.iloc[-1]["PRECIPITATION"])
                    + " "
                    + str(
                        units.loc[
                            units["measurename"] == "distance_short", unit_col
                        ].values[0]
                    ),
                    delta=str(
                        round(
                            data.iloc[-1]["PRECIPITATION"]
                            - data.iloc[-2]["PRECIPITATION"],
                            2,
                        )
                    )
                    + " "
                    + str(
                        units.loc[
                            units["measurename"] == "distance_short", unit_col
                        ].values[0]
                    ),
                    delta_color="off",
                    border=True,
                    chart_data=data[["PRECIPITATION"]],
                )

                left.metric(
                    label="Wind Speed",
                    value=str(data.iloc[-1]["WIND_SPEED"])
                    + " "
                    + str(
                        units.loc[units["measurename"] == "speed", unit_col].values[0]
                    ),
                    delta=str(
                        round(
                            data.iloc[-1]["WIND_SPEED"] - data.iloc[-2]["WIND_SPEED"],
                            2,
                        )
                    )
                    + " "
                    + str(
                        units.loc[units["measurename"] == "speed", unit_col].values[0]
                    ),
                    delta_color="off",
                    border=True,
                    chart_data=data[["WIND_SPEED"]],
                )
                right.metric(
                    label="Wind Direction",
                    value=str(data.iloc[-1]["WIND_DIRECTION"]) + " "
                    + str(
                        units.loc[units["measurename"] == "direction", unit_col].values[
                            0
                        ]
                    ),
                    border=True,
                )

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
def update_datetime():
    """
    Update the time on the page.
    """
    if "timezone" not in st.session_state:
        st.session_state["timezone"] = "Local"

    if st.session_state["timezone"] == "Local":
        if "timezone_offset" not in st.session_state:
            st.session_state["timezone_offset"] = "America/Los_Angeles"

    if st.session_state["timezone"] == "UTC":
        current_datetime: dtt = dtt.now(timezone.utc)
    else:
        current_datetime: dtt = dtt.now(
            tz=zoneinfo.ZoneInfo(key=st.session_state["timezone_offset"])
        )

    current_date = current_datetime.date()
    current_time = current_datetime.time()

    if "date_format" not in st.session_state:
        st.session_state["date_format"] = "MM/DD/YYYY"
    if st.session_state["date_format"] == "DD/MM/YYYY":
        display_date: str = current_date.strftime("%d/%m/%Y")
    elif st.session_state["date_format"] == "MM/DD/YYYY":
        display_date = current_date.strftime("%m/%d/%Y")
    elif st.session_state["date_format"] == "YYYY/MM/DD":
        display_date = current_date.strftime("%Y/%m/%d")
    else:
        display_date = current_date.strftime("%A, %d %B %Y")

    if "time_format" not in st.session_state:
        st.session_state["time_format"] = "12-hour"
    if st.session_state["time_format"] == "12-hour":
        display_time: str = current_time.strftime("%I:%M %p")
    else:
        display_time = current_time.strftime("%H:%M")
    with st.container(border=True, horizontal=True):
        st.metric(label="Date", value=display_date)
        st.metric(label="Time", value=display_time)


update_datetime()
weathertoast: DeltaGenerator = st.toast(
    body="Fetching weather data...", icon=":material/hourglass:"
)
get_weather_data(weathertoast)
