from paho.mqtt import client as mqtt_client
from pandas import read_sql
from sqlalchemy import create_engine
from datetime import datetime

from time import sleep

def get_weather_data():
    engine = create_engine("sqlite:///greenhouse.db", echo=False)
    with engine.connect() as conn:
        data = read_sql("""select CURRENT_TEMPERATURE,
                                CURRENT_HUMIDITY,
                                CURRENT_PRECIPITATION,
                                CURRENT_WEATHER_CODE,
                                CURRENT_WIND_SPEED
                            from
                                WEATHER_API_DATA
                            where
                                MEASURE_DATE = (select max(MEASURE_DATE) from WEATHER_API_DATA);""", conn)
        data.columns = data.columns.str.replace("CURRENT_", "")
        return data.to_dict('records')

def get_settings_data():
    engine = create_engine("sqlite:///greenhouse.db", echo=False)
    with engine.connect() as conn:
        data = read_sql("""select *
                            from
                                SETTING_DATA
                            where
                                MEASURE_DATE = (select max(MEASURE_DATE) from SETTING_DATA);""", conn)
#         data.columns = data.columns.str.replace("CURRENT_", "")
        return data.to_dict('records')

def get_units():
    engine = create_engine("sqlite:///greenhouse.db", echo=False)
    with engine.connect() as conn:
        data = read_sql("""select *
                            from
                                units
                            );""", conn)
        data.columns = data.columns.str.replace("CURRENT_", "")
        return data.to_dict('records')

def get_relay_state_data():
    engine = create_engine("sqlite:///greenhouse.db", echo=False)
    with engine.connect() as conn:
        data = read_sql("""select *
                            from
                                RELAY_STATE_DATA
                            where
                                MEASURE_DATE = (select max(MEASURE_DATE) from RELAY_STATE_DATA);""", conn)
#         data.columns = data.columns.str.replace("CURRENT_", "")
        return data.to_dict('records')


hostname = "raspberrypi"
port = 1883
topic = "weather_api_data"
pi_mqtt_client_id = "PI-SERVER"
mqtt_username = "pi"
mqtt_password = "pi"

def connect_mqtt():
    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            print("Connected to MQTT Broker.")
        else:
            print("Failed to connect to MQTT Broker")
    
    client = mqtt_client.Client(pi_mqtt_client_id)
    client.username_pw_set(mqtt_username, mqtt_password)
    client.on_connect = on_connect
    client.connect(hostname, port)
    return client


def publish(client):
    while True:
        try:
            msg1 = get_weather_data()
            msg2 = get_settings_data()
            msg3 = get_units()
            msg4 = get_relay_state_data()
            result = client.publish("WEATHER-API/TEMPERATURE", str(msg1[0]["TEMPERATURE"]))
            result = client.publish("WEATHER-API/HUMIDITY", str(msg1[0]["HUMIDITY"]))
            result = client.publish("WEATHER-API/PRECIPITATION", str(msg1[0]["PRECIPITATION"]))
            result = client.publish("WEATHER-API/WEATHER_CODE", msg1[0]["WEATHER_CODE"])
            result = client.publish("WEATHER-API/WIND_SPEED", str(msg1[0]["WIND_SPEED"]))
            sleep(10)
            print(f"published {msg}")
        except Exception as e:
            print(e)

client = connect_mqtt()
client.loop_start()

publish(client,msg)
client.loop_stop()
client.disconnect()