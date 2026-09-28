"""
Remote Control page: manual on/off toggles for the fan, heater, light and
water relays.

Relays are found by name in the ``relays`` table, and their current state is
the latest ``relay_events`` row (off if a relay has no history yet).
Flipping a toggle publishes the command over MQTT
(``core.mqtt.publish_relay_command``) and logs it with source ``"web"``.
"""
import streamlit as st

from core import db
from core.mqtt import publish_relay_command
from core.timeutil import utc_timestamp
from ui import auto_refresh, current_device, page_setup

page_setup("Greenhouse Control")
auto_refresh("control", ("device", "relays"))

# Display order, by relay name. The widget key is the relay number.
CONTROLLED_RELAYS: list[str] = ["fan", "heater", "light", "water"]


def insert_relay_status(relay_id: int, relay: str) -> None:
    """
    Publish the toggle's new state over MQTT and log it to the database.

    Used as the ``on_change`` callback of each toggle. The state is read from
    the widget and the time taken when the callback runs, so the command
    always matches what the user just did (fixes S-03). The change is only
    logged if the broker accepted the command (S-19).

    Args:
        relay_id (int): Relay number; also the widget key.
        relay (str): Relay name, for messages.
    """
    state = 1 if st.session_state[str(relay_id)] else 0
    name = relay.capitalize()
    action = "On" if state else "Off"

    device_id = current_device()
    if not publish_relay_command(relay_id=relay_id, state=state, source="web", device_id=device_id):
        # Not sent, so nothing changed: don't log it (the toggle snaps back on rerun).
        st.toast(body=f"Could not reach the MQTT broker; {name} was not switched.", icon=":material/error:")
        return
    st.toast(body=f"{name} status '{action}' published via MQTT", icon=":material/published_with_changes:")

    if db.log_relay_event(relay_id=relay_id, state=state, source="web", device_id=device_id,
                          event_utc=utc_timestamp()):
        st.toast(body=f"{name} turned {action} via app", icon=":material/thumb_up:")
    else:
        st.toast("Unable to insert relay status data into DB.", icon=":material/error:")


def relay_rows() -> list[dict] | None:
    """
    Combine relay names with their latest logged state.

    Returns:
        list[dict] | None: One dict per controlled relay that exists, with
        ``relay_id``, ``relay``, ``state`` and ``source`` (``None`` when the
        relay has no events yet), in ``CONTROLLED_RELAYS`` order; None if the
        relay list could not be read.
    """
    names = db.relay_names(device_id=current_device())
    if names is None:
        return None
    states = db.latest_relay_states(device_id=current_device())
    latest = {} if states is None else states.set_index("relay_id").to_dict("index")
    ids = {name: relay_id for relay_id, name in names.items()}
    rows = []
    for name in CONTROLLED_RELAYS:
        if name in ids:
            event = latest.get(ids[name], {})
            rows.append({
                "relay_id": ids[name],
                "relay": name,
                "state": int(event.get("state", 0)),
                "source": event.get("source"),
            })
    return rows


def load_page(rows: list[dict] | None, offline: bool = False) -> None:
    """
    Render one toggle and status badge per controlled relay.

    Args:
        rows (list[dict] | None): Output of :func:`relay_rows`.
        offline (bool): The controller last reported offline; commands would
            be lost, so the toggles are disabled (S-20).
    """
    if rows is None:
        st.error("Relays not found! Run `python -m scripts.upgrade_db` to create them.")
        return
    if offline:
        st.warning(
            "The greenhouse controller is offline, so switches are disabled. It is running its "
            "own safety rules until it reconnects.",
            icon=":material/cloud_off:",
        )
    with st.container(border=True):
        st.subheader(body="Device Status")
        left, right = st.columns([0.3, 0.7])
        toggles, badges = right.columns(2)
        for row in rows:
            name = row["relay"].capitalize()
            left.write(f"{name} Status:")
            # Always show the logged state, so changes made by automation or
            # the device's buttons appear on the next page run.
            st.session_state[str(row["relay_id"])] = bool(row["state"])
            toggles.toggle(
                label=f"Turn {name} On/Off",
                key=str(row["relay_id"]),
                help=f"Toggle to turn the {row['relay']} on or off",
                label_visibility="collapsed",
                on_change=insert_relay_status,
                args=(row["relay_id"], row["relay"]),
                disabled=offline,
            )
            source = f" ({row['source']})" if row["source"] else ""
            badges.badge(
                label=f"{'On' if row['state'] else 'Off'}{source}",
                color="green" if row["state"] else "red",
            )


st.title(body="Greenhouse Remote Control")
st.header(body="Control the greenhouse devices remotely.")
with st.expander("ℹ️ About this app", expanded=False):
    st.write("Devices are controlled via MQTT.")
    st.write("The automation service may switch devices based on your greenhouse rules (Settings › Greenhouse rules).")
    st.write("Use the toggles below to turn the devices on or off manually.")

status = db.device_status(device_id=current_device())
load_page(relay_rows(), offline=status is not None and status["status"] == "offline")
