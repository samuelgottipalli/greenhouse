"""
Help for the Greenhouse Control System
"""
import streamlit as st

st.set_page_config(
    page_title="Help",
    page_icon=r"images\favicon.png",
    layout="centered",
)
st.logo(r"images\favicon.png", icon_image=r"images\favicon.png", size="large")


with open("help.md", "r", encoding="utf-8") as f:
    help_text = f.read()

st.markdown(help_text)
