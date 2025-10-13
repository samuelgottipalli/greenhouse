from pytz import utc
import streamlit as st
from pandas import DataFrame
from streamlit.connections.sql_connection import SQLConnection
from datetime import datetime as dtt
from sqlalchemy import text

st.set_page_config(
    page_title="Greenhouse Control Center",
    page_icon="🌦️",
    layout="centered",
)


# @st.fragment()
# @st.cache_data
def get_relay_state_data() -> DataFrame | None:
    """
    Fetch relay state data from the database.

    Args:
        None

    Returns:
        DataFrame | None: Relay state data if successful, None otherwise.
    """
    db_conn: SQLConnection = st.connection("greenhouse", type="sql")
    try:
        data: DataFrame = db_conn.query(
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
                        relayname;"""
        )
        
        if len(data) != 0:
            return data
        else:
            return None
    except Exception:
        return None


# @st.fragment
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

    insert_relay_status_text = text("""INSERT INTO relay_status VALUES (
                             :actiontime,
                             :deviceid,
                             :relayid,
                             :actionid,
                             :reason
                         );""")
    db_conn_insert: SQLConnection = st.connection("greenhouse", type="sql")

    try:
        with db_conn_insert.session as s:
            s.begin()
            s.execute(statement=insert_relay_status_text, params=data)
            s.commit()

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
        st.toast(f"{relay} turned {action} via app", icon=":material/thumb_up:")
        # ppublish(
        #     hostname="raspberrypi",
        #     port=1883,
        #     topic=)
        return None
    except Exception as e:
        st.toast(
            f"""Unable to insert relay status data into DB. Possibly due to a database error.
                    Error: {e}""",
            icon=":material/error:",
        )
        return None


st.title(body="Greenhouse Remote Control")
st.header(body="Control the greenhouse devices remotely.")
with st.expander("ℹ️ About this app", expanded=False):
    st.write("Devices are controlled via MQTT.")
    st.write(
        "Device status may change automatically every 15 minutes based on the latest weather data."
    )
    st.write("Use the toggles below to turn the devices on or off manually.")

relay_state_toast = st.toast("Fetching relay state data...")
df = get_relay_state_data()
if isinstance(df, DataFrame):
    relay_state_toast.toast(
        "Relay state data fetched from DB", icon=":material/thumb_up:"
    )
else:
    relay_state_toast.toast("Error fetching relay state data", icon=":material/error:")


with st.container(border=True):
    st.subheader("Device Status")
    left, right = st.columns(
        [0.3, 0.7],
    )
    left.write("Fan Status:")
    rightleft, rightright = right.columns(2)
    fan_on = rightleft.toggle(
        "Turn Fan On/Off",
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
        label_visibility="hidden",
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
        ("On" if st.session_state.get("2") else "Off"),
        color=("green" if st.session_state.get("2") else "red"),
    )
    left.write("Heater Status:")
    heat_on = rightleft.toggle(
        "Turn Heater On/Off",
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
        label_visibility="hidden",
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
        ("On" if st.session_state.get("3") else "Off"),
        color=("green" if st.session_state.get("3") else "red"),
    )
    left.write("Light Status:")
    light_on = rightleft.toggle(
        "Turn Light On/Off",
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
        label_visibility="hidden",
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
        ("On" if st.session_state.get("4") else "Off"),
        color=("green" if st.session_state.get("4") else "red"),
    )
    left.write("Water Status:")
    water_on = rightleft.toggle(
        "Turn Water On/Off",
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
        label_visibility="hidden",
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
        ("On" if st.session_state.get("1") else "Off"),
        color=("green" if st.session_state.get("1") else "red"),
    )
