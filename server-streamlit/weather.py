import time
from turtle import up
from pandas import DataFrame
import streamlit as st
from config import weather_code_descr
from datetime import timedelta, datetime as dtt


st.set_page_config(
    # Title and icon for the browser's tab bar:
    page_title="Greenhouse Control Center",
    page_icon="🌦️",
    # Make the content take up the width of the page:
    layout="wide",
)

st.title("Weather Data")
if not "units" in st.session_state:
    st.session_state["units"] = "SI"
if st.session_state["units"] == "US":
    unit = "F"
else:
    unit = "C"


@st.fragment(run_every=timedelta(minutes=15))
def get_weather_data():
    """
    Fetch weather data from the database.
    """
    conn = st.connection("greenhouse", type="sql")
    try:
        data: DataFrame = conn.query(
            sql="""select
                        *
                    from
                        weather_data
                    where
                        DATE(MEASURE_DATE) = CURRENT_DATE
                    order by
                        MEASURE_DATE""",
        )
        weathertoast.toast("Weather data fetched from DB", icon=":material/thumb_up:")
        return data
    except Exception as e:
        weathertoast.toast(f"Unable to fetch weather data from DB. Possibly due to a database error. Error: {e}", icon=":material/error:")
        return None

@st.fragment(run_every=timedelta(minutes=1))
def update_datetime():
    """
    Update the time on the page.
    """

    if "date_format" not in st.session_state:
        st.session_state["date_format"] = "MM/DD/YYYY"
    if st.session_state["date_format"] == "DD/MM/YYYY":
        display_date = dtt.now().strftime("%d/%m/%Y")
    elif st.session_state["date_format"] == "MM/DD/YYYY":
        display_date = dtt.now().strftime("%m/%d/%Y")
    elif st.session_state["date_format"] == "YYYY/MM/DD":
        display_date = dtt.now().strftime("%Y/%m/%d")
    else:
        display_date = dtt.now().strftime("%A, %d %B %Y")

    if "time_format" not in st.session_state:
        st.session_state["time_format"] = "12h"
    if st.session_state["time_format"] == "12h":
        display_time = dtt.now().strftime("%I:%M %p")
    else:
        display_time = dtt.now().strftime("%H:%M")
    with st.container(border=True, horizontal=True):
        st.metric(label="Date", value=display_date)
        st.metric(label="Time", value=display_time)

update_datetime()
# Create a text element and let the reader know the data is loading.
weathertoast = st.toast("Fetching weather data...")
data = get_weather_data()
# Notify the reader that the data was successfully loaded.
# data_load_state.text("Done! (using st.cache_data)")
if data is not None:
    metrics_container = st.container(border=True,horizontal=True)
    with metrics_container:
        # if st.session_state["units"] == "US":

        st.metric(label="Temperature", value=data.iloc[-1]["TEMPERATURE"], border=True)
        st.metric(
            label="Humidity", value=data.iloc[-1]["RELATIVE_HUMIDITY"], border=True
        )
        st.metric(
            label="Precipitation", value=data.iloc[-1]["PRECIPITATION"], border=True
        )
        weathercode = data.iloc[-1]["WEATHER_CODE"]
        if weathercode in weather_code_descr:
            st.metric(
                label="Weather",
                value=weather_code_descr[weathercode],
                border=True,
            )
        else:
            st.metric(label="Weather", value="Unknown", border=True)
        st.metric(label="Wind Speed", value=data.iloc[-1]["WIND_SPEED"], border=True)
    if st.checkbox('Show raw data'):
        st.subheader('Raw data')
        st.write(data)

    container = st.container(border=True)
    with container:
        st.subheader('Temperature and Humidity over Time')
        left, right = st.columns(2)

        left.line_chart(data, x='MEASURE_DATE', y='TEMPERATURE')
        right.line_chart(data, x='MEASURE_DATE', y='RELATIVE_HUMIDITY')
