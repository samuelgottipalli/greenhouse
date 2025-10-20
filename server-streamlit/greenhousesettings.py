import streamlit as st
from streamlit.delta_generator import DeltaGenerator
import local_utils as lu
from pandas import DataFrame


st.set_page_config(
    page_title="Greenhouse Settings",
    page_icon=r"images\favicon.png",
    layout="centered",
)
st.logo(r"images\favicon.png", icon_image=r"images\favicon.png", size="large")

st.title("Greenhouse Settings")

if "units" not in st.session_state:
    st.session_state["units"] = "US"
units = lu.get_units(units=st.session_state["units"])

data = lu.read_greenhouse_conditions()
fan_on_temp_val = float(data.loc[data["conditionname"] == "fan_on_temp", "value"].values[0])
fan_on_temp_buffer_val = float(data.loc[data["conditionname"] == "fan_on_temp", "buffer"].values[0])
heater_on_temp_val = float(data.loc[data["conditionname"] == "heater_on_temp", "value"].values[0])
heater_on_temp_buffer_val = float(data.loc[data["conditionname"] == "heater_on_temp", "buffer"].values[0])
fan_on_humidity_val = float(data.loc[data["conditionname"] == "fan_on_humidity", "value"].values[0])
fan_on_humidity_buffer_val = float(data.loc[data["conditionname"] == "fan_on_humidity", "buffer"].values[0])
water_on_time_1_val = data.loc[data["conditionname"] == "water_on_time_1", "value"].values[0]
water_run_time_1_val = data.loc[data["conditionname"] == "water_on_time_1", "buffer"].values[0]
water_on_time_2_val = data.loc[data["conditionname"] == "water_on_time_2", "value"].values[0]
water_run_time_2_val = data.loc[data["conditionname"] == "water_on_time_2", "buffer"].values[0]
water_on_time_3_val = data.loc[data["conditionname"] == "water_on_time_3", "value"].values[0]
water_run_time_3_val = data.loc[data["conditionname"] == "water_on_time_3", "buffer"].values[0]
water_on_time_4_val = data.loc[data["conditionname"] == "water_on_time_4", "value"].values[0]
water_run_time_4_val = data.loc[data["conditionname"] == "water_on_time_4", "buffer"].values[0]

if st.session_state["units"] == "SI":
    temperature_unit = units.loc[units["measurename"] == "temperature", "siunit"].values[0]
else:
    temperature_unit = units.loc[units["measurename"] == "temperature", "englishunit"].values[0]
    fan_on_temp_val = round((fan_on_temp_val * 9 / 5) + 32, 2)
    # fan_on_temp_buffer_val = round((fan_on_temp_val * 9 / 5) + 32, 2)
    heater_on_temp_val = round((heater_on_temp_val * 9 / 5) + 32, 2)
    # heater_on_temp_buffer_val = round((fan_on_temp_val * 9 / 5) + 32, 2)


with st.container(border=True):
    left, right = st.columns(2)

    fan_on_temp: int|float = left.number_input(
        label=f"Turn on fan at ({temperature_unit})",
        help="Temperature at which the fan should turn on.",
        key="fan_on_temp",
        value=fan_on_temp_val,
    )
    fan_on_temp_buffer: int|float = right.number_input(
        label=f"Buffer ({temperature_unit})",
        help="""Temperature buffer at which the fan should turn off.
        Example: If the fan turned on at 70 (F) and buffer is 2 (F), then the fan will turn
        off when temperature drops to 68 (F).""",
        key="fan_on_temp_buffer",
        value=fan_on_temp_buffer_val,
    )
    heater_on_temp: int|float = left.number_input(
        label=f"Turn on heater at ({temperature_unit})",
        help="Temperature at which the heater should turn on.",
        key="heater_on_temp",
        value=heater_on_temp_val,
    )
    heater_on_temp_buffer: int|float = right.number_input(
        label=f"Buffer ({temperature_unit})",
        help="""Temperature buffer at which the heater should turn off.
        Example: If the heater turned on at 70 (F) and buffer is 2 (F), then the heater will turn
        off when temperature rises to 72 (F).""",
        key="heater_on_temp_buffer",
        value=heater_on_temp_buffer_val,
    )
    fan_on_humidity: int|float = left.number_input(
        label="Turn on fan at (% - RH)",
        help="Humidity at which the fan should turn on",
        key="fan_on_humidity",
        value=fan_on_humidity_val,
    )
    fan_on_humidity_buffer: int|float = right.number_input(
        label="Buffer (% - RH)",
        help="""Humidity buffer at which the fan should turn off.
        Example: If the fan turned on at 50 % (RH) and buffer is 2 % (RH), then the fan will turn
        off when humidity drops to 48 % (RH).""",
        key="fan_on_humidity_buffer",
        value=fan_on_humidity_buffer_val,
    )
    water_on_time_1: str = str(
        left.time_input(
            label="Water on time: 1 (HH:MM)",
            help="Time at which water should be turned on",
            key="water_on_time_1",
            value=water_on_time_1_val,
        )
    )
    water_run_time_1: str = str(
        right.time_input(
            label="Run time: 1 (HH:MM)",
            help="How long should the water run for?",
            key="water_run_time_1",
            value=water_run_time_1_val,
        )
    )
    water_on_time_2: str = str(
        left.time_input(
            label="Water on time: 2 (HH:MM)",
            help="Time at which water should be turned on",
            key="water_on_time_2",
            value=water_on_time_2_val,
        )
    )
    water_run_time_2: str = str(
        right.time_input(
            label="Run time: 2 (HH:MM)",
            help="How long should the water run for?",
            key="water_run_time_2",
            value=water_run_time_2_val,
        )
    )
    water_on_time_3: str = str(
        left.time_input(
            label="Water on time:3 (HH:MM)",
            help="Time at which water should be turned on",
            key="water_on_time_3",
            value=water_on_time_3_val,
        )
    )
    water_run_time_3: str = str(
        right.time_input(
            label="Run time:3 (HH:MM)",
            help="How long should the water run for?",
            key="water_run_time_3",
            value=water_run_time_3_val,
        )
    )
    water_on_time_4: str = str(
        left.time_input(
            label="Water on time: 4 (HH:MM)",
            help="Time at which water should be turned on",
            key="water_on_time_4",
            value=water_on_time_4_val,
        )
    )
    water_run_time_4: str = str(
        right.time_input(
            label="Run time: 4 (HH:MM)",
            help="How long should the water run for?",
            key="water_run_time_4",
            value=water_run_time_4_val,
        )
    )
with st.container(horizontal=True, horizontal_alignment="right"):
    if st.button("Save", icon=":material/save:"):
        if st.session_state["units"] == "US":
            fan_on_temp = round((fan_on_temp - 32) * 5 / 9, 2)
            heater_on_temp = round((heater_on_temp - 32) * 5 / 9, 2)

        data: DataFrame = DataFrame(
            data=[
                [1, 1, water_on_time_1, water_run_time_1, "water_on_time_1"],
                [1, 2, water_on_time_2, water_run_time_2, "water_on_time_2"],
                [1, 3, water_on_time_3, water_run_time_3, "water_on_time_3"],
                [1, 4, water_on_time_4, water_run_time_4, "water_on_time_4"],
                [2, 1, fan_on_temp, fan_on_temp_buffer, "fan_on_temp"],
                [2, 2, fan_on_humidity, fan_on_humidity_buffer, "fan_on_humidity"],
                [3, 1, heater_on_temp, heater_on_temp_buffer, "heater_on_temp"],
            ],
            columns=[
                "relay_id",
                "condition",
                "value",
                "buffer",
                "conditionname"
            ],
        )
        data["deviceid"] = "001"
        print(data)

        st.toast("Settings saved!", icon=":material/check_circle:")
    if st.button("Revert", icon=":material/undo:"):
        revert_toast: DeltaGenerator = st.toast(
            body="Greenhouse Settings are being reverted to last saved values...",
            icon=":material/hourglass:",
        )
        settings_status: bool = lu.revert_greenhouse_conditions()
        if settings_status:
            revert_toast.toast(
                body="Greenhouse Settings reverted to last saved values!",
                icon=":material/check_circle:",
            )
        else:
            revert_toast.toast(
                body="Greenhouse Settings could not be reverted to last saved values!",
                icon=":material/error:",
            )
    if st.button(label="Restore Defaults", icon=":material/restore:"):
        reset_toast: DeltaGenerator = st.toast(
            body="Greenhouse Settings are being restored to defaults...",
            icon=":material/hourglass:",
        )
        settings_status: bool = lu.reset_greenhouse_conditions()
        if settings_status:
            reset_toast.toast(
                body="Greenhouse Settings restored to defaults!",
                icon=":material/check_circle:",
            )
        else:
            reset_toast.toast(
                body="Greenhouse Settings could not be restored to defaults!",
                icon=":material/error:",
            )
