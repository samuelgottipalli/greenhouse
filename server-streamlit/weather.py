from pandas import DataFrame, to_datetime
import streamlit as st
from config import weather_code_descr
from datetime import timedelta, datetime as dtt, timezone
import zoneinfo


st.set_page_config(
    page_title="Weather Data",
    page_icon=r"images\favicon.png",
    layout="wide",
)
st.logo(r"images\favicon.png", icon_image=r"images\favicon.png", size="large")
st.title("Weather Data")


def unit_conversion(units: str):
    conn = st.connection("greenhouse", type="sql")
    try:
        data: DataFrame = conn.query(
            sql="""select
                        *
                    from
                        d_measures
                    """,
        )
    except Exception as e:
        st.toast(
            f"Unable to get units of measurement! Error: {e}", icon=":material/error:"
        )
        return None

    if units == "SI":
        data = data[["measureid", "measurename", "siunit"]]
    else:
        data = data[["measureid", "measurename", "englishunit"]]
    return data


@st.fragment(run_every=timedelta(minutes=15))
def get_weather_data():
    """
    Fetch weather data from the database.
    """
    if "timezone" not in st.session_state:
        st.session_state["timezone"] = "UTC"

    if st.session_state["timezone"] == "Local":
        if "timezone_offset" not in st.session_state:
            st.session_state["timezone_offset"] = "America/Los_Angeles"

    if st.session_state["timezone"] == "UTC":
        current_datetime = dtt.now(timezone.utc)
    else:
        current_datetime = dtt.now(
            zoneinfo.ZoneInfo(st.session_state["timezone_offset"])
        )
    current_date = current_datetime.date()

    if "units" not in st.session_state:
        st.session_state["units"] = "US"
    units = unit_conversion(st.session_state["units"])

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

            print(data)
            if "time_format" not in st.session_state:
                st.session_state["time_format"] = "12-hour"
            if st.session_state["time_format"] == "12-hour":
                data["MEASURE_DATE"] = data["MEASURE_DATE"].dt.strftime("%I:%M %p")
            else:
                data["MEASURE_DATE"] = data["MEASURE_DATE"].dt.strftime("%H:%M")
            metrics_container = st.container(border=True, horizontal=True)
            with metrics_container:
                left, middle, right = st.columns(3)
                left.metric(
                    label="Sunrise", value=str(data.iloc[-1]["SUNRISE_TIME"]), border=True
                )
                left.metric(
                    label="Sunset", value=str(data.iloc[-1]["SUNSET_TIME"]), border=True
                )

                middle.metric(
                    label="Temperature",
                    value=str(data.iloc[-1]["TEMPERATURE"])
                    + str(units.loc[units["measurename"] == "temperature", unit_col].values[0]),
                    border=True,
                )
                middle.metric(
                    label="Humidity",
                    value=str(data.iloc[-1]["RELATIVE_HUMIDITY"])
                    + str(
                        units.loc[units["measurename"] == "humidity", unit_col].values[
                            0
                        ]
                    ),
                    border=True,
                )
                middle.metric(
                    label="Precipitation",
                    value=str(data.iloc[-1]["PRECIPITATION"])
                    + str(
                        units.loc[units["measurename"] == "distance_short", unit_col].values[
                            0
                        ]
                    ),
                    border=True,
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
                    label="Wind Speed",
                    value=str(data.iloc[-1]["WIND_SPEED"])
                    + str(
                        units.loc[units["measurename"] == "speed", unit_col].values[
                            0
                        ]
                    ),
                    border=True,
                )
                right.metric(
                    label="Wind Direction",
                    value=str(data.iloc[-1]["WIND_DIRECTION"])
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

            container = st.container(border=True)
            with container:
                st.subheader("Temperature and Humidity over Time")
                left, right = st.columns(2)

                left.line_chart(data, x="MEASURE_DATE", y="TEMPERATURE")
                right.line_chart(data, x="MEASURE_DATE", y="RELATIVE_HUMIDITY")
    except Exception as e:
        raise ValueError(f"Error fetching weather data: {e}") from e
        # weathertoast.toast(
        #     f"Unable to fetch weather data from DB. Possibly due to a database error. Error: {e}",
        #     icon=":material/error:",
        # )
        # return None


@st.fragment(run_every=timedelta(minutes=1))
def update_datetime():
    """
    Update the time on the page.
    """
    if "timezone" not in st.session_state:
        st.session_state["timezone"] = "UTC"

    if st.session_state["timezone"] == "Local":
        if "timezone_offset" not in st.session_state:
            st.session_state["timezone_offset"] = "America/Los_Angeles"

    if st.session_state["timezone"] == "UTC":
        current_datetime = dtt.now(timezone.utc)
    else:
        current_datetime = dtt.now(
            zoneinfo.ZoneInfo(st.session_state["timezone_offset"])
        )

    current_date = current_datetime.date()
    current_time = current_datetime.time()

    if "date_format" not in st.session_state:
        st.session_state["date_format"] = "MM/DD/YYYY"
    if st.session_state["date_format"] == "DD/MM/YYYY":
        display_date = current_date.strftime("%d/%m/%Y")
    elif st.session_state["date_format"] == "MM/DD/YYYY":
        display_date = current_date.strftime("%m/%d/%Y")
    elif st.session_state["date_format"] == "YYYY/MM/DD":
        display_date = current_date.strftime("%Y/%m/%d")
    else:
        display_date = current_date.strftime("%A, %d %B %Y")

    if "time_format" not in st.session_state:
        st.session_state["time_format"] = "12-hour"
    if st.session_state["time_format"] == "12-hour":
        display_time = current_time.strftime("%I:%M %p")
    else:
        display_time = current_time.strftime("%H:%M")
    with st.container(border=True, horizontal=True):
        st.metric(label="Date", value=display_date)
        st.metric(label="Time", value=display_time)


update_datetime()
# Create a text element and let the reader know the data is loading.
weathertoast = st.toast("Fetching weather data...")
get_weather_data()
# Notify the reader that the data was successfully loaded.
# data_load_state.text("Done! (using st.cache_data)")
