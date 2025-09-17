import pandas as pd
from sqlalchemy import create_engine
from dash import html, callback, Input, Output, dcc
import dash_bootstrap_components as dbc
from datetime import datetime
from conversions import *
from app_device_stats import *
from app_settings import *

def device_info():
    
    engine = create_engine("sqlite:///greenhouse.db", echo=False)
    with engine.connect() as conn:
        device_names = pd.read_sql("""select distinct DEVICE_NAME
                                from
                                    SENSOR_DATA
                                ;""", conn)['DEVICE_NAME'].tolist()
        page_settings = pd.read_sql("""select UNIT, THEME
                                from
                                    SETTING_DATA
                                where
                                    MEASURE_DATE = (select max(MEASURE_DATE) from SETTING_DATA);""", conn).values[0]
        unit=page_settings[0]
        theme=page_settings[1]
        
    device_sel_menu = dbc.Row(
        [
            dcc.Dropdown(
                [item for item in device_names],
                placeholder="Select the device",
                searchable=False,
                clearable=False,
                id="select-device",
                value = device_names[0],
            )
        ],
        
    )
    device_tabs = dbc.Tabs(
            children=
                [
                    dbc.Tab(label="Stats", tab_id="Stats",),
                    dbc.Tab(label="Settings", tab_id="Settings",),
                ],
            id="device-tabs",
            active_tab="Stats",
        )
    device_content = dbc.Container(
        [
            html.Div(id="device-content",className="dbc"),
        ]    
    )
    return html.Div(
        [
            dbc.Row(
                dbc.Col(
                    [
                        html.Hr(),
                        dbc.Row(
                            dbc.Col(device_sel_menu, width=3),
                            justify="start",
                        ),
                        html.Hr(),
                        dbc.Row(
                            dbc.Col(device_tabs),
                            justify="center",
                            ),
                        dbc.Row(
                            dbc.Col(device_content),
                            justify="center",
                            ),
                    ],
                ), justify="center"
            )
        ],
        className="dbc"
    )
    
@callback(
    Output("device-tabs", "active_tab"),
    Input("select-device", "value"),
    Input("device-tabs", "active_tab"),
)
def device_menu_selection(item, tab):
    try:
        engine = create_engine("sqlite:///greenhouse.db", echo=False)
        with engine.connect() as conn:
            conn.execute(f"""update
                                 DEVICE_ON_DISPLAY
                             set
                                 SELECTED_DEVICE = '{item}';""")
    except Exception as e:
        print(e)
    return tab

@callback(
    Output("device-content", "children"),
    Input("device-tabs", "active_tab"),
)
def on_form_change(at):
    if at == "Stats":
        return device_stats()
    elif at == "Settings":
        return settings()
    