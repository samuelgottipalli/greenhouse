"""
Remote Control page: manual on/off toggles for the fan, heater, light and
water relays.

On load it reads the latest state of each relay from ``relay_events``.
Flipping a toggle publishes the command over MQTT
(``core.mqtt.publish_relay_command``) and logs it with source ``"web"``.
"""
import streamlit as st
from pandas import DataFrame
from streamlit.delta_generator import DeltaGenerator

from core import db
from core.mqtt import publish_relay_command
from core.timeutil import utc_timestamp
from ui import page_setup

page_setup("Greenhouse Control")

# Display order; the widget key is the relay number.
CONTROLLED_RELAYS: list[int] = [2, 3, 4, 1]  # fan, heater, light, water


def insert_relay_status(data: dict[str, str | int] | None) -> None:
    """
    Publish a relay command over MQTT and log it to the database.

    Used as the ``on_change`` callback of each toggle. Shows a toast for each
    step's result.

    Args:
        data (dict[str, str | int] | None): ``relay_id``, ``relay`` (name),
            ``state`` and ``event_utc``. Note that ``state`` and ``event_utc``
            are fixed when the page is rendered, not when the toggle is
            clicked (S-03).
    """
    if not data:
        st.toast("No data to load to DB", icon=":material/warning:")
        return
    relay = data["relay"].capitalize()
    action = "On" if data["state"] else "Off"

    if publish_relay_command(relay_id=data["relay_id"], state=data["state"], source="web"):
        st.toast(body=f"{relay} status '{action}' published via MQTT", icon=":material/published_with_changes:")
    else:
        st.toast(body="Unable to publish relay status to MQTT.", icon=":material/error:")

    if db.log_relay_event(
        relay_id=data["relay_id"], state=data["state"], source="web", event_utc=data["event_utc"]
    ):
        st.toast(body=f"{relay} turned {action} via app", icon=":material/thumb_up:")
    else:
        st.toast("Unable to insert relay status data into DB.", icon=":material/error:")


def load_page(df: DataFrame | None) -> None:
    """
    Render one toggle and status badge per controlled relay.

    Args:
        df (DataFrame | None): Output of ``db.latest_relay_states()``. Must
            contain a row for every relay in ``CONTROLLED_RELAYS``; if it is
            None the page raises when building the toggles (S-09).
    """
    if isinstance(df, DataFrame):
        relay_state_toast.toast(body="Relay state data fetched from DB", icon=":material/check_circle:")
    else:
        relay_state_toast.toast("Error fetching relay state data", icon=":material/error:")

    rows = df.set_index("relay_id")
    with st.container(border=True):
        st.subheader(body="Device Status")
        left, right = st.columns([0.3, 0.7])
        toggles, badges = right.columns(2)
        for relay_id in CONTROLLED_RELAYS:
            row = rows.loc[relay_id]
            name = row["relay"].capitalize()
            key = str(relay_id)
            left.write(f"{name} Status:")
            toggles.toggle(
                label=f"Turn {name} On/Off",
                value=bool(row["state"]),
                key=key,
                help=f"Toggle to turn the {row['relay']} on or off",
                label_visibility="collapsed",
                on_change=insert_relay_status,
                args=[{
                    "relay_id": relay_id,
                    "relay": row["relay"],
                    # S-03: before the widget exists this is always 1 (on).
                    "state": 0 if st.session_state.get(key) else 1,
                    "event_utc": utc_timestamp(),
                }],
            )
            badges.badge(
                label=f"{'On' if row['state'] else 'Off'} ({row['source']})",
                color="green" if st.session_state.get(key) else "red",
            )


st.title(body="Greenhouse Remote Control")
st.header(body="Control the greenhouse devices remotely.")
with st.expander("ℹ️ About this app", expanded=False):
    st.write("Devices are controlled via MQTT.")
    st.write("Device status may change automatically every 15 minutes based on the latest weather data.")
    st.write("Use the toggles below to turn the devices on or off manually.")

relay_state_toast: DeltaGenerator = st.toast("Fetching relay state data...")
load_page(db.latest_relay_states())
