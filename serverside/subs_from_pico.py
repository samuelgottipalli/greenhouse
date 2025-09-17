import paho.mqtt.subscribe as subscribe
import pandas as pd
from sqlalchemy import create_engine
from datetime import datetime

engine = create_engine("sqlite:///greenhouse.db", echo=False)

hostname = "raspberrypi"
create_sensor_table = """CREATE TABLE IF NOT EXISTS
                    SENSOR_DATA
                        (MEASURE_DATE TEXT PRIMARY KEY ASC DEFAULT CURRENT_TIMESTAMP,
                        DEVICE_NAME TEXT PRIMARY KEY ASC,
                        TEMPERATURE INT,
                        HUMIDITY INT,
                        PHOTORESISTOR_VOLTAGE NUM
                        )"""
create_relaystate_table = """CREATE TABLE IF NOT EXISTS
                    RELAY_STATE_DATA
                        (DEVICE_NAME TEXT PRIMARY KEY ASC,
                        FAN_RELAY INT,
                        FAN_MODE TEXT,
                        HEATER_RELAY INT,
                        HEATER_MODE TEXT,
                        LIGHT_RELAY INT,
                        LIGHT_MODE TEXT,
                        WATER_RELAY INT,
                        WATER_MODE TEXT
                        )"""
create_setting_table = """CREATE TABLE IF NOT EXISTS
                    SETTING_DATA
                        (DEVICE_NAME TEXT PRIMARY KEY ASC,
                        HEATER_ON_TEMP INT,
                        HEATER_OFF_TEMP_DIFF INT,
                        FAN_ON_TEMP INT,
                        FAN_OFF_TEMP_DIFF INT,
                        FAN_ON_HUM INT,
                        FAN_OFF_HUM_DIFF INT,
                        UNIT TEXT,
                        LATITUDE NUM,
                        LONGITUDE NUM,
                        LIGHT_ON_TIME TEXT,
                        LIGHT_OFF_TIME TEXT,
                        PHOTORESISTOR_LIMIT NUM,
                        WATER_ON_TIME TEXT,
                        WATER_OFF_TIME TEXT,
                        THEME TEXT)"""
with engine.connect() as conn:
    conn.execute(create_sensor_table)
    conn.execute(create_relaystate_table)
    conn.execute(create_setting_table)
    
    
insert_sensor_data = """INSERT INTO SENSOR_DATA VALUES (?,?,?,?,?)"""
insert_relay_data = """UPDATE RELAY_STATE_DATA SET (?,?,?,?,?,?,?,?) WHERE DEVICE_NAME = '{devicename}'"""
insert_setting_data = """UPDATE SETTING_DATA VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) WHERE DEVICE_NAME = '{devicename}'"""

while True:
    data = subscribe.simple(["PICOW-1/#"],
                           hostname=hostname,
                           auth={"username":"pi", "password":"pi"},
                           retained=False,
                           msg_count=26)
    cur_time = datetime.now().replace(microsecond=0)
    data = [str(t.payload, "utf-8") for t in data]
    sensor_data = data[:7]
    sensor_data.insert(0, cur_time)
    relay_state = data[7:11]
    relay_state.insert(0, cur_time)
    setting = data[11:]
    setting.insert(0, cur_time)
    print(data)
    print(sensor_data)
    print(relay_state)
    print(setting)
    
#     with engine.connect() as conn:
#         conn.execute(insert_sensor_data, sensor_data)
#         conn.execute(insert_relay_data, relay_state)
#         conn.execute(insert_setting_data, setting)
#         print("Data inserted")
#     
#         print(pd.read_sql_table("sensor_data", conn))
#         print(pd.read_sql_table("relay_state_data", conn))
#         print(pd.read_sql_table("setting_data", conn))
#     
#     data = subscribe.simple("weather_api_data",
#                            hostname=hostname,
#                            auth={"username":"pi", "password":"pi"},
#                            retained=False,
#                            msg_count=1)
#     print(data.payload)