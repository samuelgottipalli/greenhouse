"""
Analysis page, in tabs: **Greenhouse** and **Outdoor weather**, each measure
month by month over the last year as box plots, with this month so far next
to the same month last year (``sections/analysis.py``).

Link to a tab with ``/analysis?tab=greenhouse`` or ``?tab=weather``.
"""
import streamlit as st

from core import history
from sections import analysis
from ui import current_device, open_tabs, page_setup

page_setup("Analysis", layout="wide")
st.title("Analysis")
st.markdown(
    "Each month of the last year as a box: the **whiskers** span the middle 95 % of readings "
    "(2.5th to 97.5th percentile), the **box** the middle half, the **line** is the median and the "
    "**diamond** the average. This month so far is orange, the same month last year blue.")
last = history.last_run()
if last["utc"]:
    st.caption(f":material/event_repeat: Monthly summaries made through {last['month']} "
               f"(last run {last['utc']} UTC{'' if last['result'] == 'ok' else ', which failed: see the server log'}). "
               "Readings are kept in full for 6 months; older months live on as these summaries.")
else:
    st.caption(":material/event_repeat: Monthly summaries are made on the 1st of each month. Until the first "
               "run, finished months are worked out from the readings.")
greenhouse_tab, weather_tab = open_tabs({"greenhouse": "Greenhouse", "weather": "Outdoor weather"})
with greenhouse_tab:
    analysis.render("greenhouse", current_device())
with weather_tab:
    analysis.render("weather", history.WEATHER_DEVICE)
