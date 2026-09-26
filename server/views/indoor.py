"""
"Greenhouse Weather" report page.

Placeholder for indoor sensor readings (temperature, humidity, light) from
the Pico. Only the title is rendered so far (PLAN step 4.1).
"""
import streamlit as st

from ui import page_setup

page_setup("Greenhouse Weather", layout="wide")

st.title("Greenhouse Weather Data")
