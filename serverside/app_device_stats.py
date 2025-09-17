import pandas as pd
from sqlalchemy import create_engine
from dash import html, dcc, callback, Input, Output, State
import dash_bootstrap_components as dbc
from datetime import datetime, timedelta
from requests import get
from conversions import *
import plotly.graph_objects as go

def device_stats():
    
    engine = create_engine("sqlite:///greenhouse.db", echo=False)
    with engine.connect() as conn:
        device_name = pd.read_sql(f"""select SELECTED_DEVICE from DEVICE_ON_DISPLAY;""", conn).values[0][0]
        page_settings = pd.read_sql(f"""select UNIT, THEME
                                from
                                    SETTING_DATA
                                where
                                    MEASURE_DATE = (select
                                                        max(MEASURE_DATE)
                                                    from
                                                        SETTING_DATA
                                                    where
                                                        DEVICE_NAME = '{device_name}');""", conn).values[0]
        sensor_data=pd.read_sql(f"""select *
                                from
                                    SENSOR_DATA
                                where
                                    DEVICE_NAME = '{device_name}' and
                                    MEASURE_DATE in (select
                                                        max(MEASURE_DATE)
                                                    from
                                                        SENSOR_DATA
                                                    where
                                                        DEVICE_NAME = '{device_name}');""", conn)
        relay_data=pd.read_sql(f"""select *
                                from
                                    RELAY_STATE_DATA
                                where
                                    DEVICE_NAME = '{device_name}' and
                                    MEASURE_DATE = (select
                                                        max(MEASURE_DATE)
                                                    from
                                                        RELAY_STATE_DATA
                                                    where
                                                        DEVICE_NAME = '{device_name}');""", conn)
        
        unit=page_settings[0]
        theme=page_settings[1]
        units = pd.read_sql(f"""select * from UNITS where UNIT = '{unit}';""", conn).values[0]
        device_names = sensor_data[["DEVICE_NAME"]].values
        
    temp_unit = units[2]
    speed_unit = units[1]
    precip_unit = units[3]
    
    if unit == "SI":
        current_temp = convert_to_fahrenheit(sensor_data[['TEMPERATURE']].values[0][0])
        min_temp = convert_to_fahrenheit(sensor_data[['MIN_TEMP']].values[0][0])
        max_temp = convert_to_fahrenheit(sensor_data[['MAX_TEMP']].values[0][0])
        range_low = -40
        range_high = 140
    else:
        current_temp = sensor_data[['TEMPERATURE']].values[0][0]
        min_temp = sensor_data[['MIN_TEMP']].values[0][0]
        max_temp = sensor_data[['MAX_TEMP']].values[0][0]
        range_low = -40
        range_high = 60
    currenttime_card = dbc.Card(
        [
            dbc.CardHeader(
                [
                    html.I(title="Time", className="bi bi-calendar-day", style={"font-size": "2rem",}),
                ],
                className="text-center"
            ),
            dbc.CardBody(
                [
                    html.P(f"Current: {datetime.now().replace(microsecond=0)}"),
                    html.P(f"Last measured: {sensor_data[['MEASURE_DATE']].values[0][0]}")
                ],
                className="align-content-center"
            )
        ],
        outline=True
    )
    relay_card = dbc.Card(
        [
            dbc.CardHeader(
                [
                    html.I(title="Relay Status", className="bi bi-motherboard", style={"font-size": "2rem",})
                ],
                className="text-center"
           ),
            dbc.CardBody(
                [
                    html.P(f"Heater Relay: {'On' if relay_data[['HEATER_RELAY']].values[0][0] == 1 else 'Off'}"),
                    html.P(f"Fan Relay: {'On' if relay_data[['FAN_RELAY']].values[0][0] == 1 else 'Off'}"),
                    html.P(f"Light Relay: {'On' if relay_data[['LIGHT_RELAY']].values[0][0] == 1 else 'Off'}"),
                    html.P(f"Water Relay: {'On' if relay_data[['WATER_RELAY']].values[0][0] == 1 else 'Off'}"),
                ]
             )
        ],
        outline=True,
        )
    temp_figure = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=current_temp,
            domain={"x": [0,1], 'y':[0,1],},
            number = {"suffix": f" {temp_unit}"},
            gauge={
                'axis': {'range': [range_low, range_high],'nticks':10},
                'steps': [{'range': [min_temp, max_temp], 'color': 'cyan', 'thickness': 0.85},],
                },
            )
        )
    temp_figure.update_layout(template=theme)
    temp_gauge = dbc.Card(
        [
            dbc.CardBody(
                [
                    dcc.Graph(figure=temp_figure
                            ),
                    dbc.Button(id="open-temp-history", children="History", n_clicks=0),
                    dbc.Modal(
                        [
                            dbc.ModalHeader(dbc.ModalTitle("Temperature-History"), close_button=True),
                            dbc.ModalBody(dcc.Graph(id="temp-graph")),
                            dbc.ModalFooter(
                                dbc.Button(
                                    "Close",
                                    id="close-temp-history",
                                    className="ms-auto",
                                    n_clicks=0,
                                )
                            ),
                        ],
                        id="temp-history-modal",
                        centered=True,
                        is_open=False,
                    ),
                    ]
                )
            ]
        )
    hum_figure = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=sensor_data[['HUMIDITY']].values[0][0],
            domain={"x": [0,1], 'y':[0,1],},
            number = {"suffix": f" %"},
            gauge={
                'axis': {'range': [0, 100], 'nticks':10},
                'steps': [{'range': [sensor_data[['MIN_HUM']].values[0][0], sensor_data[['MAX_HUM']].values[0][0]], 'color': 'blue', 'thickness': 0.85},],
                },
            )
        )
    hum_figure.update_layout(template=theme)
    hum_gauge = dbc.Card(
        [
            dbc.CardBody(
                [
                    dcc.Graph(figure=hum_figure
                            ),
                    dbc.Button(id="open-hum-history", children="History", n_clicks=0),
                    dbc.Modal(
                        [
                            dbc.ModalHeader(dbc.ModalTitle("Humidity-History"), close_button=True),
                            dbc.ModalBody(dcc.Graph(id="hum-graph")),
                            dbc.ModalFooter(
                                dbc.Button(
                                    "Close",
                                    id="close-hum-history",
                                    className="ms-auto",
                                    n_clicks=0,
                                )
                            ),
                        ],
                        id="hum-history-modal",
                        centered=True,
                        is_open=False,
                    ),
                    ]
                ),
            ]
        )
    
    card_grp1 = dbc.CardGroup(
        [
            currenttime_card,
            relay_card,
        ]
    )
    
    return html.Div(
        [
            card_grp1,
            dbc.Accordion(
                [
                    dbc.AccordionItem(
                        temp_gauge, title="Temperature"
                    ),
                    dbc.AccordionItem(
                        hum_gauge, title="Humidity"
                    ),
                ]
            ),
        ]
    )

@callback(
    [
        Output("temp-history-modal", "is_open"),
        Output("temp-graph", "figure"),
    ],
    [
        Input("open-temp-history", "n_clicks"),
        Input("close-temp-history", "n_clicks"),
    ],
    [State("temp-history-modal", "is_open")],
)
def get_temp_history(n1, n2, is_open):
    engine = create_engine("sqlite:///greenhouse.db", echo=False)
    with engine.connect() as conn:
        device_name = pd.read_sql(f"""select SELECTED_DEVICE from DEVICE_ON_DISPLAY;""", conn).values[0][0]
        cur_unit = pd.read_sql(f"""select UNIT from SETTING_DATA
                                   where
                                         MEASURE_DATE = (select
                                                             max(MEASURE_DATE)
                                                         from
                                                             SETTING_DATA
                                                         where
                                                             DEVICE_NAME='{device_name}');""", conn).values[0][0]
        theme = pd.read_sql("""select THEME
                                from
                                    SETTING_DATA
                                where
                                    MEASURE_DATE = (select max(MEASURE_DATE) from SETTING_DATA);""", conn).values[0][0]
        sel_unit = pd.read_sql(f"""select TEMPERATURE from UNITS where UNIT = '{cur_unit}';""", conn).values[0][0]
        data = pd.read_sql(f"""select
                                   MEASURE_DATE, TEMPERATURE, MIN_TEMP, MAX_TEMP
                               from
                                   SENSOR_DATA
                               where
                                   DEVICE_NAME = '{device_name}' and
                                   MEASURE_DATE > '{datetime.now().replace(microsecond=0)-timedelta(days=30)}';""", conn)
        if cur_unit=='SI':
            data['TEMPERATURE']=data['TEMPERATURE'].apply(convert_to_fahrenheit)
            data['MIN_TEMP']=data['MIN_TEMP'].apply(convert_to_fahrenheit)
            data['MAX_TEMP']=data['MAX_TEMP'].apply(convert_to_fahrenheit)
        
        fig=go.Figure()
        fig.add_trace(go.Scatter(x=data['MEASURE_DATE'].values, y=data['MAX_TEMP'].values, name='High',
                         line=dict(color='firebrick', width=4)))
        fig.add_trace(go.Scatter(x=data['MEASURE_DATE'].values, y=data['TEMPERATURE'].values, name = 'Measured',
                                 line=dict(color='lightgreen', width=4)))
        fig.add_trace(go.Scatter(x=data['MEASURE_DATE'].values, y=data['MIN_TEMP'].values, name='Low',
                                 line=dict(color='royalblue', width=4)))
        fig.update_layout(
                   xaxis_title='Time',
                   yaxis_title=f'Temperature ({sel_unit})',
                   template=theme)
        
    if n1 or n2:
        return not is_open, fig
    else:
        return is_open, fig

@callback(
    [
        Output("hum-history-modal", "is_open"),
        Output("hum-graph", "figure"),
    ],
    [
        Input("open-hum-history", "n_clicks"),
        Input("close-hum-history", "n_clicks"),
    ],
    [State("hum-history-modal", "is_open")],
)
def get_hum_history(n1, n2, is_open):
    engine = create_engine("sqlite:///greenhouse.db", echo=False)
    with engine.connect() as conn:
        device_name = pd.read_sql(f"""select SELECTED_DEVICE from DEVICE_ON_DISPLAY;""", conn).values[0][0]
        theme = pd.read_sql("""select THEME
                                from
                                    SETTING_DATA
                                where
                                    MEASURE_DATE = (select max(MEASURE_DATE) from SETTING_DATA);""", conn).values[0][0]
        data = pd.read_sql(f"""select
                                   MEASURE_DATE, HUMIDITY, MIN_HUM, MAX_HUM
                               from
                                   SENSOR_DATA
                               where
                                   DEVICE_NAME = '{device_name}' and
                                   MEASURE_DATE > '{datetime.now().replace(microsecond=0)-timedelta(days=30)}';""", conn)
        fig=go.Figure()
        fig.add_trace(go.Scatter(x=data['MEASURE_DATE'].values, y=data['MAX_HUM'].values, name='High',
                         line=dict(color='firebrick', width=4)))
        fig.add_trace(go.Scatter(x=data['MEASURE_DATE'].values, y=data['HUMIDITY'].values, name = 'Measured',
                                 line=dict(color='lightgreen', width=4)))
        fig.add_trace(go.Scatter(x=data['MEASURE_DATE'].values, y=data['MIN_HUM'].values, name='Low',
                                 line=dict(color='royalblue', width=4)))
        fig.update_layout(
                   xaxis_title='Time',
                   yaxis_title='Humidity (%)',
                   template=theme)
        
                
    if n1 or n2:
        return not is_open, fig
    else:
        return is_open, fig

