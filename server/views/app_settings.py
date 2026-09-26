"""
App Settings page: per-session display preferences.

Stores the user's choices in ``st.session_state`` (not the database), so they
reset when the browser session ends. The keys are listed in ``ui.py``.
"""
import zoneinfo

import streamlit as st

from ui import page_setup

page_setup("App Settings")

st.title("App Settings")
timezone_list = sorted(zoneinfo.available_timezones())


def load_value(options: list[str], key: str) -> int:
    """
    Return the index of a previously selected option, for a widget's ``index``.

    Args:
        options (list[str]): Options shown in the widget.
        key (str): The previously selected value (not a session-state key).

    Returns:
        int: Position of ``key`` in ``options``, or 0 if it is not present.
    """
    try:
        index_val = options.index(key)
    except ValueError:
        index_val = 0
    return index_val


DATE_FORMATS = ["DD/MM/YYYY", "MM/DD/YYYY", "YYYY/MM/DD", "Day, Month DD, YYYY"]

with st.container(border=True):
    st.session_state["units"] = st.radio(
        label="Display Units",
        options=["SI", "US"],
        horizontal=True,
        index=load_value(["SI", "US"], st.session_state["units"]),
    )
    st.session_state["date_format"] = st.radio(
        "Date Format",
        DATE_FORMATS,
        horizontal=True,
        index=load_value(DATE_FORMATS, st.session_state["date_format"]),
    )
    st.session_state["time_format"] = st.radio(
        "Time Format",
        ["12-hour", "24-hour"],
        horizontal=True,
        index=load_value(["12-hour", "24-hour"], st.session_state["time_format"]),
    )
    timezone = st.radio(
        "Timezone",
        ["UTC", "Local"],
        horizontal=True,
        index=load_value(["UTC", "Local"], st.session_state["timezone"]),
    )
    st.session_state["timezone"] = timezone
    if timezone == "Local":
        st.session_state["timezone_name"] = st.selectbox(
            "Local timezone",
            timezone_list,
            index=load_value(timezone_list, st.session_state["timezone_name"]),
        )
