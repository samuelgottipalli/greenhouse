"""
Reports page: the date and time (shared, above the tabs), then tabs:
**Greenhouse** (inside: gauges, charts, table) and **Outdoor weather**
(today's weather from Open-Meteo). See ``sections/greenhouse.py`` and
``sections/weather.py``; each tab says when its data was last updated.

Link to a tab with ``/reports?tab=greenhouse`` or ``?tab=weather``. The page
reloads itself when new readings arrive (``ui.auto_refresh``).
"""
import streamlit as st

from sections import greenhouse, weather
from ui import auto_refresh, date_and_time, open_tabs, page_setup

page_setup("Reports", layout="wide")
auto_refresh("reports", ("device", "weather"))
st.title("Reports")
date_and_time()
inside, outside = open_tabs({"greenhouse": "Greenhouse", "weather": "Outdoor weather"})
with inside:
    greenhouse.render()
with outside:
    weather.render()
