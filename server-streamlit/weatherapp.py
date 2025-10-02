from os import getenv

from dotenv import load_dotenv
from requests import get
from sqlalchemy import create_engine, text


def get_config() -> None:
    conf = load_dotenv(".env")


def fetch_weather() -> dict[str, str|int|float|dict[str, str|int|float|list[str]]] | None:
    weatherurl: str|None = getenv("WEATHER_API")
    lat: str|None = getenv("LATITUDE")
    long: str|None = getenv("LONGITUDE")
    if not weatherurl or not lat or not long:
        print("Missing environment variables. Check .env file.")
        return None
    weatherurl = weatherurl.format(LATITUDE=lat, LONGITUDE=long)
    try:
        response = get(weatherurl)
    except Exception:
        print("Unable to get data from weather API. Check network, API access key, API online status.")
        return None
    weather_data = response.json()
    return weather_data

def clean_data(data: dict[str, str|int|float|dict[str, str|int|float|list[str]]] | None) -> dict[str, str|int|float] | None:
    if not data or (isinstance(data, dict) and len(data) == 0):
        print("No data to clean")
        return None
    data_list = {
        "LATITUDE": str(data["latitude"]),
        "LONGITUDE": str(data["longitude"]),
        "TIMEZONE": data["timezone"],
        "MEASURE_DATE": (data["current"]["time"]).replace("T", " ")+":00",
        "ELEVATION": data["elevation"],
        "TEMPERATURE": data["current"]["temperature"],
        "APPARENT_TEMPERATURE": data["current"]["apparent_temperature"],
        "RELATIVE_HUMIDITY": data["current"]["relative_humidity_2m"],
        "PRECIPITATION": data["current"]["precipitation"],
        "RAIN": data["current"]["rain"],
        "SNOWFALL": data["current"]["snowfall"],
        "SHOWERS": data["current"]["showers"],
        "WEATHER_CODE": data["current"]["weather_code"],
        "WIND_SPEED": data["current"]["wind_speed_10m"],
        "WIND_DIRECTION": data["current"]["wind_direction_10m"],
        "SUNRISE_TIME": (data["daily"]["sunrise"][0]).replace("T", " ")+":00",
        "SUNSET_TIME": (data["daily"]["sunset"][0]).replace("T", " ")+":00",
    }
    return data_list

def load_to_db(data: dict[str, str|int|float] | None) -> bool | None:
    db_path = getenv("DB_PATH")
    if not db_path:
        print("Missing DB_PATH environment variable. Check .env file.")
        return None
    conn_str = getenv("DB_CONNECTION_STRING").format(DB_PATH=db_path)
    if not conn_str:
        print("Missing DB_CONNECTION_STRING environment variable. Check .env file.")
        return None
    if not data or (isinstance(data, dict) and len(data) == 0):
        print("No data to load to DB")
        return None
    insert_weather_data = """INSERT INTO weather_data VALUES (
                             :LATITUDE,
                             :LONGITUDE,
                             :TIMEZONE,
                             :MEASURE_DATE,
                             :ELEVATION,
                             :TEMPERATURE,
                             :APPARENT_TEMPERATURE,
                             :RELATIVE_HUMIDITY,
                             :PRECIPITATION,
                             :RAIN,
                             :SNOWFALL,
                             :SHOWERS,
                             :WEATHER_CODE,
                             :WIND_SPEED,
                             :WIND_DIRECTION,
                             :SUNRISE_TIME,
                             :SUNSET_TIME
                         )"""
    engine = create_engine(conn_str, echo=False)
    try:
        with engine.connect() as conn:
            conn.begin()
            try:
                conn.execute(text(insert_weather_data), data)
                conn.commit()
                print("Weather API data inserted into DB")
            except Exception as e:
                conn.rollback()
                print(f"Unable to insert weather API data into DB. Possible issue with the data format or constraints. Error: {e}")
                return None
    except Exception as e:
        print(f"Unable to insert weather API data into DB. Possibly due to a database error. Error: {e}")
        return None
    return True


get_config()
data = fetch_weather()
data = clean_data(data)
print(load_to_db(data))