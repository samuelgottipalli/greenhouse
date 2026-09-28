"""
Settings › Controllers tab: connect a controller to Wi-Fi, and update its software.

For the controller chosen in the sidebar it shows:

* **Software**: the version it runs and the version this server offers
  (``core/firmware.py``), how the last update went, and an **Update
  controller** button while it is online and out of date (see docs/MQTT.md,
  "Over-the-air updates").
* **Connect it to Wi-Fi**: how to start the controller's setup hotspot, and a
  QR code and setup code holding this server's address and the controller's
  broker login (``core/setup_code.py``). When the broker needs logins but the
  controller's password isn't stored yet (``core/device_credentials.py``), it
  asks for it first.
"""
from datetime import datetime, timezone

import streamlit as st

from core import db, device_credentials, firmware, settings, setup_code
from core.indoor_report import age_text
from ui import current_device

FIRMWARE_STATES = {
    "running": "Running",
    "updating": "Downloading an update",
    "restarting": "Restarting into the update",
    "updated": "Updated",
    "failed": "Last update failed; nothing was changed",
    "rolled_back": "Last update didn't start properly and was undone",
}


def render() -> None:
    """Draw this section (called by its tabbed page)."""
    device_id = current_device()
    devices = db.list_devices() or {}
    st.subheader(f"Controller {device_id}" + (f" ({devices[device_id]})" if device_id in devices else ""))

    st.markdown("#### Software")
    status = db.device_status(device_id=device_id) or {}
    installed = status.get("firmware_version")
    available = firmware.available_version()
    online = status.get("status") == "online"
    left, right = st.columns(2)
    left.metric("Installed", installed or "Not reported")
    right.metric("Available", available)
    if status.get("firmware_state"):
        when = age_text(status["firmware_utc"], datetime.now(timezone.utc)) if status.get("firmware_utc") else ""
        detail = f": {status['firmware_detail']}" if status.get("firmware_detail") else ""
        st.caption(f"{FIRMWARE_STATES.get(status['firmware_state'], status['firmware_state'])}{detail} ({when})")
    if installed == available:
        st.success("Up to date.", icon=":material/check_circle:")
    else:
        if installed is None:
            st.info("The controller hasn't reported its version yet (older software does not). You can "
                    "still update it; only files that differ are sent.", icon=":material/info:")
        else:
            st.info("A software update is available.", icon=":material/system_update:")
        reachable = setup_code.server_address() is not None
        if st.button("Update controller", icon=":material/system_update:", disabled=not (online and reachable),
                     help="The controller downloads the new files, checks them, and restarts (about a "
                          "minute). If the new version doesn't start properly, it goes back to the old one."):
            if firmware.publish_update(device_id):
                st.success("Update sent. The controller restarts in about a minute; refresh this page to see "
                           "the new version.", icon=":material/check_circle:")
            else:
                st.error("The update couldn't be sent: the broker didn't answer.", icon=":material/error:")
        if not online:
            st.caption("The controller must be online to update.")

    st.markdown("#### Connect it to Wi-Fi")
    st.markdown(
        "1. **New controller:** just switch it on. **Changing Wi-Fi:** hold the screen button (the one "
        "on its own) while switching it on, until the screen says *setup*.\n"
        "2. On your phone, join the Wi-Fi network shown on the controller's screen "
        "(`GreenhouseSetup-…`) with the password shown there.\n"
        "3. Scan the QR code below with the phone's camera, or open **http://192.168.4.1** and paste the "
        "setup code.\n"
        "4. Pick your Wi-Fi network, type its password and tap **Save and connect**. The controller "
        "restarts and appears as *online* on the Home page within a minute."
    )

    host = setup_code.server_address()
    login = device_credentials.get(device_id)
    needs_login = bool(settings.MQTT_USERNAME)

    if not host:
        st.warning("This computer's network address couldn't be found. Set `PUBLIC_HOST` in `server/.env` "
                   "to its IP address (for example 192.168.1.20) and restart the dashboard.")
    elif needs_login and login is None:
        user = device_credentials.device_user(device_id)
        st.info(f"The broker password of **{user}** isn't stored on this server yet. The installer stores it "
                "when it creates the login; if you created it by hand, enter it here.")
        with st.form("controller_login"):
            password = st.text_input(f"Broker password for {user}", type="password")
            if st.form_submit_button("Save password") and password:
                device_credentials.save(device_id, user, password)
                st.rerun()
    else:
        code = setup_code.encode(
            host,
            settings.MQTT_PORT,
            device_id,
            login["user"] if login else None,
            login["password"] if login else None,
            settings.TIMEZONE,
        )
        left, right = st.columns([1, 2], vertical_alignment="center")
        with left:
            st.image(setup_code.qr_png(setup_code.setup_link(code)), caption="Scan with the phone's camera")
        with right:
            st.markdown("**Setup code**")
            st.code(code, language=None, wrap_lines=True)
            st.caption(f"Server address inside the code: {host}:{settings.MQTT_PORT}. The code contains the "
                       "controller's password, so share it only with people you trust.")
