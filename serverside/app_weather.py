import pandas as pd
from sqlalchemy import create_engine
from dash import html, dcc, callback, Input, Output, State
import dash_bootstrap_components as dbc
from datetime import datetime, timedelta
from requests import get
from conversions import *
import plotly.graph_objects as go

# Weather Code Description
weather_code_descr = {"Clear sky":"bi bi-sun",
    "Mainly clear":"bi bi-cloud-sun",
    "Partly cloudy":"bi bi-cloud-sun",
    "Overcast":"bi bi-cloud-sun-fill",
    "Fog":"bi bi-cloud-fog",
    "Depositing rime fog":"bi bi-cloud-fog2",
    "Light drizzle":"bi bi-cloud-drizzle",
    "Moderate drizzle":"bi bi-cloud-drizzle",
    "Dense drizzle":"bi bi-cloud-drizzle-fill",
    "Light freezing drizzle":"bi bi-cloud-snow",
    "Dense freezing drizzle":"bi bi-cloud-snow-fill",
    "Slight rain":"bi bi-cloud-rain",
    "Moderate rain":"bi bi-cloud-rain-fill",
    "Heavy rain":"bi bi-cloud-rain-heavy",
    "Light freezing rain":"bi bi-cloud-snow",
    "Heavy freezing rain":"bi bi-cloud-snow-fill",
    "Slight snow fall":"bi bi-snow",
    "Moderate snow fall":"bi bi-snow3",
    "Heavy snow fall":"bi bi-snow2",
    "Snow grains":"bi bi-cloud-snow",
    "Slight rain showers":"bi bi-cloud-drizzle",
    "Moderate rain showers":"bi bi-cloud-rain",
    "Violent rain showers":"bi bi-cloud-rain-heavy",
    "Slight snow showers":"bi bi-cloud-snow",
    "Heavy snow showers":"bi bi-cloud-snow-fill",
    "Slight or moderate thunderstorm":"bi bi-cloud-lightning-rain",
    "Thunderstorm with slight hail":"bi bi-cloud-hail",
    "Thunderstorm with heavy hail":"bi bi-cloud-hail-fill",
}

# Wind Direction
wind_direction = [
    {'Direction':'North',
     'Direction_short':'N',
     'Min': 348.75,
     'Max': 11.25},
    {'Direction':'North-Northeast',
     'Direction_short': 'NNE',
     'Min': 11.25,
     'Max': 33.75},
    {'Direction':'Northeast',
     'Direction_short':'NE',
     'Min': 33.75,
     'Max': 56.25},
    {'Direction':'East-Northeast',
     'Direction_short':'ENE',
     'Min': 56.25,
     'Max': 78.75},
    {'Direction':'East',
     'Direction_short':'E',
     'Min': 78.75,
     'Max': 101.25},
    {'Direction':'East-Southeast',
     'Direction_short':'ESE',
     'Min': 101.25,
     'Max': 123.75},
    {'Direction':'Southeast',
     'Direction_short':'SE',
     'Min': 123.75,
     'Max': 146.25},
    {'Direction':'South-Southeast',
     'Direction_short':'SSE',
     'Min': 146.25,
     'Max': 168.75},
    {'Direction':'South',
     'Direction_short':'S',
     'Min': 168.75,
     'Max': 191.25},
    {'Direction':'South-Southwest',
     'Direction_short':'SSW',
     'Min': 191.25,
     'Max': 213.75},
    {'Direction':'Southwest',
     'Direction_short':'SW',
     'Min': 213.75,
     'Max': 236.25},
    {'Direction':'West-Southwest',
     'Direction_short':'WSW',
     'Min': 236.25,
     'Max': 258.75},
    {'Direction':'West',
     'Direction_short':'W',
     'Min': 258.75,
     'Max': 281.25},
    {'Direction':'West-Northwest',
     'Direction_short':'WNW',
     'Min': 281.25,
     'Max': 303.75},
    {'Direction':'Northwest',
     'Direction_short':'NW',
     'Min': 303.75,
     'Max': 326.25},
    {'Direction':'North-Northwest',
     'Direction_short':'NNW',
     'Min': 326.25,
     'Max': 348.75},
]

def weather():
    
    engine = create_engine("sqlite:///greenhouse.db", echo=False)
    with engine.connect() as conn:
        page_settings = pd.read_sql("""select UNIT, THEME
                                from
                                    SETTING_DATA
                                where
                                    MEASURE_DATE = (select max(MEASURE_DATE) from SETTING_DATA);""", conn).values[0]
        unit=page_settings[0]
        theme=page_settings[1]
        data=pd.read_sql("""select *
                                from
                                    WEATHER_API_DATA
                                where
                                    MEASURE_DATE = (select
                                                        max(MEASURE_DATE)
                                                    from
                                                        WEATHER_API_DATA);""", conn)
        units = pd.read_sql(f"""select * from UNITS where UNIT = '{unit}';""", conn).values[0]
        temp_unit = units[2]
        speed_unit = units[1]
        precip_unit = units[3]
        
        wa_wc = data[['CURRENT_WEATHER_CODE']].values[0][0]
        wa_pic = weather_code_descr[wa_wc]
        
        if unit == "SI":
            current_temp = convert_to_fahrenheit(data[['CURRENT_TEMPERATURE']].values[0][0])
            min_temp = convert_to_fahrenheit(data[['DAILY_TEMPERATURE_MIN']].values[0][0])
            max_temp = convert_to_fahrenheit(data[['DAILY_TEMPERATURE_MAX']].values[0][0])
            precip = convert_to_inches(data[['CURRENT_PRECIPITATION']].values[0][0])
            current_wind_speed = convert_to_mph(data[['CURRENT_WIND_SPEED']].values[0][0])
            max_wind_speed = convert_to_mph(data[['DAILY_WIND_SPEED_MAX']].values[0][0])
            range_low = -40
            range_high = 140
        else:
            current_temp = data[['CURRENT_TEMPERATURE']].values[0][0]
            min_temp = data[['DAILY_TEMPERATURE_MIN']].values[0][0]
            max_temp = data[['DAILY_TEMPERATURE_MAX']].values[0][0]
            precip = data[['CURRENT_PRECIPITATION']].values[0][0]
            current_wind_speed = data[['CURRENT_WIND_SPEED']].values[0][0]
            max_wind_speed = data[['DAILY_WIND_SPEED_MAX']].values[0][0]
            range_low = -40
            range_high = 60
        
        wind_dir = data[['CURRENT_WIND_DIRECTION']].values[0][0]
        for d in wind_direction:
            if d['Min']<=wind_dir<d['Max']:
                wind_dir_descr = f"{d['Direction']} ({d['Direction_short']})"
        
        
    rev_lookup_url = f"https://api.geoapify.com/v1/geocode/reverse?lat={data[['LATITUDE']].values[0][0]}&lon={data[['LONGITUDE']].values[0][0]}&apiKey=117596a26b7d4a159a5d1ed488a997e6"
    headers = {"Accept": "application/json"}
    loc = get(rev_lookup_url, headers=headers)
    try:
        loc = loc.json()['features'][0]['properties']
        try:
            loc = f"{loc['city']}, {loc['state']}, {loc['country']}"
        except:
            try:
                loc = f"{loc['village']}, {loc['state']}, {loc['country']}"
            except:
                try:
                    loc = f"{loc['state']}, {loc['country']}"
                except:
                    loc = "Unknown Location"
    except:
        loc = "Unknown Location"
    
    time_card = dbc.Card(
        [
            dbc.CardHeader("Time", className="text-center"),
            dbc.CardBody(
                    [
                        html.P(f"Current: {datetime.now().replace(microsecond=0)}"),
                        html.P(f"Last measured: {data[['MEASURE_DATE']].values[0][0]}"),
                        html.P(f"{data[['TIMEZONE']].values[0][0]} ({data[['TIMEZONE_ABBR']].values[0][0]})"),
                    ],
                    className="align-content-center"
                )
            ],
            outline=True,
        )
    weather_card = dbc.Card(
        [
            dbc.CardHeader("Weather", className="text-center"),
            dbc.CardBody(
                [
                    html.I(className=wa_pic, style={"font-size": "3rem",}),
                    html.P(wa_wc),        
                ],
            )
        ],
        outline=True,
        className="text-center"
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
                    dbc.Button(id="open-temp-history-weather", children="History", n_clicks=0),
                    dbc.Modal(
                        [
                            dbc.ModalHeader(dbc.ModalTitle("Temperature-History"), close_button=True),
                            dbc.ModalBody(
                                [
                                    dcc.Graph(id="temp-graph-weather"),
                                    dbc.Label("Range"),
                                    dbc.RadioItems(
                                        options=[
                                            {"label": "1 day", "value": "day"},
                                            {"label": "1 week", "value": "week"},
                                            {"label": "1 month", "value": "month"},
                                            {"label": "1 year", "value": "year"},
                                        ],
                                        value="day",
                                        id="temp-modal-filter",
                                        inline=True,
                                    ),
                                ]
                            ),
                            dbc.ModalFooter(
                                dbc.Button(
                                    "Close",
                                    id="close-temp-history-weather",
                                    className="ms-auto",
                                    n_clicks=0,
                                )
                            ),
                        ],
                        id="temp-history-weather-modal",
                        centered=True,
                        size="xl",
                        is_open=False,
                    ),
                    ]
                )
            ]
        )
    hum_figure = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=data[['CURRENT_HUMIDITY']].values[0][0],
            number = {"suffix": f" %"},
            domain={"x": [0,1], 'y':[0,1],},
            title={"text": f"<span style='font-size:0.8em;color:gray'>Precipitation: {precip} {precip_unit}"},
            gauge={
                'axis': {'range': [0, 100],}
                },
            )
        )
    hum_figure.update_layout(template=theme)
    humidity_gauge = dbc.Card(
        [
            dbc.CardBody(
                [
                    dcc.Graph(figure=hum_figure
                            ),
                    dbc.Button(id="open-humidity-history-weather", children="Humidity History", n_clicks=0),
                    dbc.Button(id="open-precipitation-history-weather", children="Precipitation History", n_clicks=0),
                    dbc.Modal(
                        [
                            dbc.ModalHeader(dbc.ModalTitle("Humidity-History"), close_button=True),
                            dbc.ModalBody(
                                [
                                    dcc.Graph(id="humidity-graph-weather"),
                                    dbc.Label("Range"),
                                    dbc.RadioItems(
                                        options=[
                                            {"label": "1 day", "value": "day"},
                                            {"label": "1 week", "value": "week"},
                                            {"label": "1 month", "value": "month"},
                                            {"label": "1 year", "value": "year"},
                                        ],
                                        value="day",
                                        id="humidity-modal-filter",
                                        inline=True,
                                    ),
                                ]
                            ),
                            dbc.ModalFooter(
                                dbc.Button(
                                    "Close",
                                    id="close-humidity-history-weather",
                                    className="ms-auto",
                                    n_clicks=0,
                                )
                            ),
                        ],
                        id="humidity-history-weather-modal",
                        centered=True,
                        size="xl",
                        is_open=False,
                    ),
                    dbc.Modal(
                        [
                            dbc.ModalHeader(dbc.ModalTitle("Precipitation-History"), close_button=True),
                            dbc.ModalBody(
                                [
                                    dcc.Graph(id="precipitation-graph-weather"),
                                    dbc.Label("Range"),
                                    dbc.RadioItems(
                                        options=[
                                            {"label": "1 day", "value": "day"},
                                            {"label": "1 week", "value": "week"},
                                            {"label": "1 month", "value": "month"},
                                            {"label": "1 year", "value": "year"},
                                        ],
                                        value="day",
                                        id="precipitation-modal-filter",
                                        inline=True,
                                    ),
                                ]
                            ),
                            dbc.ModalFooter(
                                dbc.Button(
                                    "Close",
                                    id="close-precipitation-history-weather",
                                    className="ms-auto",
                                    n_clicks=0,
                                )
                            ),
                        ],
                        id="precipitation-history-weather-modal",
                        centered=True,
                        size="xl",
                        is_open=False,
                    ),
                    ]
                )
            ]
        )
    ws_figure = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=current_wind_speed,
            number = {"suffix": f" {speed_unit}"},
            domain={"x": [0,1], 'y':[0,1],},
            title={"text": f"<span style='font-size:0.8em;color:gray'>Direction: {wind_dir_descr}"},
            gauge={
                'axis': {'range': [0, 100],},
                'threshold': {
                    'value': max_wind_speed,
                    'line': {'color': 'lightgreen', 'width': 5}
                    },
                },
            )
        )
    ws_figure.update_layout(template=theme)
    wind_speed_gauge = dbc.Card(
        [
            dbc.CardBody(
                [
                    dcc.Graph(figure=ws_figure
                            ),
                    dbc.Button(id="open-windspeed-history-weather", children="History", n_clicks=0),
                    dbc.Modal(
                        [
                            dbc.ModalHeader(dbc.ModalTitle("Windpseed-History"), close_button=True),
                            dbc.ModalBody(
                                [
                                    dcc.Graph(id="windspeed-graph-weather"),
                                    dbc.Label("Range"),
                                    dbc.RadioItems(
                                        options=[
                                            {"label": "1 day", "value": "day"},
                                            {"label": "1 week", "value": "week"},
                                            {"label": "1 month", "value": "month"},
                                            {"label": "1 year", "value": "year"},
                                        ],
                                        value="day",
                                        id="windspeed-modal-filter",
                                        inline=True,
                                    ),
                                ]
                            ),
                            dbc.ModalFooter(
                                dbc.Button(
                                    "Close",
                                    id="close-windspeed-history-weather",
                                    className="ms-auto",
                                    n_clicks=0,
                                )
                            ),
                        ],
                        id="windpseed-history-weather-modal",
                        centered=True,
                        size="xl",
                        is_open=False,
                    ),
                    ]
                )
            ]
        )
    
    suntime_card = dbc.Card(
        [
            dbc.CardBody(
                [
                    dbc.Row(
                        [
                            dbc.Col(html.I(className="bi bi-sunrise", style={"font-size": "2rem",}), className="justify-content-center align-content-center", width=2),
                            dbc.Col(html.P(f"{data[['SUNRISE_TIME']].values[0][0]}", ), className="justify-content-start align-content-center"),
                        ]
                    ),
                    dbc.Row(
                        [
                            dbc.Col(html.I(className="bi bi-sunset", style={"font-size": "2rem",}), className="justify-content-center align-content-center", width=2),
                            dbc.Col(html.P(f"{data[['SUNSET_TIME']].values[0][0]}",), className="justify-content-start align-content-center"),
                        ]
                    )
                ], 
             )
        ],
        outline=True,
        className="align-content-center"
        )
    
    location_card = dbc.Card(
        [
            dbc.CardBody(
                [
                    dbc.Row(
                        [
                            dbc.Col(html.I(children="my_location", className="material-symbols-rounded", style={"font-size": "2rem",}), className="justify-content-center align-content-center", width=2),
                            dbc.Col(
                                [
                                    html.P(f"{loc}"),
                                    html.P(f"[Latitude: {data[['LATITUDE']].values[0][0]}, Longitude: {data[['LONGITUDE']].values[0][0]}]"),
                                ], className="justify-content-start align-content-center"
                            ),
                        ]
                    ),
                ], 
             )
        ],
        outline=True,
        )
    
    card_grp1 = dbc.CardGroup(
        [
            time_card,weather_card
        ],
    )
    card_grp2 = dbc.CardGroup(
        [
            suntime_card,location_card
        ]
    )
    
    return html.Div(
        [
            html.Hr(),
            card_grp1,
            card_grp2,
            dbc.Accordion(
                [
                    dbc.AccordionItem(
                        temp_gauge, title="Temperature"
                    ),
                    dbc.AccordionItem(
                        humidity_gauge, title="Humidity"
                    ),
                    dbc.AccordionItem(
                        wind_speed_gauge, title="Wind Speed"
                    )
                ]
            ),
        ],
        className="align-content-center"
    )

@callback(
    Output("humidity-history-weather-modal", "is_open"),
    [
        Input("open-humidity-history-weather", "n_clicks"),
        Input("close-humidity-history-weather", "n_clicks"),
    ],
    [State("humidity-history-weather-modal", "is_open")],
)
def get_humidity_history(n1, n2, is_open):
    if n1 or n2:
        return not is_open
    else:
        return is_open

@callback(
    Output("humidity-graph-weather", "figure"),
    Input("humidity-modal-filter", "value"),
)
def get_humidity_history_figure(sel_delta):
    if sel_delta=="week":
        delta=datetime.now().replace(microsecond=0)-timedelta(days=7)
    elif sel_delta=="month":
        delta=datetime.now().replace(microsecond=0)-timedelta(days=31)
    elif sel_delta=="year":
        delta=datetime.now().replace(microsecond=0)-timedelta(days=365)
    else:
        delta=datetime.now().replace(microsecond=0)-timedelta(hours=24)
        
    engine = create_engine("sqlite:///greenhouse.db", echo=False)
    with engine.connect() as conn:
        theme = pd.read_sql("""select THEME
                                from
                                    SETTING_DATA
                                where
                                    MEASURE_DATE = (select max(MEASURE_DATE) from SETTING_DATA);""", conn).values[0][0]
        if sel_delta in ['month', 'year']:
            sql_str = f"""select
                               DATE(MEASURE_DATE) as MEASURE_DATE
                               , ROUND(AVG(CURRENT_HUMIDITY),0) as CURRENT_HUMIDITY
                           from
                               WEATHER_API_DATA
                           where
                               MEASURE_DATE > '{delta}'
                           group by
                               DATE(MEASURE_DATE);"""
        else:
            sql_str = f"""select
                               MEASURE_DATE, CURRENT_HUMIDITY
                           from
                               WEATHER_API_DATA
                           where
                               MEASURE_DATE > '{delta}';"""
        data = pd.read_sql(sql_str, conn)
        fig=go.Figure()
        fig.add_trace(go.Scatter(x=data['MEASURE_DATE'].values, y=data['CURRENT_HUMIDITY'].values, name='Humidity',
                         line=dict(color='firebrick', width=4)))
        fig.update_layout(
                   xaxis_title='Time',
                   yaxis_title=f'Humidity (%)',
                   template=theme)
    return fig


@callback(
    Output("precipitation-history-weather-modal", "is_open"),
    [
        Input("open-precipitation-history-weather", "n_clicks"),
        Input("close-precipitation-history-weather", "n_clicks"),
    ],
    [State("precipitation-history-weather-modal", "is_open")],
)
def get_precip_history(n1, n2, is_open):        
    if n1 or n2:
        return not is_open
    else:
        return is_open
    
@callback(
    Output("precipitation-graph-weather", "figure"),
    Input("precipitation-modal-filter", "value"),
)
def get_precip_history_figure(sel_delta):
    if sel_delta=="week":
        delta=datetime.now().replace(microsecond=0)-timedelta(days=7)
    elif sel_delta=="month":
        delta=datetime.now().replace(microsecond=0)-timedelta(days=31)
    elif sel_delta=="year":
        delta=datetime.now().replace(microsecond=0)-timedelta(days=365)
    else:
        delta=datetime.now().replace(microsecond=0)-timedelta(hours=24)
        
    engine = create_engine("sqlite:///greenhouse.db", echo=False)
    with engine.connect() as conn:
        cur_unit = pd.read_sql(f"""select UNIT from SETTING_DATA
                                   where
                                         MEASURE_DATE = (select
                                                             max(MEASURE_DATE)
                                                         from
                                                             SETTING_DATA
                                                         );""", conn).values[0][0]
        theme = pd.read_sql("""select THEME
                                from
                                    SETTING_DATA
                                where
                                    MEASURE_DATE = (select max(MEASURE_DATE) from SETTING_DATA);""", conn).values[0][0]
        sel_unit = pd.read_sql(f"""select PRECIPITATION from UNITS where UNIT = '{cur_unit}';""", conn).values[0][0]
        if sel_delta in ['month', 'year']:
            sql_str = f"""select
                               DATE(MEASURE_DATE) as MEASURE_DATE
                               , ROUND(AVG(CURRENT_PRECIPITATION),0) as CURRENT_PRECIPITATION
                           from
                               WEATHER_API_DATA
                           where
                               MEASURE_DATE > '{delta}'
                           group by
                               DATE(MEASURE_DATE);"""
        else:
            sql_str = f"""select
                               MEASURE_DATE, CURRENT_PRECIPITATION
                           from
                               WEATHER_API_DATA
                           where
                               MEASURE_DATE > '{delta}';"""
        data = pd.read_sql(sql_str, conn)
        if cur_unit=='SI':
            data['CURRENT_PRECIPITATION']=data['CURRENT_PRECIPITATION'].apply(convert_to_inches)
        
        fig=go.Figure()
        fig.add_trace(go.Scatter(x=data['MEASURE_DATE'].values, y=data['CURRENT_PRECIPITATION'].values, name='Precipitation',
                         line=dict(color='firebrick', width=4)))
        fig.update_layout(
                   xaxis_title='Time',
                   yaxis_title=f'Precipitation ({sel_unit})',
                   template=theme)
    return fig

    
@callback(
    Output("temp-history-weather-modal", "is_open"),
    [
        Input("open-temp-history-weather", "n_clicks"),
        Input("close-temp-history-weather", "n_clicks"),
    ],
    [State("temp-history-weather-modal", "is_open")],
)
def get_temp_history(n1, n2, is_open):
    if n1 or n2:
        return not is_open
    else:
        return is_open

@callback(
    Output("temp-graph-weather", "figure"),
    Input("temp-modal-filter", "value"),
)
def get_temp_history_figure(sel_delta):
    if sel_delta=="week":
        delta=datetime.now().replace(microsecond=0)-timedelta(days=7)
    elif sel_delta=="month":
        delta=datetime.now().replace(microsecond=0)-timedelta(days=31)
    elif sel_delta=="year":
        delta=datetime.now().replace(microsecond=0)-timedelta(days=365)
    else:
        delta=datetime.now().replace(microsecond=0)-timedelta(hours=24)
        
    engine = create_engine("sqlite:///greenhouse.db", echo=False)
    with engine.connect() as conn:
        cur_unit = pd.read_sql(f"""select UNIT from SETTING_DATA
                                   where
                                         MEASURE_DATE = (select
                                                             max(MEASURE_DATE)
                                                         from
                                                             SETTING_DATA
                                                         );""", conn).values[0][0]
        theme = pd.read_sql("""select THEME
                                from
                                    SETTING_DATA
                                where
                                    MEASURE_DATE = (select max(MEASURE_DATE) from SETTING_DATA);""", conn).values[0][0]
        sel_unit = pd.read_sql(f"""select TEMPERATURE from UNITS where UNIT = '{cur_unit}';""", conn).values[0][0]
        if sel_delta in ['month', 'year']:
            sql_str = f"""select
                               DATE(MEASURE_DATE) as MEASURE_DATE
                               , ROUND(AVG(CURRENT_TEMPERATURE),0) as CURRENT_TEMPERATURE
                               , ROUND(AVG(DAILY_TEMPERATURE_MIN),0) as DAILY_TEMPERATURE_MIN
                               , ROUND(AVG(DAILY_TEMPERATURE_MAX),0) as DAILY_TEMPERATURE_MAX
                           from
                               WEATHER_API_DATA
                           where
                               MEASURE_DATE > '{delta}'
                           group by
                               DATE(MEASURE_DATE);"""
        else:
            sql_str = f"""select
                               MEASURE_DATE, CURRENT_TEMPERATURE, DAILY_TEMPERATURE_MIN, DAILY_TEMPERATURE_MAX
                           from
                               WEATHER_API_DATA
                           where
                               MEASURE_DATE > '{delta}';"""
        data = pd.read_sql(sql_str, conn)
        if cur_unit=='SI':
            data['CURRENT_TEMPERATURE']=data['CURRENT_TEMPERATURE'].apply(convert_to_fahrenheit)
            data['DAILY_TEMPERATURE_MIN']=data['DAILY_TEMPERATURE_MIN'].apply(convert_to_fahrenheit)
            data['DAILY_TEMPERATURE_MAX']=data['DAILY_TEMPERATURE_MAX'].apply(convert_to_fahrenheit)
        
        fig=go.Figure()
        fig.add_trace(go.Scatter(x=data['MEASURE_DATE'].values, y=data['DAILY_TEMPERATURE_MAX'].values, name='High',
                         line=dict(color='firebrick', width=4)))
        fig.add_trace(go.Scatter(x=data['MEASURE_DATE'].values, y=data['CURRENT_TEMPERATURE'].values, name = 'Measured',
                                 line=dict(color='lightgreen', width=4)))
        fig.add_trace(go.Scatter(x=data['MEASURE_DATE'].values, y=data['DAILY_TEMPERATURE_MIN'].values, name='Low',
                                 line=dict(color='royalblue', width=4)))
        fig.update_layout(
                   xaxis_title='Time',
                   yaxis_title=f'Temperature ({sel_unit})',
                   template=theme)
    return fig

    
@callback(
    Output("windpseed-history-weather-modal", "is_open"),
    [
        Input("open-windspeed-history-weather", "n_clicks"),
        Input("close-windspeed-history-weather", "n_clicks"),
    ],
    [State("windpseed-history-weather-modal", "is_open")],
)
def get_windspeed_history(n1, n2, is_open):
    if n1 or n2:
        return not is_open
    else:
        return is_open

@callback(
    Output("windspeed-graph-weather", "figure"),
    Input("windspeed-modal-filter", "value"),
)
def get_windspeed_history_figure(sel_delta):
    if sel_delta=="week":
        delta=datetime.now().replace(microsecond=0)-timedelta(days=7)
    elif sel_delta=="month":
        delta=datetime.now().replace(microsecond=0)-timedelta(days=31)
    elif sel_delta=="year":
        delta=datetime.now().replace(microsecond=0)-timedelta(days=365)
    else:
        delta=datetime.now().replace(microsecond=0)-timedelta(hours=24)
        
    engine = create_engine("sqlite:///greenhouse.db", echo=False)
    with engine.connect() as conn:
        cur_unit = pd.read_sql(f"""select UNIT from SETTING_DATA
                                   where
                                         MEASURE_DATE = (select
                                                             max(MEASURE_DATE)
                                                         from
                                                             SETTING_DATA
                                                         );""", conn).values[0][0]
        theme = pd.read_sql("""select THEME
                                from
                                    SETTING_DATA
                                where
                                    MEASURE_DATE = (select max(MEASURE_DATE) from SETTING_DATA);""", conn).values[0][0]
        sel_unit = pd.read_sql(f"""select SPEED from UNITS where UNIT = '{cur_unit}';""", conn).values[0][0]
        if sel_delta in ['month', 'year']:
            sql_str = f"""select
                               DATE(MEASURE_DATE) as MEASURE_DATE
                               , ROUND(AVG(CURRENT_WIND_SPEED),0) as CURRENT_WIND_SPEED
                               , ROUND(AVG(DAILY_WIND_SPEED_MAX),0) as DAILY_WIND_SPEED_MAX
                           from
                               WEATHER_API_DATA
                           where
                               MEASURE_DATE > '{delta}'
                           group by
                               DATE(MEASURE_DATE);"""
        else:
            sql_str = f"""select
                               MEASURE_DATE, CURRENT_WIND_SPEED, DAILY_WIND_SPEED_MAX
                           from
                               WEATHER_API_DATA
                           where
                               MEASURE_DATE > '{delta}';"""
        data = pd.read_sql(sql_str, conn)
        if cur_unit=='SI':
            data['CURRENT_WIND_SPEED']=data['CURRENT_WIND_SPEED'].apply(convert_to_mph)
            data['DAILY_WIND_SPEED_MAX']=data['DAILY_WIND_SPEED_MAX'].apply(convert_to_mph)
        
        fig=go.Figure()
        fig.add_trace(go.Scatter(x=data['MEASURE_DATE'].values, y=data['DAILY_WIND_SPEED_MAX'].values, name='High',
                         line=dict(color='firebrick', width=4)))
        fig.add_trace(go.Scatter(x=data['MEASURE_DATE'].values, y=data['CURRENT_WIND_SPEED'].values, name = 'Measured',
                                 line=dict(color='lightgreen', width=4)))
        fig.update_layout(
                   xaxis_title='Time',
                   yaxis_title=f'Wind Speed ({sel_unit})',
                   template=theme)
        return fig