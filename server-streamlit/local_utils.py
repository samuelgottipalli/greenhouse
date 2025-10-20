"""
Utility functions for the greenhouse project.
"""
from dotenv import load_dotenv
from sqlalchemy.engine import create_engine
from sqlalchemy import Engine, text
from pandas import DataFrame, read_sql_query
from os import getenv


def get_config() -> bool:
    """
    Load environment variables from a .env file.

    Returns:
        bool: True if the .env file was loaded successfully, False otherwise.
    """
    from os import path
    if not path.exists(".env"):
        print(".env file not found.")
        return False
    conf: bool = load_dotenv(dotenv_path=".env")
    return conf
get_config()
DB_CONN_STRING: str = getenv("DB_CONNECTION_STRING")
# print(DB_CONN_STRING)


def get_units(units: str) -> None | DataFrame:
    engine: Engine = create_engine(
        url=DB_CONN_STRING,
    )
    with engine.connect() as conn:
        try:
            data: DataFrame = read_sql_query(
                sql="""select
                            *
                        from
                            d_measures
                        """,
                        con=conn
            )
        except Exception as e:
            print("Unable to get units of measurement!")
            print(e)
            return None
    if units == "SI":
        data = data[["measureid", "measurename", "siunit"]]
    else:
        data = data[["measureid", "measurename", "englishunit"]]
    return data


def read_greenhouse_conditions(default: bool = False) -> None | DataFrame:
    """
    Read the greenhouse conditions from the database.
    """
    if default:
        tablename = "relay_conditions_default"
    else:
        tablename = "relay_conditions"
    engine: Engine = create_engine(
        url=DB_CONN_STRING,
    )
    with engine.connect() as conn:
        try:
            data: DataFrame = read_sql_query(
                sql=f"""select
                            *
                        from
                            {tablename}
                        where
                            deviceid = '001' 
                            and relayid != '4'
                        """,
                con=conn,
            )
        except Exception as e:
            print("Unable to read greenhouse settings from database!")
            print(e)
            return None
        if data.empty:
            return None
    return data

def write_greenhouse_conditions(data: DataFrame) -> bool:
    engine: Engine = create_engine(
        url=DB_CONN_STRING,
    )
    with engine.connect() as conn:
        conn.begin()
        try:
            conn.execute(
                statement=text(
                    text="""delete from
                                relay_conditions
                            where
                                deviceid = '001'
                                and relayid != '4'
                            """
                )
            )
            data.to_sql(
                name="relay_conditions", con=conn, if_exists="append", index=False
            )
            conn.commit()
            return True
        except Exception as e:
            print(e)
            conn.rollback()
            return False


def reset_greenhouse_conditions() -> bool:
    return write_greenhouse_conditions(data=read_greenhouse_conditions(default=True))

def revert_greenhouse_conditions() -> bool:
    return write_greenhouse_conditions(data=read_greenhouse_conditions())
