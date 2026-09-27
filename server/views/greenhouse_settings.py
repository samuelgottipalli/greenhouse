"""
Greenhouse Settings page: edit the automation thresholds and watering
schedule used by ``services/automation.py``.

Shows fan/heater temperature triggers and the fan humidity trigger (each with
a hysteresis buffer), and four watering slots (start time + minutes).
Temperatures and their buffers are stored in °C; when the session's units
are "US" they are shown in °F (buffers as temperature differences, without the
32° offset) and converted back on save.

Buttons:
    * Save: store the values shown.
    * Revert: discard unsaved edits and reload the saved values.
    * Restore Defaults: replace the saved values with the factory defaults.
"""
import streamlit as st

from core import db
from core.conversions import (
    celsius_delta_to_fahrenheit,
    celsius_to_fahrenheit,
    fahrenheit_delta_to_celsius,
    fahrenheit_to_celsius,
)
from core.timeutil import format_time_of_day
from ui import current_device, page_setup

page_setup("Greenhouse Settings")
st.title("Greenhouse Settings")

TEMPERATURE_FIELDS = ["fan_on_temp", "heater_on_temp"]
TEMPERATURE_BUFFER_FIELDS = ["fan_on_temp_buffer", "heater_on_temp_buffer"]
THRESHOLD_FIELDS = {
    # widget key: (threshold name, "value" | "buffer")
    "fan_on_temp": ("fan_on_temp_c", "value"),
    "fan_on_temp_buffer": ("fan_on_temp_c", "buffer"),
    "heater_on_temp": ("heater_on_temp_c", "value"),
    "heater_on_temp_buffer": ("heater_on_temp_c", "buffer"),
    "fan_on_humidity": ("fan_on_humidity_pct", "value"),
    "fan_on_humidity_buffer": ("fan_on_humidity_pct", "buffer"),
}
SLOTS = [1, 2, 3, 4]
WIDGET_KEYS = list(THRESHOLD_FIELDS) + [f"water_on_time_{s}" for s in SLOTS] + [f"water_run_time_{s}" for s in SLOTS]


def clear_form() -> None:
    """Forget edited widget values so the next run reloads them from the database."""
    for key in WIDGET_KEYS:
        st.session_state.pop(key, None)


def revert() -> None:
    """Button callback: discard unsaved edits."""
    clear_form()
    st.session_state["settings_notice"] = ("Greenhouse Settings reverted to last saved values!", ":material/check_circle:")


def restore_defaults() -> None:
    """Button callback: copy the default profile over the current settings."""
    if db.restore_default_settings(device_id=current_device()):
        clear_form()
        st.session_state["settings_notice"] = ("Greenhouse Settings restored to defaults!", ":material/check_circle:")
    else:
        st.session_state["settings_notice"] = ("Greenhouse Settings could not be restored to defaults!", ":material/error:")


if notice := st.session_state.pop("settings_notice", None):
    st.toast(body=notice[0], icon=notice[1])

us_units = st.session_state["units"] == "US"
units = db.unit_labels(st.session_state["units"])
thresholds = db.read_thresholds(device_id=current_device())
schedule = db.read_watering_schedule(device_id=current_device())
if thresholds is None or schedule is None or units is None:
    st.error("Greenhouse settings not found! Run `python -m scripts.upgrade_db` to create them.")
    st.stop()

limits = thresholds.set_index("name")
initial = {key: float(limits.loc[name, part]) for key, (name, part) in THRESHOLD_FIELDS.items()}
if us_units:
    for key in TEMPERATURE_FIELDS:
        initial[key] = celsius_to_fahrenheit(initial[key])
    for key in TEMPERATURE_BUFFER_FIELDS:
        initial[key] = celsius_delta_to_fahrenheit(initial[key])
slots = schedule.set_index("slot")
temperature_unit = units["temperature"]

with st.container(border=True):
    left, right = st.columns(2)
    fan_on_temp = left.number_input(
        label=f"Turn on fan at ({temperature_unit})",
        help="Temperature at which the fan should turn on.",
        key="fan_on_temp",
        value=initial["fan_on_temp"],
    )
    fan_on_temp_buffer = right.number_input(
        label=f"Buffer ({temperature_unit})",
        help="""Temperature buffer at which the fan should turn off.
        Example: If the fan turned on at 70 (F) and buffer is 2 (F), then the fan will turn
        off when temperature drops to 68 (F).""",
        key="fan_on_temp_buffer",
        value=initial["fan_on_temp_buffer"],
    )
    heater_on_temp = left.number_input(
        label=f"Turn on heater at ({temperature_unit})",
        help="Temperature at which the heater should turn on.",
        key="heater_on_temp",
        value=initial["heater_on_temp"],
    )
    heater_on_temp_buffer = right.number_input(
        label=f"Buffer ({temperature_unit})",
        help="""Temperature buffer at which the heater should turn off.
        Example: If the heater turned on at 70 (F) and buffer is 2 (F), then the heater will turn
        off when temperature rises to 72 (F).""",
        key="heater_on_temp_buffer",
        value=initial["heater_on_temp_buffer"],
    )
    fan_on_humidity = left.number_input(
        label="Turn on fan at (% - RH)",
        help="Humidity at which the fan should turn on",
        key="fan_on_humidity",
        value=initial["fan_on_humidity"],
    )
    fan_on_humidity_buffer = right.number_input(
        label="Buffer (% - RH)",
        help="""Humidity buffer at which the fan should turn off.
        Example: If the fan turned on at 50 % (RH) and buffer is 2 % (RH), then the fan will turn
        off when humidity drops to 48 % (RH).""",
        key="fan_on_humidity_buffer",
        value=initial["fan_on_humidity_buffer"],
    )
    water_slots: dict[int, tuple[str, int]] = {}
    for slot in SLOTS:
        start = left.time_input(
            label=f"Water on time: {slot} (HH:MM)",
            help="Time at which water should be turned on",
            key=f"water_on_time_{slot}",
            value=slots.loc[slot, "start_local"],
        )
        minutes = right.number_input(
            label=f"Run time: {slot} (minutes)",
            help="How long should the water run for? 0 turns this slot off.",
            key=f"water_run_time_{slot}",
            min_value=0,
            max_value=1440,
            step=5,
            value=int(slots.loc[slot, "duration_min"]),
        )
        water_slots[slot] = (format_time_of_day(start), int(minutes))

with st.container(horizontal=True, horizontal_alignment="right"):
    if st.button("Save", icon=":material/save:"):
        if us_units:
            fan_on_temp = fahrenheit_to_celsius(fan_on_temp)
            heater_on_temp = fahrenheit_to_celsius(heater_on_temp)
            fan_on_temp_buffer = fahrenheit_delta_to_celsius(fan_on_temp_buffer)
            heater_on_temp_buffer = fahrenheit_delta_to_celsius(heater_on_temp_buffer)
        saved = db.save_settings(
            thresholds={
                "fan_on_temp_c": (fan_on_temp, fan_on_temp_buffer),
                "fan_on_humidity_pct": (fan_on_humidity, fan_on_humidity_buffer),
                "heater_on_temp_c": (heater_on_temp, heater_on_temp_buffer),
            },
            schedule=water_slots,
            device_id=current_device(),
        )
        if saved:
            st.toast(body="Greenhouse Settings saved!", icon=":material/check_circle:")
        else:
            st.toast(body="Greenhouse Settings could not be saved!", icon=":material/error:")
    st.button("Revert", icon=":material/undo:", on_click=revert)
    st.button(label="Restore Defaults", icon=":material/restore:", on_click=restore_defaults)
