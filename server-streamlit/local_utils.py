"""
Utility functions for the greenhouse project.
"""
from dotenv import load_dotenv
import streamlit as st
from streamlit.connections.sql_connection import SQLConnection
from pandas import DataFrame

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


def get_units(units: str) -> None | DataFrame:
    conn: SQLConnection = st.connection(name="greenhouse", type="sql")
    try:
        data: DataFrame = conn.query(
            sql="""select
                        *
                    from
                        d_measures
                    """,
        )
    except Exception as e:
        st.toast(
            f"Unable to get units of measurement! Error: {e}", icon=":material/error:"
        )
        return None

    if units == "SI":
        data = data[["measureid", "measurename", "siunit"]]
    else:
        data = data[["measureid", "measurename", "englishunit"]]
    return data
