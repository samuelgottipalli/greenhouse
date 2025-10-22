import local_utils as lu
import pub_to_pico as pub
from os import getenv
from datetime import datetime as dtt, timedelta
from pytz import utc


lu.get_config()
DB_CONN_STRING = getenv(key="DB_CONNECTION_STRING", default="sqlite:///greenhouse.db")

# while True:
condition_data: None | lu.DataFrame = lu.read_greenhouse_conditions()
greenhouse_data: None | lu.DataFrame = lu.read_greenhouse_data()
greenhouse_relay_state: None | lu.DataFrame = lu.read_relay_status()

utctime = dtt.now(tz=utc).strftime("%Y-%m-%d %H:%M:%S")

currenttime = dtt.now()
# print(currenttime)
# print(utctime)

# print(condition_data)
# print(greenhouse_data)
# print(greenhouse_relay_state)
# exit(5)

if (
    condition_data is not None
    and greenhouse_data is not None
    and greenhouse_relay_state is not None
    and not condition_data.empty
    and not greenhouse_data.empty
    and not greenhouse_relay_state.empty
):
    fan_on_temp_val = float(
        condition_data.loc[
            condition_data["conditionname"] == "fan_on_temp", "value"
        ].values[0]
    )
    fan_on_temp_buffer_val = float(
        condition_data.loc[
            condition_data["conditionname"] == "fan_on_temp", "buffer"
        ].values[0]
    )
    heater_on_temp_val = float(
        condition_data.loc[
            condition_data["conditionname"] == "heater_on_temp", "value"
        ].values[0]
    )
    heater_on_temp_buffer_val = float(
        condition_data.loc[
            condition_data["conditionname"] == "heater_on_temp", "buffer"
        ].values[0]
    )
    fan_on_humidity_val = float(
        condition_data.loc[
            condition_data["conditionname"] == "fan_on_humidity", "value"
        ].values[0]
    )
    fan_on_humidity_buffer_val = float(
        condition_data.loc[
            condition_data["conditionname"] == "fan_on_humidity", "buffer"
        ].values[0]
    )
    light_on_lumen_val = float(
        condition_data.loc[
            condition_data["conditionname"] == "light_on_lumen", "value"
        ].values[0]
    )

    water_on_time_1_val = condition_data.loc[
        condition_data["conditionname"] == "water_on_time_1", "value"
    ].values[0]
    water_run_time_1_val = condition_data.loc[
        condition_data["conditionname"] == "water_on_time_1", "buffer"
    ].values[0]
    water_on_time_1_val = dtt.strptime(water_on_time_1_val, "%H:%M").replace(
        year=dtt.now().year, month=dtt.now().month, day=dtt.now().day
    )
    water_off_time_1_val = water_on_time_1_val + timedelta(
        hours=int(water_run_time_1_val[:2]), minutes=int(water_run_time_1_val[3:])
    )

    water_on_time_2_val = condition_data.loc[
        condition_data["conditionname"] == "water_on_time_2", "value"
    ].values[0]
    water_run_time_2_val = condition_data.loc[
        condition_data["conditionname"] == "water_on_time_2", "buffer"
    ].values[0]
    water_on_time_2_val = dtt.strptime(water_on_time_2_val, "%H:%M").replace(
        year=dtt.now().year, month=dtt.now().month, day=dtt.now().day
    )
    water_off_time_2_val = water_on_time_2_val + timedelta(
        hours=int(water_run_time_2_val[:2]), minutes=int(water_run_time_2_val[3:])
    )

    water_on_time_3_val = condition_data.loc[
        condition_data["conditionname"] == "water_on_time_3", "value"
    ].values[0]
    water_run_time_3_val = condition_data.loc[
        condition_data["conditionname"] == "water_on_time_3", "buffer"
    ].values[0]
    water_on_time_3_val = dtt.strptime(water_on_time_3_val, "%H:%M").replace(
        year=dtt.now().year, month=dtt.now().month, day=dtt.now().day
    )
    water_off_time_3_val = water_on_time_3_val + timedelta(
        hours=int(water_run_time_3_val[:2]), minutes=int(water_run_time_3_val[3:])
    )

    water_on_time_4_val = condition_data.loc[
        condition_data["conditionname"] == "water_on_time_4", "value"
    ].values[0]
    water_run_time_4_val = condition_data.loc[
        condition_data["conditionname"] == "water_on_time_4", "buffer"
    ].values[0]
    water_on_time_4_val = dtt.strptime(water_on_time_4_val, "%H:%M").replace(
        year=dtt.now().year, month=dtt.now().month, day=dtt.now().day
    )
    water_off_time_4_val = water_on_time_4_val + timedelta(
        hours=int(water_run_time_4_val[:2]), minutes=int(water_run_time_4_val[3:])
    )

    greenhouse_temp = greenhouse_data.loc[
        greenhouse_data["measurename"] == "temperature", "value_001"
    ].values[0]
    greenhouse_humidity = greenhouse_data.loc[
        greenhouse_data["measurename"] == "humidity", "value_001"
    ].values[0]
    # greenhouse_light = greenhouse_data.loc[greenhouse_data["measurename"] == "light_intensity", "value_001"].values[0]

    fan_relay_state = greenhouse_relay_state.loc[
        greenhouse_relay_state["relayname"] == "fan", "actionid"
    ].values[0]
    heater_relay_state = greenhouse_relay_state.loc[
        greenhouse_relay_state["relayname"] == "heater", "actionid"
    ].values[0]
    light_relay_state = greenhouse_relay_state.loc[
        greenhouse_relay_state["relayname"] == "light", "actionid"
    ].values[0]
    water_relay_state = greenhouse_relay_state.loc[
        greenhouse_relay_state["relayname"] == "water", "actionid"
    ].values[0]


if greenhouse_humidity > fan_on_humidity_val:
    if fan_relay_state[-1] == "1":
        if greenhouse_humidity > fan_on_humidity_val - fan_on_humidity_buffer_val:
            pass
    else:
        pub.publish_relay_status(device_id="001", relay_id="2", action_id="011")
        data = {
            "actiontime": utctime,
            "deviceid": "001",
            "relayid": "2",
            "actionid": "011",
        }
        lu.write_relay_status(data=data)
else:
    if fan_relay_state[-1] == "0":
        pass
    elif greenhouse_temp > fan_on_temp_val - fan_on_temp_buffer_val:
        pass
    else:
        pub.publish_relay_status(device_id="001", relay_id="2", action_id="010")
        data = {
            "actiontime": utctime,
            "deviceid": "001",
            "relayid": "2",
            "actionid": "010",
        }
        lu.write_relay_status(data=data)

if greenhouse_temp > fan_on_temp_val:
    if fan_relay_state[-1] == "1":
        if greenhouse_temp > fan_on_temp_val - fan_on_temp_buffer_val:
            pass
    else:
        pub.publish_relay_status(device_id="001", relay_id="2", action_id="011")
        data = {
            "actiontime": utctime,
            "deviceid": "001",
            "relayid": "2",
            "actionid": "011",
        }
        lu.write_relay_status(data=data)
else:
    if fan_relay_state[-1] == "0":
        pass
    elif greenhouse_temp > fan_on_humidity_val - fan_on_humidity_buffer_val:
        pass
    else:
        pub.publish_relay_status(device_id="001", relay_id="2", action_id="010")
        data = {
            "actiontime": utctime,
            "deviceid": "001",
            "relayid": "2",
            "actionid": "010",
        }
        lu.write_relay_status(data=data)

if greenhouse_temp < heater_on_temp_val:
    if heater_relay_state[-1] == "1":
        if greenhouse_temp > heater_on_temp_val - heater_on_temp_buffer_val:
            pass
    else:
        pub.publish_relay_status(device_id="001", relay_id="2", action_id="011")
        data = {
            "actiontime": utctime,
            "deviceid": "001",
            "relayid": "3",
            "actionid": "011",
        }
        lu.write_relay_status(data=data)
else:
    if heater_relay_state[-1] == "0":
        pass
    else:
        pub.publish_relay_status(device_id="001", relay_id="2", action_id="010")
        data = {
            "actiontime": utctime,
            "deviceid": "001",
            "relayid": "3",
            "actionid": "010",
        }
        lu.write_relay_status(data=data)

if (
    water_on_time_1_val <= currenttime <= water_off_time_1_val
    or water_on_time_2_val <= currenttime <= water_off_time_2_val
    or water_on_time_3_val <= currenttime <= water_off_time_3_val
    or water_on_time_4_val <= currenttime <= water_off_time_4_val
):
    if water_relay_state[-1] == "1":
        pass
    else:
        pub.publish_relay_status(device_id="001", relay_id="1", action_id="011")
        data = {
            "actiontime": utctime,
            "deviceid": "001",
            "relayid": "1",
            "actionid": "011",
        }
        lu.write_relay_status(data=data)
else:
    if water_relay_state[-1] == "0":
        pass
    else:
        pub.publish_relay_status(device_id="001", relay_id="1", action_id="010")
        data = {
            "actiontime": utctime,
            "deviceid": "001",
            "relayid": "1",
            "actionid": "010",
        }
        lu.write_relay_status(data=data)


# Light Status logic to be updated later
# if (
#     sunrise_time_val <= currenttime <= sunset_time_val
#     and greenhouse_light < light_on_lumen_val
# ):
#     if light_relay_state[-1] == "1":
#         pass
#     else:
#         pub.publish_relay_status(device_id="001", relay_id="4", action_id="011")
#         data = {
#             "actiontime": utctime,
#             "deviceid": "001",
#             "relayid": "4",
#             "actionid": "011",
#         }
#         lu.write_relay_status(data=data)
# else:
#     if light_relay_state[-1] == "0":
#         pass
#     else:
#         pub.publish_relay_status(device_id="001", relay_id="4", action_id="010")
#         data = {
#             "actiontime": utctime,
#             "deviceid": "001",
#             "relayid": "4",
#             "actionid": "010",
#         }
#         lu.write_relay_status(data=data)
