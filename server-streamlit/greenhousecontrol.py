from requests import get
import streamlit as st
from pandas import DataFrame
from streamlit.connections.sql_connection import SQLConnection
from datetime import datetime as dtt

st.set_page_config(
    page_title="Greenhouse Control Center",
    page_icon="🌦️",
    layout="centered",
)


@st.fragment()
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
        data: DataFrame = db_conn.query(sql="""select distinct 
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
        return data
    except Exception as e:
        st.error(
            f"Unable to fetch relay state data from DB. Possibly due to a database error. Error: {e}"
        )
        return None

@st.fragment()
def insert_relay_status(data: dict[str, str|int]) -> bool | None:
    """
    Insert relay status data into the database.
    Args:
        data (dict): Relay status data to insert.
    Returns:
        bool: True if the data was inserted successfully, False otherwise.
    """
    db_conn: SQLConnection = st.connection("greenhouse", type="sql")
    if not data or (isinstance(data, dict) and len(data) == 0):
        st.toast("No data to load to DB", icon=":material/warning:")
        return None
    from sqlalchemy import text
    insert_relay_status = text("""INSERT INTO relay_status VALUES (
                             :actiontime,
                             :deviceid,
                             :relayid,
                             :actionid,
                             :reason
                         );""")
    try:
        with db_conn.session as session:
            session.execute(statement=insert_relay_status, params=data)
            session.commit()
            df = get_relay_state_data()
            st.session_state.df = df
        st.toast("Relay status data inserted into DB", icon=":material/check:", )
        return True
    except Exception as e:
        st.toast(
            f"Unable to insert relay status data into DB. Possibly due to a database error. Error: {e}",
            icon=":material/error:"
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

with st.status("Fetching relay state data...", expanded=False) as df_stat:
    df = get_relay_state_data()
    if isinstance(df, DataFrame):
        st.dataframe(df)
        df_stat.update(label="Relay state data fetched from DB", state="complete")
    else:
        df_stat.update(label="Error fetching relay state data", state="error")


with st.container(border=True):
    st.subheader("Device Status")
    left, right = st.columns(
        [0.3, 0.7],
    )
    left.write("Fan Status:")
    rightleft, rightright = right.columns(2)
    rightleft.toggle(
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
                "actiontime": dtt.now().strftime("%Y-%m-%d %H:%M:%S"),
                "deviceid": "001",
                "relayid": '2',
                "actionid": '021' if st.session_state.get("2", False) else '020',
                "reason": "Manual toggle via Streamlit app"
            }
        ],
    )
    rightright.badge(
        (
            "On"
            if isinstance(df, DataFrame)
            and "on"
            in df[
                (df["relayname"].str.lower() == "fan")
                & (df["devicename"].str.lower() == "picow1")
            ]
            .iloc[0]["actionname"]
            .lower()
            else "Off"
        ),
        color=(
            "green"
            if isinstance(df, DataFrame)
            and "on"
            in df[
                (df["relayname"].str.lower() == "fan")
                & (df["devicename"].str.lower() == "picow1")
            ]
            .iloc[0]["actionname"]
            .lower()
            else "red"
        ),
    )
    left.write("Heater Status:")
    rightleft.toggle(
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
    )
    rightright.badge(
        (
            "On"
            if isinstance(df, DataFrame)
            and "on"
            in df[
                (df["relayname"].str.lower() == "heater")
                & (df["devicename"].str.lower() == "picow1")
            ]
            .iloc[0]["actionname"]
            .lower()
            else "Off"
        ),
        color=(
            "green"
            if isinstance(df, DataFrame)
            and "on"
            in df[
                (df["relayname"].str.lower() == "heater")
                & (df["devicename"].str.lower() == "picow1")
            ]
            .iloc[0]["actionname"]
            .lower()
            else "red"
        ),
    )
    left.write("Light Status:")
    rightleft.toggle(
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
    )
    rightright.badge(
        (
            "On"
            if isinstance(df, DataFrame)
            and "on"
            in df[
                (df["relayname"].str.lower() == "light")
                & (df["devicename"].str.lower() == "picow1")
            ]
            .iloc[0]["actionname"]
            .lower()
            else "Off"
        ),
        color=(
            "green"
            if isinstance(df, DataFrame)
            and "on"
            in df[
                (df["relayname"].str.lower() == "light")
                & (df["devicename"].str.lower() == "picow1")
            ]
            .iloc[0]["actionname"]
            .lower()
            else "red"
        ),
    )
    left.write("Water Status:")
    rightleft.toggle(
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
    )
    rightright.badge(
        (
            "On"
            if isinstance(df, DataFrame)
            and "on"
            in df[
                (df["relayname"].str.lower() == "water")
                & (df["devicename"].str.lower() == "picow1")
            ]
            .iloc[0]["actionname"]
            .lower()
            else "Off"
        ),
        color=(
            "green"
            if isinstance(df, DataFrame)
            and "on"
            in df[
                (df["relayname"].str.lower() == "water")
                & (df["devicename"].str.lower() == "picow1")
            ]
            .iloc[0]["actionname"]
            .lower()
            else "red"
        ),
    )
