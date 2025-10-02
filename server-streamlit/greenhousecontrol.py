import streamlit as st
from os import getenv

import local_utils as lu

lu.get_config()

st.set_page_config(
    # Title and icon for the browser's tab bar:
    page_title="Greenhouse Control Center",
    # page_icon="🌦️",
    # Make the content take up the width of the page:
    layout="centered",
)


def get_relay_state_data():
    """
    Fetch relay state data from the database.
    """
    db_path = getenv("DB_PATH")
    if not db_path:
        st.error("Missing DB_PATH environment variable. Check .env file.")
        return None
    conn_str = getenv("DB_CONNECTION_STRING").format(DB_PATH=db_path)
    if not conn_str:
        st.error("Missing DB_CONNECTION_STRING environment variable. Check .env file.")
        return None
    from pandas import read_sql, DataFrame
    from sqlalchemy import create_engine, Engine, text

    engine: Engine = create_engine(conn_str, echo=False)
    try:
        with engine.connect() as conn:
            data: DataFrame = read_sql(
                text(
                    """select distinct 
                                deviceid, 
                                relayid, 
                                actionid, 
                                reason, 
                                max(actiontime) as actiontime 
                            from 
                                relay_status 
                            group by 
                                deviceid, 
                                relayid, 
                                actionid, 
                                reason 
                            order by 
                                deviceid, relayid;"""
                ),
                conn,
            )
            print(data)
            st.success(body="Relay state data fetched from DB")
            return data
    except Exception as e:
        st.error(
            f"Unable to fetch relay state data from DB. Possibly due to a database error. Error: {e}"
        )
        return None


st.title("Greenhouse Remote Control")
st.header("Control the greenhouse devices remotely.")
with st.expander("ℹ️ About this app", expanded=False):
    st.write("Devices are controlled via MQTT.")
    st.write("Device status is updated every 15 minutes based on the latest weather data.")
    st.write("Use the toggles below to turn the devices on or off manually.")

st.table(get_relay_state_data())

with st.container(border=True):
    with st.columns(2)[0]:
        st.subheader("Device Controls")
    with st.columns(2)[0]:
        st.write("Fan Status:")
    with st.columns(2)[1]:
        st.toggle("Turn Fan On/Off", key="fan_status", help="Toggle to turn the fan on or off", label_visibility="hidden")
    with st.columns(2)[0]:
        st.write("Heater Status:")
    with st.columns(2)[1]:
        st.toggle("Turn Heater On/Off", key="heater_status", help="Toggle to turn the heater on or off", label_visibility="hidden")
    with st.columns(2)[0]:
        st.write("Light Status:")
    with st.columns(2)[1]:
        st.toggle("Turn Light On/Off", key="light_status", help="Toggle to turn the light on or off", label_visibility="hidden")
    with st.columns(2)[0]:
        st.write("Water Status:")
    with st.columns(2)[1]:
        st.toggle("Turn Water On/Off", key="water_status", help="Toggle to turn the water on or off", label_visibility="hidden")