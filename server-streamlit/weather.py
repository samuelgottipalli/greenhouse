import streamlit as st

from os import getenv
from dotenv import load_dotenv

conf = load_dotenv(".env")

st.set_page_config(
    # Title and icon for the browser's tab bar:
    page_title="Greenhouse Control Center",
    # page_icon="🌦️",
    # Make the content take up the width of the page:
    layout="wide",
)

st.title("Weather Data")
# st.write("This app fetches weather data from an external API, cleans it, and loads it into a database.")

@st.cache_data
def get_weather_data():
    db_path = getenv("DB_PATH")
    if not db_path:
        st.error("Missing DB_PATH environment variable. Check .env file.")
        return None
    conn_str = getenv("DB_CONNECTION_STRING").format(DB_PATH=db_path)
    if not conn_str:
        st.error("Missing DB_CONNECTION_STRING environment variable. Check .env file.")
        return None
    from pandas import read_sql_table
    from sqlalchemy import create_engine
    engine = create_engine(conn_str, echo=False)
    try:
        with engine.connect() as conn:
            data = read_sql_table("weather_data", conn)
            st.success("Weather data fetched from DB")
            return data
    except Exception as e:
        st.error(f"Unable to fetch weather data from DB. Possibly due to a database error. Error: {e}")
        return None
        
# Create a text element and let the reader know the data is loading.
with st.spinner('Loading data...'):
    data = get_weather_data()
# Notify the reader that the data was successfully loaded.
# data_load_state.text("Done! (using st.cache_data)")

if st.checkbox('Show raw data'):
    st.subheader('Raw data')
    st.write(data)

container = st.container(border=True,horizontal=True, width="stretch")
with container:
    st.subheader('Temperature and Humidity over Time')
    st.line_chart(data, x='MEASURE_DATE', y='TEMPERATURE')
    st.line_chart(data, x='MEASURE_DATE', y='RELATIVE_HUMIDITY')