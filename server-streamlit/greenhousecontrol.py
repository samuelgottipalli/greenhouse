from datetime import datetime as dtt
from os import getenv

import local_utils as lu
import streamlit as st
from pandas import DataFrame, read_sql
from pub_to_pico import publish_relay_status
from pytz import utc
from sqlalchemy import Engine, text
from sqlalchemy.engine import create_engine
from streamlit.connections.sql_connection import SQLConnection
from streamlit.delta_generator import DeltaGenerator

lu.get_config()
DB_CONN_STRING: str = getenv(
    key="DB_CONNECTION_STRING", default="sqlite:///greenhouse.db"
)
st.set_page_config(
    page_title="Greenhouse Control",
    page_icon=r"images\favicon.png",
    layout="centered",
)
st.logo(r"images\favicon.png", icon_image=r"images\favicon.png", size="large")


# @st.fragment()
def get_relay_state_data() -> DataFrame | None:
    """
    Fetch relay state data from the database.

    Args:
        None

    Returns:
        DataFrame | None: Relay state data if successful, None otherwise.
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
                        reason,
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
                        actionname,
                        reason
                    order by
                        devicename,
                        relayname;""",
                con=conn,
            )

            if len(data) != 0:
                return data
            return None
        except Exception:
            return None


def insert_relay_status(data: dict[str, str | int] | None) -> None:
    """
    Insert relay status data into the database.
    Args:
        data (dict): Relay status data to insert.
    Returns:
        bool: True if the data was inserted successfully, False otherwise.
    """
    if not data or len(data) == 0:
        st.toast("No data to load to DB", icon=":material/warning:")
        return None

    if data["relayid"] == "1":
        relay = "Water"
    elif data["relayid"] == "2":
        relay = "Fan"
    elif data["relayid"] == "3":
        relay = "Heater"
    elif data["relayid"] == "4":
        relay = "Light"
    else:
        relay = "Unknown"

    if data["actionid"] == "020":
        action = "Off"
    elif data["actionid"] == "021":
        action = "On"
    else:
        action = "Unknown"
    insert_relay_status_text = text(
        """INSERT INTO relay_status VALUES (
                             :actiontime,
                             :deviceid,
                             :relayid,
                             :actionid,
                             :reason
                         );"""
    )
    db_conn_insert: SQLConnection = st.connection("greenhouse", type="sql")

    try:
        with db_conn_insert.session as s:
            s.begin()
            s.execute(statement=insert_relay_status_text, params=data)
            st.toast(
                body=f"{relay} turned {action} via app", icon=":material/thumb_up:"
            )
            try:
                publish_relay_status(
                    device_id=data["deviceid"],
                    relay_id=data["relayid"],
                    action_id=data["actionid"],
                )
                st.toast(
                    body=f"{relay} status '{action}' published via MQTT",
                    icon=":material/published_with_changes:",
                )
            except Exception as e:
                st.toast(
                    body=f"""Unable to publish relay status to MQTT. Error: {e}""",
                    icon=":material/error:",
                )
            s.commit()

    except Exception as e:
        st.toast(
            f"""Unable to insert relay status data into DB. Possibly due to a database error.
                    Error: {e}""",
            icon=":material/error:",
        )
        # return None


def load_page(df: DataFrame | None) -> None:
    """ """
    if isinstance(df, DataFrame):
        relay_state_toast.toast(
            body="Relay state data fetched from DB", icon=":material/check_circle:"
        )
    else:
        relay_state_toast.toast(
            "Error fetching relay state data", icon=":material/error:"
        )

    with st.container(border=True):
        st.subheader(body="Device Status")
        left, right = st.columns(
            [0.3, 0.7],
        )
        left.write("Fan Status:")
        rightleft, rightright = right.columns(2)
        rightleft.toggle(
            label="Turn Fan On/Off",
            value=(
                True
                if isinstance(df, DataFrame)
                and "on"
                in df[
                    (df["relayname"].str.lower() == "fan")
                    & (df["devicename"].str.lower() == "picow1")
                ]
                .iloc[0]["actionname"]
                .lower()
                else False
            ),
            key="2",
            help="Toggle to turn the fan on or off",
            label_visibility="collapsed",
            on_change=insert_relay_status,
            args=[
                {
                    "actiontime": dtt.now(tz=utc).strftime("%Y-%m-%d %H:%M:%S"),
                    "deviceid": "001",
                    "relayid": "2",
                    "actionid": "020" if st.session_state.get("2") else "021",
                    "reason": f"""Manual {"off" if st.session_state.get("2") else "on"} via app""",
                }
            ],
        )
        rightright.badge(
            label=("On" if st.session_state.get("2") else "Off"),
            color=("green" if st.session_state.get("2") else "red"),
        )
        left.write("Heater Status:")
        rightleft.toggle(
            label="Turn Heater On/Off",
            value=(
                True
                if isinstance(df, DataFrame)
                and "on"
                in df[
                    (df["relayname"].str.lower() == "heater")
                    & (df["devicename"].str.lower() == "picow1")
                ]
                .iloc[0]["actionname"]
                .lower()
                else False
            ),
            key="3",
            help="Toggle to turn the heater on or off",
            label_visibility="collapsed",
            on_change=insert_relay_status,
            args=[
                {
                    "actiontime": dtt.now(tz=utc).strftime("%Y-%m-%d %H:%M:%S"),
                    "deviceid": "001",
                    "relayid": "3",
                    "actionid": "020" if st.session_state.get("3") else "021",
                    "reason": f"""Manual {"off" if st.session_state.get("3") else "on"} via app""",
                }
            ],
        )
        rightright.badge(
            label=("On" if st.session_state.get("3") else "Off"),
            color=("green" if st.session_state.get("3") else "red"),
        )
        left.write("Light Status:")
        rightleft.toggle(
            label="Turn Light On/Off",
            value=(
                True
                if isinstance(df, DataFrame)
                and "on"
                in df[
                    (df["relayname"].str.lower() == "light")
                    & (df["devicename"].str.lower() == "picow1")
                ]
                .iloc[0]["actionname"]
                .lower()
                else False
            ),
            key="4",
            help="Toggle to turn the light on or off",
            label_visibility="collapsed",
            on_change=insert_relay_status,
            args=[
                {
                    "actiontime": dtt.now(tz=utc).strftime("%Y-%m-%d %H:%M:%S"),
                    "deviceid": "001",
                    "relayid": "4",
                    "actionid": "020" if st.session_state.get("4") else "021",
                    "reason": f"""Manual {"off" if st.session_state.get("4") else "on"} via app""",
                }
            ],
        )
        rightright.badge(
            label=("On" if st.session_state.get("4") else "Off"),
            color=("green" if st.session_state.get("4") else "red"),
        )
        left.write("Water Status:")
        rightleft.toggle(
            label="Turn Water On/Off",
            value=(
                True
                if isinstance(df, DataFrame)
                and "on"
                in df[
                    (df["relayname"].str.lower() == "water")
                    & (df["devicename"].str.lower() == "picow1")
                ]
                .iloc[0]["actionname"]
                .lower()
                else False
            ),
            key="1",
            help="Toggle to turn the water on or off",
            label_visibility="collapsed",
            on_change=insert_relay_status,
            args=[
                {
                    "actiontime": dtt.now(tz=utc).strftime("%Y-%m-%d %H:%M:%S"),
                    "deviceid": "001",
                    "relayid": "1",
                    "actionid": "020" if st.session_state.get("1") else "021",
                    "reason": f"""Manual {"off" if st.session_state.get("1") else "on"} via app""",
                }
            ],
        )
        rightright.badge(
            label=("On" if st.session_state.get("1") else "Off"),
            color=("green" if st.session_state.get("1") else "red"),
        )


st.title(body="Greenhouse Remote Control")
st.header(body="Control the greenhouse devices remotely.")
with st.expander("ℹ️ About this app", expanded=False):
    st.write("Devices are controlled via MQTT.")
    st.write(
        "Device status may change automatically every 15 minutes based on the latest weather data."
    )
    st.write("Use the toggles below to turn the devices on or off manually.")

relay_state_toast: DeltaGenerator = st.toast("Fetching relay state data...")
data: DataFrame | None = get_relay_state_data()
load_page(data)
