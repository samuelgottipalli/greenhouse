"""
Analysis page. **Compare** picks the view, shown in tabs (**Greenhouse** and
**Outdoor weather**):

* **Today vs yesterday**, **This week vs last week**, **This month vs last
  month**: each measure's current period so far over the whole previous one,
  with a like-for-like sentence (``core/comparisons.py``).
* **Last 12 months**: each month as a box plot, with this month so far next
  to the same month last year (``sections/analysis.py``).

Link to a tab with ``/analysis?tab=greenhouse`` or ``?tab=weather``.
"""
import streamlit as st

from core import history, places
from sections import analysis
from ui import current_device, open_tabs, page_setup

VIEWS = {"Today vs yesterday": "day", "This week vs last week": "week", "This month vs last month": "month",
         "Last 12 months": "year"}
EXPLAIN = {
    "day": "Hourly averages: today so far in orange over all of yesterday in blue. The sentence compares "
           "today with yesterday up to the same time.",
    "week": "Hourly averages from Monday: this week so far in orange over all of last week in blue. The "
            "sentence compares this week with last week up to the same point.",
    "month": "Daily averages by date: this month's complete days in orange over all of last month in blue. "
             "The sentence compares this month (including today so far) with last month up to the same date.",
}

page_setup("Analysis", layout="wide")
st.title("Analysis")
choice = st.segmented_control("Compare", list(VIEWS), default="Last 12 months", key="analysis_view") \
    or "Last 12 months"
kind = VIEWS[choice]
if kind == "year":
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
else:
    st.markdown(EXPLAIN[kind])

greenhouse_tab, weather_tab = open_tabs({"greenhouse": "Greenhouse", "weather": "Outdoor weather"})
with greenhouse_tab:
    if kind == "year":
        analysis.render("greenhouse", current_device())
    else:
        analysis.render_comparison(kind, "greenhouse", current_device())
with weather_tab:
    if kind == "year":
        analysis.render("weather", history.WEATHER_DEVICE)
    else:
        analysis.render_comparison(kind, "weather", history.WEATHER_DEVICE, places.current())
