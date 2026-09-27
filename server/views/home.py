"""
Home page: system health at a glance.

* Controller: online/offline, plus the health it reports in telemetry
  (uptime, Wi-Fi signal, free memory, when it was last heard from), and a
  link to the Controllers page when a software update is available.
* Readings: how old the latest greenhouse reading is (fresh or stale).
* Relays: the logged state of each controlled relay and who set it.
* Services: heartbeat of ingest, automation and weather (ok, degraded,
  down or unknown), from ``core/health.py``.
* Active alerts (``core/alerts.py``) at the top, until they clear.

Every status is shown with an icon and a word, not colour alone.
"""
from datetime import datetime, timezone

import streamlit as st

from core import db, firmware
from core.health import format_duration, service_health, signal_quality
from core.indoor_report import age_text, is_stale
from ui import current_device, page_setup

page_setup("Home")
st.title("Greenhouse")

SERVICE_BADGES = {
    "ok": ("OK", ":material/check_circle:", "green"),
    "degraded": ("Degraded", ":material/warning:", "orange"),
    "down": ("Down", ":material/error:", "red"),
    "unknown": ("Unknown", ":material/help:", "gray"),
}

now = datetime.now(timezone.utc)

for alert in db.active_alerts():
    st.error(f"{alert['message']} (since {age_text(alert['since_utc'], now)})", icon=":material/notifications_active:")

controller, readings, relays = st.columns(3)

with controller.container(border=True):
    st.caption("Controller")
    status = db.device_status(device_id=current_device())
    if status is None:
        st.badge("Unknown", icon=":material/help:", color="gray")
        st.write("No status received yet.")
    else:
        if status["status"] == "online":
            st.badge("Online", icon=":material/check_circle:", color="green")
        else:
            st.badge("Offline", icon=":material/error:", color="red")
        st.write(f"Since {age_text(status['updated_utc'], now)}")
        if status["last_seen_utc"]:
            st.write(
                f"Last message {age_text(status['last_seen_utc'], now)} · "
                f"up {format_duration(status['uptime_s'])}"
            )
            signal = signal_quality(status["rssi_dbm"])
            dbm = f" ({status['rssi_dbm']} dBm)" if status["rssi_dbm"] is not None else ""
            memory = f" · {status['mem_free'] // 1024} KB free" if status["mem_free"] is not None else ""
            st.write(f"Wi-Fi {signal}{dbm}{memory}")
        if status["firmware_version"] and status["firmware_version"] != firmware.available_version():
            st.markdown(":material/system_update: Software update available (Settings, Controllers)")

with readings.container(border=True):
    st.caption("Greenhouse readings")
    latest = db.latest_sensor_readings(device_id=current_device())
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
    states = db.latest_relay_states(device_id=current_device())
    if states is None:
        st.write("No relay changes logged yet.")
    else:
        for row in states.itertuples():
            icon = ":material/toggle_on:" if row.state else ":material/toggle_off:"
            st.write(f"{icon} **{row.relay.capitalize()}**: {'On' if row.state else 'Off'} ({row.source})")

with st.container(border=True):
    st.caption("Services")
    services = service_health(now)
    for column, entry in zip(st.columns(len(services)), services):
        label, icon, color = SERVICE_BADGES[entry["status"]]
        column.write(f"**{entry['service'].capitalize()}**")
        column.badge(label, icon=icon, color=color)
        if entry["updated_utc"]:
            detail = f" · {entry['detail']}" if entry["detail"] else ""
            column.write(f"Last beat {age_text(entry['updated_utc'], now)}{detail}")
        else:
            column.write("Not seen yet.")
