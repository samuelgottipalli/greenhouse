import streamlit as st

st.set_page_config(
    page_title="Greenhouse Control Center: App Settings",
    page_icon="🌦️",
    layout="centered",
)

st.title("App Settings")

with st.container(border=True):
    units = st.radio("Display Units", ["SI", "US"], horizontal=True)
    st.session_state["units"] = units
    # theme = st.radio("Display Theme", ["Light", "Dark", "System"], horizontal=True)
    # st.session_state["theme"] = theme
    date_format = st.radio("Date Format", ["DD/MM/YYYY", "MM/DD/YYYY", "YYYY/MM/DD", "Day, Month DD, YYYY"], horizontal=True)
    st.session_state["date_format"] = date_format
    time_format = st.radio("Time Format", ["12-hour", "24-hour"], horizontal=True)
    st.session_state["time_format"] = time_format
