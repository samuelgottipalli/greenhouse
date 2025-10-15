import streamlit as st
import zoneinfo

st.set_page_config(
    page_title="App Settings",
    page_icon=r"images\favicon.png",
    layout="centered",
)
st.logo(r"images\favicon.png", icon_image=r"images\favicon.png", size="large")

st.title("App Settings")
if "units" not in st.session_state:
    st.session_state["units"] = "US"
if "date_format" not in st.session_state:
    st.session_state["date_format"] = "MM/DD/YYYY"
if "time_format" not in st.session_state:
    st.session_state["time_format"] = "12-hour"
if "timezone" not in st.session_state:
    st.session_state["timezone"] = "UTC"
if "timezone_offset" not in st.session_state:
    st.session_state["timezone_offset"] = "America/Los_Angeles"
timezone_list = sorted(list(zoneinfo.available_timezones()))

def load_value(options: list[str], key: str) -> int:
    """
    This function returns the index value of the option previously selected.

    Args:
        options (list[str]): _description_
        key (str): _description_

    Returns:
        int: _description_
    """
    try:
        index_val = options.index(key)
    except ValueError:
        index_val = 0
    return index_val


with st.container(border=True):
    units = st.radio(
        label="Display Units",
        options=["SI", "US"],
        horizontal=True,
        index=load_value(["SI", "US"], st.session_state["units"]),
    )
    st.session_state["units"] = units
    date_format = st.radio(
        "Date Format",
        ["DD/MM/YYYY", "MM/DD/YYYY", "YYYY/MM/DD", "Day, Month DD, YYYY"],
        horizontal=True,
        index=load_value(
            ["DD/MM/YYYY", "MM/DD/YYYY", "YYYY/MM/DD", "Day, Month DD, YYYY"],
            st.session_state["date_format"],
        ),
    )
    st.session_state["date_format"] = date_format
    time_format = st.radio(
        "Time Format",
        ["12-hour", "24-hour"],
        horizontal=True,
        index=load_value(["12-hour", "24-hour"], st.session_state["time_format"]),
    )
    st.session_state["time_format"] = time_format
    timezone = st.radio(
        "Timezone",
        ["UTC", "Local"],
        horizontal=True,
        index=load_value(["UTC", "Local"], st.session_state["timezone"]),
    )
    st.session_state["timezone"] = timezone
    if timezone == "Local":
        
        timezone_offset = st.selectbox(
            "Timezone Offset",
            timezone_list,
            index=load_value(timezone_list, st.session_state["timezone_offset"]),
        )
        st.session_state["timezone_offset"] = timezone_offset
    else:
        timezone_offset = "UTC"
        st.session_state["timezone_offset"] = timezone_offset
