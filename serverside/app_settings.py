import pandas as pd
from sqlalchemy import create_engine
from dash import html, callback, Input, Output
import dash_bootstrap_components as dbc
from dash.exceptions import PreventUpdate
from conversions import *

def settings():
    global cur_unit
    engine = create_engine("sqlite:///greenhouse.db", echo=False)
    
    with engine.connect() as conn:
        device_name = pd.read_sql(f"""select SELECTED_DEVICE from DEVICE_ON_DISPLAY;""", conn).values[0][0]
        data = pd.read_sql(f"""select *
                                from
                                    SETTING_DATA
                                where
                                    DEVICE_NAME = '{device_name}' and
                                    MEASURE_DATE = (select
                                                        max(MEASURE_DATE)
                                                    from
                                                        SETTING_DATA
                                                    where
                                                        DEVICE_NAME = '{device_name}');""", conn)
        cur_unit = data[["UNIT"]].values[0][0]
        units = pd.read_sql(f"""select * from UNITS where UNIT = '{cur_unit}';""", conn).values[0]
        temp_unit = units[2]

    if cur_unit == "SI":
        heater_on_temp = convert_to_fahrenheit(data[['HEATER_ON_TEMP']].values[0][0])
        fan_on_temp = convert_to_fahrenheit(data[['FAN_ON_TEMP']].values[0][0])
    else:
        heater_on_temp = data[['HEATER_ON_TEMP']].values[0][0]
        fan_on_temp = data[['FAN_ON_TEMP']].values[0][0]

    
    heater_input = html.Div(
        [
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Row(
                                [
                                    dbc.Col(dbc.Label("Turn on temperature is at", html_for="heater")),
                                    dbc.Col(
                                        [
                                            dbc.Input(id="temp-heater", type="number", step=1, value=heater_on_temp),
                                            dbc.Tooltip("Cannot be blank value", id="temp-heat-tooltip", is_open=False, target="temp-heater", trigger="focus legacy",),
                                        ],
                                        width=3
                                    ),
                                    dbc.Col(dbc.Label(temp_unit, id="temp-unit-heater", html_for="heater"), width=1),
                                ],
                                align="center"
                            ),
                            dbc.Row(
                                [
                                    dbc.Col(dbc.Label("Turn off when temperature is over", html_for="heater")),
                                    dbc.Col(
                                        [
                                            dbc.Input(id="temp-heater_diff", type="number", min=0, max=10, step=1, value=data[['HEATER_OFF_TEMP_DIFF']].values[0][0]),
                                            dbc.Tooltip("Cannot be blank value", id="temp-heat-diff-tooltip", is_open=False, target="temp-heater_diff", trigger="focus legacy",),
                                        ],
                                        width=3
                                    ),
                                    dbc.Col(dbc.Label(temp_unit, id="temp-unit-heater_diff", html_for="heater"), width=1),
                                ],
                                align="center"
                            ),
                        ],
                        width=7
                    ),
                    dbc.Col(dbc.Button("Save", id="heater-settings", n_clicks=0, color="primary"), width=2),
                    dbc.Col(
                        [
                            dbc.Row(dbc.Label("Manual Control", html_for="heater"), align="center"),
                            dbc.Row(
                                html.Span(
                                    [
                                        dbc.Label("Off", html_for="heater-manual"),
                                        dbc.Switch(id="heater-manual", value=True, className="d-inline-block ms-1", persistence=True),
                                        dbc.Label("On", html_for="heater-manual"),
                                    ]
                                ),
                                align="center"
                            )
                        ], width=3
                    )
                ],
                align="center"
            )
        ]
    )

    fan_temp_input = html.Div(
        [
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Row(
                                [
                                    dbc.Col(dbc.Label("Turn on temperature is at", html_for="fan-temp")),
                                    dbc.Col(
                                        [
                                            dbc.Input(id="temp-fan", type="number", step=1, value=fan_on_temp),
                                            dbc.Tooltip("Cannot be blank value", id="temp-fan-tooltip", is_open=False, target="temp-fan", trigger="focus legacy",),
                                        ],
                                        width=3
                                    ),
                                    dbc.Col(dbc.Label(temp_unit, id="temp-unit-fan", html_for="fan-temp"), width=1),
                                ],
                                align="center"
                            ),
                            dbc.Row(
                                [
                                    dbc.Col(dbc.Label("Turn off when temperature is under", html_for="fan-temp")),
                                    dbc.Col(
                                        [
                                            dbc.Input(id="temp-fan_diff", type="number", min=0, max=10, step=1, value=data[['FAN_OFF_TEMP_DIFF']].values[0][0]),
                                            dbc.Tooltip("Cannot be blank value", id="temp-fan-diff-tooltip", is_open=False, target="temp-fan_diff", trigger="focus legacy",),
                                        ],
                                        width=3
                                    ),
                                    dbc.Col(dbc.Label(temp_unit, id="temp-unit-fan_diff", html_for="fan-temp"), width=1),
                                ],
                                align="center"
                            ),
                        ],
                        width=7
                    ),
                    dbc.Col(dbc.Button("Save", id="fan-temp-settings", n_clicks=0, color="primary"), width=2),
                    dbc.Col(
                        [
                            dbc.Row(dbc.Label("Manual Control", html_for="fan"), align="center"),
                            dbc.Row(
                                html.Span(
                                    [
                                        dbc.Label("Off", html_for="fan-manual"),
                                        dbc.Switch(id="fan-manual", value=True, className="d-inline-block ms-1", persistence=True),
                                        dbc.Label("On", html_for="fan-manual"),
                                    ],
                                ), align="center"
                            )
                        ], width=3
                    )
                ],
                align="center"
            ),
        ]
    )
    fan_hum_input = html.Div(
        [
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Row(
                                [
                                    dbc.Col(dbc.Label("Turn on when humidity is at", html_for="fan-humidity")),
                                    dbc.Col(
                                        [
                                            dbc.Input(id="humidity-fan", type="number", min=0, max=100, step=1, value=data[["FAN_ON_HUM"]].values[0][0]),
                                            dbc.Tooltip("Cannot be blank value", id="humidity-fan-tooltip", is_open=False, target="humidity-fan", trigger="focus legacy",),
                                        ],
                                        width=3
                                    ),
                                    dbc.Col(dbc.Label("%", html_for="fan-humidity"), width=1),
                                ],
                                align="center"
                            ),
                            dbc.Row(
                                [
                                    dbc.Col(dbc.Label("Turn off when humidity is under", html_for="fan-humidity")),
                                    dbc.Col(
                                        [
                                            dbc.Input(id="humidity-fan_diff", type="number", min=0, max=10, step=1, value=data[["FAN_OFF_HUM_DIFF"]].values[0][0]),
                                            dbc.Tooltip("Cannot be blank value", id="humidity-fan-diff-tooltip", is_open=False, target="humidity-fan_diff", trigger="focus legacy",),
                                        ],
                                        width=3
                                    ),
                                    dbc.Col(dbc.Label("%", html_for="fan-humidity"), width=1),
                                ],
                                align="center"
                            ),
                        ],
                        width=7
                    ),
                    dbc.Col(dbc.Button("Save", id="fan-hum-settings", n_clicks=0, color="primary"))
                ],
                align="center"
            )
        ]
    )

    loc_input = html.Div(
        [
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Row(
                                [
                                    dbc.Col(dbc.Label("Latitude", html_for="location")),
                                    dbc.Col(
                                        [
                                            dbc.Input(id="latitude", type="number", min=-90, max=90, step=0.01, value=data[["LATITUDE"]].values[0][0]),
                                            dbc.Tooltip("Cannot be blank value", id="latitude-tooltip", is_open=False, target="latitude", trigger="focus legacy",),
                                        ],
                                        width=3
                                    ),
                                    dbc.Col(dbc.Label(" ", html_for="fan-humidity"), width=1),
                                ],
                                align="center"
                            ),
                            dbc.Row(
                                [
                                    dbc.Col(dbc.Label("Longitude", html_for="location")),
                                    dbc.Col(
                                        [
                                            dbc.Input(id="longitude", type="number", min=-180, max=180, step=0.01, value=data[["LONGITUDE"]].values[0][0]),
                                            dbc.Tooltip("Cannot be blank value", id="longitude-tooltip", is_open=False, target="longitude", trigger="focus legacy",),
                                        ],
                                        width=3
                                    ),
                                    dbc.Col(dbc.Label(" ", html_for="fan-humidity"), width=1),
                                ],
                                align="center"
                            ),
                        ],
                        width=7
                    ),
                    dbc.Col(dbc.Button("Save", id="location-settings", n_clicks=0, color="primary"))
                ],
                align="center"
            )
        ]
    )

    light_input = html.Div(
        [
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Row(
                                [
                                    dbc.Col(dbc.Label("Turn on light at", html_for="light")),
                                    dbc.Col(
                                        [
                                            dbc.Input(id="light-on-time", type="text", value=data[["LIGHT_ON_TIME"]].values[0][0], placeholder="HH:MI:SS"),
                                            dbc.Tooltip("Cannot be blank value", id="light-on-time-tooltip", is_open=False, target="light-on-time", trigger="focus legacy",),
                                        ],
                                        width=3
                                    ),
                                    dbc.Col(dbc.Label(" ", html_for="fan-humidity"), width=1),
                                ],
                                align="center"
                            ),
                            dbc.Row(
                                [
                                    dbc.Col(dbc.Label("Turn off light at", html_for="light")),
                                    dbc.Col(
                                        [
                                            dbc.Input(id="light-off-time", type="text", value=data[["LIGHT_OFF_TIME"]].values[0][0], placeholder="HH:MI:SS"),
                                            dbc.Tooltip("Cannot be blank value", id="light-off-time-tooltip", is_open=False, target="light-off-time", trigger="focus legacy",),
                                        ],
                                        width=3
                                    ),
                                    dbc.Col(dbc.Label(" ", html_for="fan-humidity"), width=1),
                                ],
                                align="center"
                            ),
                            dbc.Row(
                                [
                                    dbc.Col(dbc.Label("Photoresistor sensitivity", html_for="light")),
                                    dbc.Col(
                                        [
                                            dbc.Input(id="photoresistor", type="number", min=0, max=10, step=0.1, value=data[["PHOTORESISTOR_LIMIT"]].values[0][0]),
                                            dbc.Tooltip("Cannot be blank value", id="photoresistor-tooltip", is_open=False, target="photoresistor", trigger="focus legacy",),
                                        ],
                                        width=3
                                    ),
                                    dbc.Col(dbc.Label(" ", html_for="fan-humidity"), width=1),
                                ],
                                align="center"
                            ),
                        ],
                        width=7
                    ),
                    dbc.Col(dbc.Button("Save", id="light-settings", n_clicks=0, color="primary"), width=2),
                    dbc.Col(
                        [
                            dbc.Row(dbc.Label("Manual Control", html_for="light"), align="center"),
                            dbc.Row(
                                html.Span(
                                    [
                                        dbc.Label("Off", html_for="light-manual"),
                                        dbc.Switch(id="light-manual", value=True, className="d-inline-block ms-1", persistence=True),
                                        dbc.Label("On", html_for="light-manual"),
                                    ],
                                ), align="center"
                            )
                        ], width=3
                    )
                ],
                align="center"
            )
        ]
    )

    water_input = html.Div(
        [
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Row(
                                [
                                    dbc.Col(dbc.Label("Turn on water at", html_for="water")),
                                    dbc.Col(
                                        [
                                            dbc.Input(id="water-on-time", type="text", value=data[["WATER_ON_TIME"]].values[0][0], placeholder="HH:MI:SS"),
                                            dbc.Tooltip("Cannot be blank value", id="water-on-time-tooltip", is_open=False, target="water-on-time", trigger="focus legacy",),
                                        ],
                                        width=3
                                    ),
                                    dbc.Col(dbc.Label(" ", html_for="fan-humidity"), width=1),
                                ],
                                align="center"
                            ),
                            dbc.Row(
                                [
                                    dbc.Col(dbc.Label("Turn off water at", html_for="water")),
                                    dbc.Col(
                                        [
                                            dbc.Input(id="water-off-time", type="text", value=data[["WATER_OFF_TIME"]].values[0][0], placeholder="HH:MI:SS"),
                                            dbc.Tooltip("Cannot be blank value", id="water-off-time-tooltip", is_open=False, target="water-off-time", trigger="focus legacy",),
                                        ],
                                    width=3
                                    ),
                                    dbc.Col(dbc.Label(" ", html_for="fan-humidity"), width=1),
                                ],
                                align="center"
                            ),
                        ],
                        width=7
                    ),
                    dbc.Col(dbc.Button("Save", id="water-settings", n_clicks=0, color="primary"), width=2),
                    dbc.Col(
                        [
                            dbc.Row(dbc.Label("Manual Control", html_for="water"), align="center"),
                            dbc.Row(
                                html.Span(
                                    [
                                        dbc.Label("Off", html_for="water-manual"),
                                        dbc.Switch(id="water-manual", value=True, className="d-inline-block ms-1", persistence=True),
                                        dbc.Label("On", html_for="water-manual"),
                                    ],
                                ), align="center"
                            )
                        ], width=3
                    )
                ],
                align="center"
            )
        ]
    )
    return dbc.Container(
                        [
                            dbc.Label(device_name, id="device-name", hidden=True),
                            dbc.Row(
                                [
                                    dbc.Col(
                                        [
                                            html.Br(),
                                            dbc.Row(
                                                [
                                                    dbc.Col(dbc.Label("Heater Settings (Temperature)", html_for="heater", width="auto"), width=3),
                                                    dbc.Col(heater_input)
                                                ],
                                                align="center"
                                            ),
                                            html.Hr(),
                                            dbc.Row(
                                                [
                                                    dbc.Col(dbc.Label("Fan Settings (Temperature)", html_for="fan-temp", width="auto"), width=3),
                                                    dbc.Col(fan_temp_input)
                                                ],
                                                align="center"
                                            ),
                                            html.Hr(),
                                            dbc.Row(
                                                [
                                                    dbc.Col(dbc.Label("Fan Settings (Humidity)", html_for="fan-humidity", width="auto"), width=3),
                                                    dbc.Col(fan_hum_input)
                                                ],
                                                align="center"
                                            ),
                                            html.Hr(),
                                            dbc.Row(
                                                [
                                                    dbc.Col(dbc.Label("Light Settings", html_for="light", width="auto"), width=3),
                                                    dbc.Col(light_input)
                                                ],
                                                align="center"
                                            ),
                                            html.Hr(),
                                            dbc.Row(
                                                [
                                                    dbc.Col(dbc.Label("Water Settings", html_for="water", width="auto"), width=3),
                                                    dbc.Col(water_input,)
                                                ],
                                                align="center"
                                            ),
                                            html.Hr(),
                                            dbc.Row(
                                                [
                                                    dbc.Col(dbc.Label("Geo-Location", html_for="location", width="auto"), width=3),
                                                    dbc.Col(loc_input)
                                                ],
                                                align="center"
                                            ),
                                        ]
                                    )
                                ],
                                justify="center",
                                align="center"
                            )
                        ],
                        loading_state={"is_loading": True}
                    )

@callback(
    [
        Output("heater-settings", "color"),
        Output("heater-settings", "n_clicks"),
        Output("temp-heat-tooltip", "is_open"),
        Output("temp-heat-diff-tooltip", "is_open"),
    ],
    [
        Input("temp-heater", "value"),
        Input("temp-heater_diff", "value"),
        Input("heater-settings", "n_clicks"),
    ],
    
)
def on_heater_button_click(temp, temp_diff, n):
    global cur_unit
    if n == 0:
        raise PreventUpdate
    else:
        if not temp and not temp_diff:
            color = "warning"
            return color, 0, True, True
        elif not temp:
            color = "warning"
            return color, 0, True, False
        elif not temp_diff:
            color = "warning"
            return color, 0, False, True
        
        if cur_unit == "SI":
            temp = convert_to_celcius(temp)
        
        try:
            engine = create_engine("sqlite:///greenhouse.db", echo=False)
            with engine.connect() as conn:
                device_name = pd.read_sql(f"""select SELECTED_DEVICE from DEVICE_ON_DISPLAY;""", conn).values[0][0]
                conn.execute(f"""update
                                     SETTING_DATA
                                 set
                                     HEATER_ON_TEMP = {temp},
                                     HEATER_OFF_TEMP_DIFF = {temp_diff}
                                 where
                                     DEVICE_NAME = '{device_name}' and
                                     MEASURE_DATE = (select
                                                         max(MEASURE_DATE)
                                                     from
                                                         SETTING_DATA
                                                     where
                                                         DEVICE_NAME = '{device_name}');""")
            color = "success"
        except Exception as e:
            print(e)
            color = "warning"
        return color, 0, False, False
    
@callback(
    [
        Output("fan-temp-settings", "color"),
        Output("fan-temp-settings", "n_clicks"),
        Output("temp-fan-tooltip", "is_open"),
        Output("temp-fan-diff-tooltip", "is_open"),
    ],
    [
        Input("temp-fan", "value"),
        Input("temp-fan_diff", "value"),
        Input("fan-temp-settings", "n_clicks"),
    ],
)
def on_fantemp_button_click(temp, temp_diff, n):
    global cur_unit
    if n == 0:
        raise PreventUpdate
    else:
        if not temp and not temp_diff:
            color = "warning"
            return color, 0, True, True
        elif not temp:
            color = "warning"
            return color, 0, True, False
        elif not temp_diff:
            color = "warning"
            return color, 0, False, True
        
        if cur_unit == "SI":
            temp = convert_to_celcius(temp)
        try:
            engine = create_engine("sqlite:///greenhouse.db", echo=False)
            with engine.connect() as conn:
                device_name = pd.read_sql(f"""select SELECTED_DEVICE from DEVICE_ON_DISPLAY;""", conn).values[0][0]
                conn.execute(f"""update
                                     SETTING_DATA
                                 set
                                     FAN_ON_TEMP = {temp},
                                     FAN_OFF_TEMP_DIFF = {temp_diff}
                                 where
                                     DEVICE_NAME = '{device_name}' and
                                     MEASURE_DATE = (select 
                                                         max(MEASURE_DATE)
                                                     from
                                                         SETTING_DATA
                                                     where
                                                         DEVICE_NAME = '{device_name}');""")
            print(f"""update
                                     SETTING_DATA
                                 set
                                     FAN_ON_TEMP = {temp},
                                     FAN_OFF_TEMP_DIFF = {temp_diff}
                                 where
                                     DEVICE_NAME = '{device_name}' and
                                     MEASURE_DATE = (select 
                                                         max(MEASURE_DATE)
                                                     from
                                                         SETTING_DATA
                                                     where
                                                         DEVICE_NAME = '{device_name}');""")
            color = "success"
        except Exception as e:
            print(e)
            color = "warning"
        return color, 0, False, False

@callback(
    [
        Output("location-settings", "color"),
        Output("location-settings", "n_clicks"),
        Output("latitude-tooltip", "is_open"),
        Output("longitude-tooltip", "is_open"),
    ],
    [
        Input("latitude", "value"),
        Input("longitude", "value"),
        Input("location-settings", "n_clicks"),
    ],
)
def on_location_button_click(lat, long, n):
    if n == 0:
        raise PreventUpdate
    else:
        if not lat and not long:
            color = "warning"
            return color, 0, True, True
        elif not lat:
            color = "warning"
            return color, 0, True, False
        elif not long:
            color = "warning"
            return color, 0, False, True
        
        try:
            engine = create_engine("sqlite:///greenhouse.db", echo=False)
            with engine.connect() as conn:
                device_name = pd.read_sql(f"""select SELECTED_DEVICE from DEVICE_ON_DISPLAY;""", conn).values[0][0]
                conn.execute(f"""update
                                     SETTING_DATA
                                 set
                                     LATITUDE = {lat},
                                     LONGITUDE = {long}
                                 where
                                     DEVICE_NAME = '{device_name}' and
                                     MEASURE_DATE = (select
                                                         max(MEASURE_DATE)
                                                     from
                                                         SETTING_DATA
                                                     where
                                                         DEVICE_NAME = '{device_name}');""")
            color = "success"
        except Exception as e:
            print(e)
            color = "warning"
        return color, 0, False, False

@callback(
    [
        Output("fan-hum-settings", "color"),
        Output("fan-hum-settings", "n_clicks"),
        Output("humidity-fan-tooltip", "is_open"),
        Output("humidity-fan-diff-tooltip", "is_open"),
    ],
    [
        Input("humidity-fan", "value"),
        Input("humidity-fan_diff", "value"),
        Input("fan-hum-settings", "n_clicks"),
    ],
)
def on_humidity_button_click(hum, hum_diff, n):
    if n == 0:
        raise PreventUpdate
    else:
        if not hum and not hum_diff:
            color = "warning"
            return color, 0, True, True
        elif not hum:
            color = "warning"
            return color, 0, True, False
        elif not hum_diff:
            color = "warning"
            return color, 0, False, True
        
        try:
            engine = create_engine("sqlite:///greenhouse.db", echo=False)
            with engine.connect() as conn:
                device_name = pd.read_sql(f"""select SELECTED_DEVICE from DEVICE_ON_DISPLAY;""", conn).values[0][0]
                conn.execute(f"""update
                                     SETTING_DATA
                                 set
                                     FAN_ON_HUM = {hum},
                                     FAN_OFF_HUM_DIFF = {hum_diff}
                                 where
                                     DEVICE_NAME = '{device_name}' and
                                     MEASURE_DATE = (select
                                                         max(MEASURE_DATE)
                                                     from
                                                         SETTING_DATA
                                                     where
                                                         DEVICE_NAME = '{device_name}');""")
            color = "success"
        except Exception as e:
            print(e)
            color = "warning"
        return color, 0, False, False

@callback(
    [
        Output("light-settings", "color"),
        Output("light-settings", "n_clicks"),
        Output("light-on-time-tooltip", "is_open"),
        Output("light-off-time-tooltip", "is_open"),
        Output("photoresistor-tooltip", "is_open"),
    ],
    [
        Input("light-on-time", "value"),
        Input("light-off-time", "value"),
        Input("photoresistor", "value"),
        Input("light-settings", "n_clicks"),
    ],
)
def on_light_button_click(on, off, pr, n):
    if n == 0:
        raise PreventUpdate
    else:
        if not on and not off and not pr:
            color = "warning"
            return color, 0, True, True, True
        elif not on and not off:
            color = "warning"
            return color, 0, True, True, False
        elif not on and not pr:
            color = "warning"
            return color, 0, True, False, True
        elif not off and not pr:
            color = "warning"
            return color, 0, False, True, True
        elif not on:
            color = "warning"
            return color, 0, True, False, False
        elif not off:
            color = "warning"
            return color, 0, False, True, False
        elif not pr:
            color = "warning"
            return color, 0, False, False, True
        
        try:
            engine = create_engine("sqlite:///greenhouse.db", echo=False)
            with engine.connect() as conn:
                device_name = pd.read_sql(f"""select SELECTED_DEVICE from DEVICE_ON_DISPLAY;""", conn).values[0][0]
                conn.execute(f"""update
                                     SETTING_DATA
                                 set
                                     LIGHT_ON_TIME = '{on}',
                                     LIGHT_OFF_TIME = '{off}',
                                     PHOTORESISTOR_LIMIT = {pr}
                                 where
                                     DEVICE_NAME = '{device_name}' and
                                     MEASURE_DATE = (select
                                                         max(MEASURE_DATE)
                                                     from
                                                         SETTING_DATA
                                                     where
                                                         DEVICE_NAME = '{device_name}');""")
            color = "success"
        except Exception as e:
            print(e)
            color = "warning"
        return color, 0, False, False, False

@callback(
    [
        Output("water-settings", "color"),
        Output("water-settings", "n_clicks"),
        Output("water-on-time-tooltip", "is_open"),
        Output("water-off-time-tooltip", "is_open"),
    ],
    [
        Input("water-on-time", "value"),
        Input("water-off-time", "value"),
        Input("water-settings", "n_clicks"),
    ],
)
def on_water_button_click(on, off, n):
    if n == 0:
        raise PreventUpdate
    else:
        if not on and not off:
            color = "warning"
            return color, 0, True, True
        elif not on:
            color = "warning"
            return color, 0, True, False
        elif not off:
            color = "warning"
            return color, 0, False, True
        
        try:
            engine = create_engine("sqlite:///greenhouse.db", echo=False)
            with engine.connect() as conn:
                device_name = pd.read_sql(f"""select SELECTED_DEVICE from DEVICE_ON_DISPLAY;""", conn).values[0][0]
                conn.execute(f"""update
                                     SETTING_DATA
                                 set
                                     WATER_ON_TIME = '{on}',
                                     WATER_OFF_TIME = '{off}'
                                 where
                                     DEVICE_NAME = '{device_name}' and
                                     MEASURE_DATE = (select
                                                         max(MEASURE_DATE)
                                                     from
                                                         SETTING_DATA
                                                     where
                                                         DEVICE_NAME = '{device_name}');""")
            color = "success"
        except Exception as e:
            print(e)
            color = "warning"
        return color, 0, False, False