"""
Utility functions for the greenhouse project.
"""
from os import getenv, path

from dotenv import load_dotenv
from pandas import DataFrame, read_sql
from pandas.errors import EmptyDataError
from sqlalchemy import Engine, text
from sqlalchemy.engine import create_engine
from sqlalchemy.exc import SQLAlchemyError


def get_config() -> bool:
    """
    Load environment variables from a .env file.

    Returns:
        bool: True if the .env file was loaded successfully, False otherwise.
    """
    if not path.exists(path=".env"):
        print(".env file not found.")
        return False
    conf: bool = load_dotenv(dotenv_path=".env")
    return conf

get_config()
DB_CONN_STRING: str = getenv(key="DB_CONNECTION_STRING", default="sqlite:///greenhouse.db")


def get_units(units: str) -> None | DataFrame:
    """
    Get the units of measurement from the database.
    Args:
        units (str): The units to get from the database.

    Returns:
        None | DataFrame: The units of measurement from the database.
    """
    engine: Engine = create_engine(url=DB_CONN_STRING,)
    with engine.connect() as conn:
        try:
            data: DataFrame = read_sql(
                sql="""select
                            *
                        from
                            d_measures
                        """,
                        con=conn
            )
        except (SQLAlchemyError, EmptyDataError, ValueError) as e:
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
            data: DataFrame = read_sql(
                sql=f"""select
                            *
                        from
                            {tablename}
                        where
                            deviceid = '001' 
                            and relayid != '4'
                        """, con=conn)
        except (SQLAlchemyError, EmptyDataError, ValueError) as e:
            print("Unable to read greenhouse settings from database!")
            print(e)
            return None
        if data.empty:
            return None
    return data


def write_greenhouse_conditions(data: DataFrame | None) -> bool:
    """
    Write the greenhouse conditions to the database.
    Args:
        data (DataFrame | None): The greenhouse conditions to write to the database. If data is a
            None or data is empty, then it will automatically return False.

    Returns:
        bool: True if the data was written successfully, False otherwise.
    """
    if data is None or data.empty:
        return False
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
        except (SQLAlchemyError, ValueError) as e:
            print(e)
            conn.rollback()
            return False


def reset_greenhouse_conditions() -> bool:
    """
    Reset the greenhouse conditions to the default values.
    """
    return write_greenhouse_conditions(data=read_greenhouse_conditions(default=True))

def revert_greenhouse_conditions() -> bool:
    """
    Revert the greenhouse conditions to the last saved values.
    """
    return write_greenhouse_conditions(data=read_greenhouse_conditions())
