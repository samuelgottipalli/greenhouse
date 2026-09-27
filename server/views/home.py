"""
Home page: system status at a glance.

* Controller: online/offline as last reported on its MQTT status topic.
* Readings: how old the latest greenhouse reading is (fresh or stale).
* Relays: the logged state of each controlled relay and who set it.
"""
from datetime import datetime, timezone

import streamlit as st

from core import db
from core.indoor_report import age_text, is_stale
from ui import page_setup

page_setup("Home")
st.title("Greenhouse")

now = datetime.now(timezone.utc)
controller, readings, relays = st.columns(3)

with controller.container(border=True):
    st.caption("Controller")
    status = db.device_status()
    if status is None:
        st.badge("Unknown", icon=":material/help:", color="gray")
        st.write("No status received yet.")
    elif status["status"] == "online":
        st.badge("Online", icon=":material/check_circle:", color="green")
        st.write(f"Since {age_text(status['updated_utc'], now)}")
    else:
        st.badge("Offline", icon=":material/error:", color="red")
        st.write(f"Since {age_text(status['updated_utc'], now)}")

with readings.container(border=True):
    st.caption("Greenhouse readings")
    latest = db.latest_sensor_readings()
    if latest is None:
        st.badge("None yet", icon=":material/help:", color="gray")
    else:
        newest = latest["reading_utc"].max()
        if is_stale(newest, now):
            st.badge("Stale", icon=":material/warning:", color="orange")
        else:
            st.badge("Fresh", icon=":material/check_circle:", color="green")
        st.write(f"Latest {age_text(newest, now)}")

with relays.container(border=True):
    st.caption("Relays")
    states = db.latest_relay_states()
    if states is None:
        st.write("No relay changes logged yet.")
    else:
        for row in states.itertuples():
            icon = ":material/toggle_on:" if row.state else ":material/toggle_off:"
            st.write(f"{icon} **{row.relay.capitalize()}**: {'On' if row.state else 'Off'} ({row.source})")
