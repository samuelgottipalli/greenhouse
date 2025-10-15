import streamlit as st

from os import getenv
from dotenv import load_dotenv

conf = load_dotenv(".env")

st.set_page_config(
    page_title="Greenhouse Weather",
    page_icon=r"images\favicon.png",
    layout="wide",
)
st.logo(r"images\favicon.png", icon_image=r"images\favicon.png", size="large")

st.title("Greenhouse Weather Data")
