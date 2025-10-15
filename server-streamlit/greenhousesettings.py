from turtle import right
import streamlit as st
import local_utils as lu


st.set_page_config(
    page_title="Greenhouse Settings",
    page_icon=r"images\favicon.png",
    layout="centered",
)
st.logo(r"images\favicon.png", icon_image=r"images\favicon.png", size="large")

st.title("Greenhouse Settings")

if "units" not in st.session_state:
    st.session_state["units"] = "US"


with st.container(border=True):

    # units = lu.get_units(units=st.session_state["units"])

    # if st.session_state["units"] == "SI":
    #     temperature_unit = units.loc[units["measurename"] == "temperature", "siunit"].values[0]
    # else:
    #     temperature_unit = units.loc[units["measurename"] == "temperature", "englishunit"].values[0]
    temperature_unit = "F"

    left, right = st.columns(2)

    left.number_input(
        label=f"Turn on fan at ({temperature_unit})",
        help="Temperature at which the fan should turn on.",
        key="fan_on_temp",
        value=80,
    )
    right.number_input(
        label=f"Buffer ({temperature_unit})",
        help="""Temperature buffer at which the fan should turn off.
        Example: If the fan turned on at 70 (F) and buffer is 2 (F), then the fan will turn
        off when temperature drops to 68 (F).""",
        key="fan_on_temp_buffer",
        value=2,
    )
    left.number_input(
        label=f"Turn on heater at ({temperature_unit})",
        help="Temperature at which the heater should turn on.",
        key="heater_on_temp",
        value=70,
    )
    right.number_input(
        label=f"Buffer ({temperature_unit})",
        help="""Temperature buffer at which the heater should turn off.
        Example: If the heater turned on at 70 (F) and buffer is 2 (F), then the heater will turn
        off when temperature rises to 72 (F).""",
        key="heater_on_temp_buffer",
        value=2,
    )
    left.text_input(
        label="Turn on fan at (% - RH)",
        help="Humidity at which the fan should turn on",
        max_chars=4,
        key="fan_on_humidity",
        value="50",
    )
    right.text_input(
        label=f"Buffer (% - RH)",
        help="""Humidity buffer at which the fan should turn off.
        Example: If the fan turned on at 50 % (RH) and buffer is 2 % (RH), then the fan will turn
        off when humidity drops to 48 % (RH).""",
        max_chars=4,
        key="fan_on_humidity_buffer",
        value="2",
    )
    left.time_input(
        label="Water on time: 1 (HH:MM)",
        help="Time at which water should be turned on",
        key="water_on_time_1",
        value="00:00",
    )
    right.time_input(
        label="Run time: 1 (HH:MM)",
        help="How long should the water run for?",
        key="water_run_time_1",
        value="00:00",
    )
    left.time_input(
        label="Water on time: 2 (HH:MM)",
        help="Time at which water should be turned on",
        key="water_on_time_2",
        value="00:00",
    )
    right.text_input(label="Run time (2)")
    left.time_input(
        label="Water on time:3 (HH:MM)",
        help="Time at which water should be turned on",
        key="water_on_time_3",
        value="00:00",
    )
    right.text_input(label="Run time (3)")
    left.time_input(
        label="Water on time: 4 (HH:MM)",
        help="Time at which water should be turned on",
        key="water_on_time_4",
        value="00:00",
    )
    right.text_input(label="Run time (4)")
