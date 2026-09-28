"""
App Settings page: display preferences (units, formats, time zone, colour
scheme, page width and automatic refresh).

Choices apply to the current session immediately and are saved to the
database, so new sessions start with them. The keys are listed in ``ui.py``.
"""
import zoneinfo

import streamlit as st

from ui import PAGE_WIDTHS, PREFERENCE_DEFAULTS, THEMES, page_setup, save_preferences

page_setup("App Settings")
before = {key: st.session_state[key] for key in PREFERENCE_DEFAULTS}

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

with st.container(border=True):
    st.session_state["theme"] = st.radio(
        "Colour scheme",
        THEMES,
        horizontal=True,
        index=load_value(THEMES, st.session_state["theme"]),
        help="Use system setting follows your phone's or computer's light/dark mode.",
    )
    st.session_state["page_width"] = st.radio(
        "Page width",
        PAGE_WIDTHS,
        horizontal=True,
        index=load_value(PAGE_WIDTHS, st.session_state["page_width"]),
        help="Automatic: report pages use the full width, the others stay narrow and easy to read.",
    )
    refresh = st.toggle(
        "Refresh pages automatically when new data arrives",
        value=st.session_state["auto_refresh"] == "On",
        help="Home, the reports and Remote Control check for new readings every 30 seconds with one "
             "small database query, and reload only when something changed.",
    )
    st.session_state["auto_refresh"] = "On" if refresh else "Off"

if {key: st.session_state[key] for key in PREFERENCE_DEFAULTS} != before:
    if save_preferences():
        st.toast("Preferences saved", icon=":material/check_circle:")
        if st.session_state["page_width"] != before["page_width"] or st.session_state["theme"] != before["theme"]:
            st.rerun()  # apply the new width or colour scheme now
    else:
        st.toast("Preferences could not be saved", icon=":material/error:")
