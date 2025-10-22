"""
Utility functions for the greenhouse project.
"""
from os import getenv, path

from dotenv import load_dotenv
from pandas import DataFrame, read_sql
from pandas.errors import EmptyDataError
from sqlalchemy import Engine, TextClause, text
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


def read_greenhouse_conditions(default: bool = False, conditions_update: bool = False) -> None | DataFrame:
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
                            --and relayid != '4'
                        """, con=conn)
            if conditions_update:
                data = data[data["relayid"]!="4"]
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
    return write_greenhouse_conditions(data=read_greenhouse_conditions(default=True, conditions_update=True))

def revert_greenhouse_conditions() -> bool:
    """
    Revert the greenhouse conditions to the last saved values.
    """
    return write_greenhouse_conditions(data=read_greenhouse_conditions(conditions_update=True))


def read_greenhouse_data() -> None | DataFrame:
    """
    Read the greenhouse data from the database.
    """
    engine: Engine = create_engine(
        url=DB_CONN_STRING,
    )
    with engine.connect() as conn:
        try:
            data: DataFrame = read_sql(
                sql="""select distinct
                            devicename,
                            measurename,
                            g.measureid,
                            measuredatetime,
                            g.value_001
                        from
                            greenhouse_data g
                        join (select
                                deviceid,
                                measureid,
                                max(measuredatetime) maxmeasuredatetime
                            from
                                greenhouse_data
                            group by
                                deviceid,
                                measureid) as gtop
                        on g.deviceid = gtop.deviceid
                        and g.measureid = gtop.measureid
                        and g.measuredatetime = gtop.maxmeasuredatetime
                        join d_devices d
                        on g.deviceid = d.deviceid
                        join d_measures dm
                        on g.measureid = dm.measureid
                        where
                            g.deviceid = '001'
                        group by
                            devicename,
                            g.measureid
                        order by
                            devicename,
                            measurename;
                        """,
                con=conn,
            )
        except (SQLAlchemyError, EmptyDataError, ValueError) as e:
            print("Unable to read greenhouse data from database!")
            print(e)
            return None
        if data.empty:
            return None
    return data

def read_relay_status() -> None | DataFrame:
    """
    Read the relay status from the database.
    """
    engine: Engine = create_engine(
        url=DB_CONN_STRING,
    )
    with engine.connect() as conn:
        try:
            data: DataFrame = read_sql(
                sql="""select distinct
                        devicename,
                        relayname,
                        r.relayid,
                        actionname,
                        r.actionid,
                        r.actiontime
                    from
                        relay_status r
                    join (select
                            deviceid,
                            relayid,
                            max(actiontime) maxactiontime
                        from
                            relay_status
                        group by
                            deviceid,
                            relayid) as rtop
                    on r.deviceid = rtop.deviceid
                    and r.relayid = rtop.relayid
                    and r.actiontime = rtop.maxactiontime
                    join d_devices d
                    on r.deviceid = d.deviceid
                    join d_relays dr
                    on r.relayid = dr.relayid
                    join d_actions a
                    on r.actionid = a.actionid
                    group by
                        devicename,
                        relayname,
                        actionname
                    order by
                        devicename,
                        relayname;""",
                con=conn,
            )
        except (SQLAlchemyError, EmptyDataError, ValueError) as e:
            print("Unable to read relay status data from database!")
            print(e)
            return None
        if data.empty:
            return None
    return data

def write_relay_status(data: dict[str, str | int] | None) -> bool:
    """
    write_relay_status _summary_

    _extended_summary_

    Args:
        data (dict[str, str  |  int] | None): _description_

    Returns:
        bool: _description_
    """
    engine: Engine = create_engine(
        url=DB_CONN_STRING,
    )
    insert_relay_status_text: TextClause = text(
        text="""INSERT INTO relay_status VALUES (
                             :actiontime,
                             :deviceid,
                             :relayid,
                             :actionid
                         );"""
    )
    with engine.connect() as conn:
        try:
            conn.begin()
            conn.execute(statement=insert_relay_status_text, parameters=data)
            conn.commit()
        except (SQLAlchemyError, ValueError) as e:
            print(e)
            conn.rollback()
            return False
    return True
