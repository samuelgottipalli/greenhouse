"""
Controllers page: connect a controller to Wi-Fi with a setup code.

For the controller chosen in the sidebar it shows how to start the
controller's setup hotspot, and a QR code and setup code holding this
server's address and the controller's broker login (``core/setup_code.py``).
When the broker needs logins but the controller's password isn't stored yet
(``core/device_credentials.py``), it asks for it first.
"""
import streamlit as st

from core import db, device_credentials, settings, setup_code
from ui import current_device, page_setup

page_setup("Controllers")
st.title("Controllers")

device_id = current_device()
devices = db.list_devices() or {}
st.subheader(f"Controller {device_id}" + (f" ({devices[device_id]})" if device_id in devices else ""))

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
        st.html(setup_code.qr_svg(setup_code.setup_link(code)))
    with right:
        st.markdown("**Setup code**")
        st.code(code, language=None, wrap_lines=True)
        st.caption(f"Server address inside the code: {host}:{settings.MQTT_PORT}. The code contains the "
                   "controller's password, so share it only with people you trust.")
