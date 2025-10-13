from pandas import DataFrame
import streamlit as st
from config import weather_code_descr


st.set_page_config(
    # Title and icon for the browser's tab bar:
    page_title="Greenhouse Control Center",
    page_icon="🌦️",
    # Make the content take up the width of the page:
    layout="centered",
)

st.title("Weather Data")

@st.fragment(run_every="15m")
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

# Create a text element and let the reader know the data is loading.
weathertoast = st.toast("Fetching weather data...")
data = get_weather_data()
# Notify the reader that the data was successfully loaded.
# data_load_state.text("Done! (using st.cache_data)")
if data is not None:
    metrics_container = st.container(border=True,horizontal=True)
    with metrics_container:
        st.metric(label="Temperature", value=data.iloc[-1]["TEMPERATURE"])
        st.metric(label="Humidity", value=data.iloc[-1]["RELATIVE_HUMIDITY"])
        st.metric(label="Precipitation", value=data.iloc[-1]["PRECIPITATION"])
        weathercode = data.iloc[-1]["WEATHER_CODE"]
        if weathercode in weather_code_descr:
            st.metric(label="Weather", value=weather_code_descr[weathercode])
        else:
            st.metric(label="Weather", value="Unknown")
        st.metric(label="Wind Speed", value=data.iloc[-1]["WIND_SPEED"])
    if st.checkbox('Show raw data'):
        st.subheader('Raw data')
        st.write(data)

    container = st.container(border=True)
    with container:
        st.subheader('Temperature and Humidity over Time')
        left, right = st.columns(2)

        left.line_chart(data, x='MEASURE_DATE', y='TEMPERATURE')
        right.line_chart(data, x='MEASURE_DATE', y='RELATIVE_HUMIDITY')
