from requests import get
from pprint import pprint
from sqlalchemy import create_engine
from datetime import datetime
import pandas as pd

# Weather Code Description
weather_code_descr = {0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow fall",
    73: "Moderate snow fall",
    75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Slight or moderate thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}

create_weather_table = """CREATE TABLE IF NOT EXISTS
                    WEATHER_API_DATA
                        (LATITUDE NUM,
                        LONGITUDE NUM,
                        TIMEZONE TEXT,
                        TIMEZONE_ABBR TEXT,
                        MEASURE_DATE TEXT PRIMARY KEY ASC DEFAULT CURRENT_TIMESTAMP,
                        CURRENT_TEMPERATURE INT,
                        CURRENT_HUMIDITY INT,
                        CURRENT_PRECIPITATION INT,
                        CURRENT_WEATHER_CODE TEXT,
                        CURRENT_WIND_SPEED INT,
                        CURRENT_WIND_DIRECTION INT,
                        SUNRISE_TIME TEXT,
                        SUNSET_TIME TEXT,
                        )"""
insert_weather_data = """INSERT INTO WEATHER_API_DATA VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""

engine = create_engine("sqlite:///greenhouse.db", echo=False)
with engine.connect() as conn:
    conn.execute(create_weather_table)
while True:
    if (datetime.now().minute == 0 or datetime.now().minute % 15 == 0) and datetime.now().second == 0: #
        with engine.connect() as conn:
            coord = pd.read_sql("select latitude, longitude from setting_data where measure_date=(select max(MEASURE_DATE) from setting_data)", conn)
            if isinstance(coord, pd.DataFrame) and len(coord) > 0:
                LAT = coord.values[0][0]
                LONG = coord.values[0][1]
        #         print(LAT, LONG)
        LAT = 39.5349
        LONG = -119.7527
        try:
            response = get(f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LONG}&current=temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m,wind_direction_10m&daily=weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset,wind_speed_10m_max&timezone=America%2FLos_Angeles&forecast_days=1")
        except Exception:
            print("Unable to get data from weather API. Check network, API access key, API online status.")
            continue
        weather_data = response.json()
        weather_data = [round(weather_data["latitude"],2),
                     round(weather_data["longitude"],2),
                     weather_data["timezone"],
                     weather_data["timezone_abbreviation"],
                     datetime.strptime(weather_data["current"]["time"], '%Y-%m-%dT%H:%M'),
                     round(weather_data["current"]["temperature_2m"],0),
                     round(weather_data["current"]["relative_humidity_2m"],0),
                     round(weather_data["current"]["precipitation"],0),
                     weather_code_descr.get(weather_data["current"]["weather_code"], 'Undefined'),
                     round(weather_data["current"]["wind_speed_10m"],0),
                     weather_data["current"]["wind_direction_10m"],
                     weather_code_descr.get(weather_data["daily"]["weather_code"][0], 'Undefined'),
                     round(weather_data["daily"]["temperature_2m_max"][0],0),
                     round(weather_data["daily"]["temperature_2m_min"][0],0),
                     round(weather_data["daily"]["wind_speed_10m_max"][0],0),
                     datetime.strptime(weather_data["daily"]["sunrise"][0], '%Y-%m-%dT%H:%M'),
                     datetime.strptime(weather_data["daily"]["sunset"][0], '%Y-%m-%dT%H:%M'),
                     weather_data["current_units"]["temperature_2m"],
                     weather_data["current_units"]["relative_humidity_2m"],
                     weather_data["current_units"]["precipitation"],
                     weather_data["current_units"]["wind_speed_10m"],
                     weather_data["current_units"]["wind_direction_10m"],
                     ]
#         print(weather_data)
        try:
            with engine.connect() as conn:
                conn.execute(insert_weather_data, weather_data)
        except Exception:
            print("Unable to insert weather API data into DB. Check DB availability, storage space and any other possible issues.")
            continue