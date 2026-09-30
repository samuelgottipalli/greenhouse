"""
Settings page, in tabs: **Display** (units, formats, colour scheme ...),
**Location** (for the outdoor weather and sunrise/sunset), **Greenhouse
rules** (fan, heater, grow light and watering), **Controllers** (Wi-Fi
setup code and software updates) and **System** (restart the controller,
the services or the server). See ``sections/display.py``,
``sections/location.py``, ``sections/rules.py``, ``sections/controllers.py`` and ``sections/system.py``.

Link to a tab with ``/settings?tab=display``, ``?tab=location``, ``?tab=rules``, ``?tab=controllers`` or ``?tab=system``.
"""
import streamlit as st

from sections import controllers, display, location, rules, system
from ui import open_tabs, page_setup

page_setup("Settings")
st.title("Settings")
display_tab, location_tab, rules_tab, controllers_tab, system_tab = open_tabs(
    {"display": "Display", "location": "Location", "rules": "Greenhouse rules", "controllers": "Controllers",
     "system": "System"})
with display_tab:
    display.render()
with location_tab:
    location.render()
with rules_tab:
    rules.render()
with controllers_tab:
    controllers.render()
with system_tab:
    system.render()
