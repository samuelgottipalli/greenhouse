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

st.title("Greenhouse Weather Data")