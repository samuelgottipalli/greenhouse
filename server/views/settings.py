"""
Settings page, in tabs: **Display** (units, formats, colour scheme ...),
**Greenhouse rules** (fan, heater, grow light and watering) and
**Controllers** (Wi-Fi setup code and software updates). See
``sections/display.py``, ``sections/rules.py`` and ``sections/controllers.py``.

Link to a tab with ``/settings?tab=display``, ``?tab=rules`` or ``?tab=controllers``.
"""
import streamlit as st

from sections import controllers, display, rules
from ui import open_tabs, page_setup

page_setup("Settings")
st.title("Settings")
display_tab, rules_tab, controllers_tab = open_tabs(
    {"display": "Display", "rules": "Greenhouse rules", "controllers": "Controllers"})
with display_tab:
    display.render()
with rules_tab:
    rules.render()
with controllers_tab:
    controllers.render()
