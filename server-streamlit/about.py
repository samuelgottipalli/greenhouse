"""
About the Greenhouse Control System
"""
import streamlit as st

st.set_page_config(
    page_title="About",
    page_icon=r"images\favicon.png",
    layout="centered",
)
st.logo(r"images\favicon.png", icon_image=r"images\favicon.png", size="large")

with open("about.md", "r", encoding="utf-8") as f:
    about = f.read()

st.markdown(about)
