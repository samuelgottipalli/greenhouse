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
    theme = st.radio("Display Theme", ["Light", "Dark", "System"], horizontal=True)
    st.session_state["theme"] = theme