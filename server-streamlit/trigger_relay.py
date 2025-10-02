from paho.mqtt import client as mqtt_client
from pandas import read_sql
from sqlalchemy import create_engine, text
from datetime import datetime
from os import getenv
from time import sleep

import local_utils as lu
lu.get_config()

def get_weather_data():
    db_path = getenv("DB_PATH")
    if not db_path:
        print("Missing DB_PATH environment variable. Check .env file.")
        return None
    conn_str = getenv("DB_CONNECTION_STRING").format(DB_PATH=db_path)
    if not conn_str:
        print("Missing DB_CONNECTION_STRING environment variable. Check .env file.")
        return None
    engine = create_engine(conn_str, echo=False)
    with engine.connect() as conn:
        data = read_sql(
            """select *
                            from
                                weather_data
                            where
                                MEASURE_DATE = (select max(MEASURE_DATE) from weather_data);""",
            conn,
        )
        return data.to_dict("records")
# print(get_weather_data())

def publish_relay_status():
    pass

data = {
    "actiontime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "deviceid": '001',
    "relayid": '4',
    "actionid": '010',
    "reason": "Test relay action",
}
def log_relay_status(data: dict[str, str|int] | None) -> bool | None:
    db_path: str | None = getenv("DB_PATH")
    if not db_path:
        print("Missing DB_PATH environment variable. Check .env file.")
        return None
    conn_str: str | None = getenv("DB_CONNECTION_STRING").format(DB_PATH=db_path)
    if not conn_str:
        print("Missing DB_CONNECTION_STRING environment variable. Check .env file.")
        return None
    if not data or (isinstance(data, dict) and len(data) == 0):
        print("No data to load to DB")
        return None
    insert_relay_status = """INSERT INTO relay_status VALUES (
                             :actiontime,
                             :deviceid,
                             :relayid,
                             :actionid,
                             :reason
                         )"""
    engine = create_engine(conn_str, echo=False)
    try:
        with engine.connect() as conn:
            conn.begin()
            try:
                conn.execute(text(insert_relay_status), data)
                conn.commit()
                print("Relay status data inserted into DB")
            except Exception as e:
                conn.rollback()
                print(
                    f"Unable to insert relay status data into DB. Possible issue with the data format or constraints. Error: {e}"
                )
                return None
    except Exception as e:
        print(
            f"Unable to insert relay status data into DB. Possibly due to a database error. Error: {e}"
        )
        return None
    return True
print(log_relay_status(data))

def get_settings_data():
    engine = create_engine("sqlite:///greenhouse.db", echo=False)
    with engine.connect() as conn:
        data = read_sql(
            """select *
                            from
                                SETTING_DATA
                            where
                                MEASURE_DATE = (select max(MEASURE_DATE) from SETTING_DATA);""",
            conn,
        )
        #         data.columns = data.columns.str.replace("CURRENT_", "")
        return data.to_dict("records")


def get_units():
    engine = create_engine("sqlite:///greenhouse.db", echo=False)
    with engine.connect() as conn:
        data = read_sql(
            """select *
                            from
                                units
                            );""",
            conn,
        )
        data.columns = data.columns.str.replace("CURRENT_", "")
        return data.to_dict("records")


def get_relay_state_data():
    engine = create_engine("sqlite:///greenhouse.db", echo=False)
    with engine.connect() as conn:
        data = read_sql(
            """select *
                            from
                                RELAY_STATE_DATA
                            where
                                MEASURE_DATE = (select max(MEASURE_DATE) from RELAY_STATE_DATA);""",
            conn,
        )
        #         data.columns = data.columns.str.replace("CURRENT_", "")
        return data.to_dict("records")


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
            result = client.publish(
                "WEATHER-API/TEMPERATURE", str(msg1[0]["TEMPERATURE"])
            )
            result = client.publish("WEATHER-API/HUMIDITY", str(msg1[0]["HUMIDITY"]))
            result = client.publish(
                "WEATHER-API/PRECIPITATION", str(msg1[0]["PRECIPITATION"])
            )
            result = client.publish("WEATHER-API/WEATHER_CODE", msg1[0]["WEATHER_CODE"])
            result = client.publish(
                "WEATHER-API/WIND_SPEED", str(msg1[0]["WIND_SPEED"])
            )
            sleep(10)
            print(f"published {msg}")
        except Exception as e:
            print(e)


# client = connect_mqtt()
# client.loop_start()

# publish(client, msg)
# client.loop_stop()
# client.disconnect()
