import pandas as pd
from sqlalchemy import create_engine
from dash import html, dcc
import dash_bootstrap_components as dbc
from datetime import datetime
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

def overview():
    engine = create_engine("sqlite:///greenhouse.db", echo=False)
    with engine.connect() as conn:
        ghdata=pd.read_sql("""select *
                                from
                                    SENSOR_DATA
                                where
                                    MEASURE_DATE = (select
                                                        max(MEASURE_DATE)
                                                    from
                                                        SENSOR_DATA);""", conn)
        
        wadata=pd.read_sql("""select *
                                from
                                    WEATHER_API_DATA
                                where
                                    MEASURE_DATE = (select
                                                        max(MEASURE_DATE)
                                                    from
                                                        WEATHER_API_DATA);""", conn)
        page_settings = pd.read_sql("""select UNIT, THEME
                                from
                                    SETTING_DATA
                                where
                                    MEASURE_DATE = (select max(MEASURE_DATE) from SETTING_DATA);""", conn).values[0]
        unit=page_settings[0]
        theme=page_settings[1]
        units = pd.read_sql(f"""select * from UNITS where UNIT = '{unit}';""", conn).values[0]
        
    temp_unit = units[2]
    speed_unit = units[1]
    precip_unit = units[3]
    
    wa_wc = wadata[['CURRENT_WEATHER_CODE']].values[0][0]
    wa_pic = weather_code_descr[wa_wc]
    
    if unit == "SI":
        current_gh_temp = convert_to_fahrenheit(ghdata[['TEMPERATURE']].values[0][0])
        min_temp = convert_to_fahrenheit(ghdata[['MIN_TEMP']].values[0][0])
        max_temp = convert_to_fahrenheit(ghdata[['MAX_TEMP']].values[0][0])
        current_wa_temp = convert_to_fahrenheit(wadata[['CURRENT_TEMPERATURE']].values[0][0])
        min_wa_temp = convert_to_fahrenheit(wadata[['DAILY_TEMPERATURE_MIN']].values[0][0])
        max_wa_temp = convert_to_fahrenheit(wadata[['DAILY_TEMPERATURE_MAX']].values[0][0])
        range_low = -40
        range_high = 140
    else:
        current_gh_temp = ghdata[['TEMPERATURE']].values[0][0]
        min_temp = ghdata[['MIN_TEMP']].values[0][0]
        max_temp = ghdata[['MAX_TEMP']].values[0][0]
        current_wa_temp = wadata[['CURRENT_TEMPERATURE']].values[0][0]
        min_wa_temp = wadata[['DAILY_TEMPERATURE_MIN']].values[0][0]
        max_wa_temp = wadata[['DAILY_TEMPERATURE_MAX']].values[0][0]
        range_low = -40
        range_high = 60
    time_card = dbc.Card(
        [
            dbc.CardHeader("Time", className="text-center"),
            dbc.CardBody(
                    [
                        html.P(f"Current: {datetime.now().replace(microsecond=0)}"),
                        html.P(f"Last measured: {ghdata[['MEASURE_DATE']].values[0][0]}")
                    ],
                    className="align-content-center"
                )
            ],
            outline=True,
        )
    wa_currentweather_card = dbc.Card(
        [
            dbc.CardHeader("Weather", className="text-center"),
            dbc.CardBody(
                [
                    html.I(className=wa_pic, style={"font-size": "3rem",}),
                    html.H5(wa_wc),        
                ],
            )
        ],
        outline=True,
        className="text-center"
    )
    
    temp_figure = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=current_gh_temp,
            domain={"x": [0,1], 'y':[0,1],},
            title={"text": f"Temperature ({temp_unit})"},
            gauge={
                'axis': {'range': [range_low, range_high],'nticks':10},
                'steps': [
                    {'range': [min_wa_temp, max_wa_temp], 'color': 'blue', 'thickness': 0.85},
                    {'range': [min_temp, max_temp], 'color': 'cyan', 'thickness': 0.75},
                    ],
                'threshold': {
                    'value': current_wa_temp,
                    'line': {'color': 'lightgreen', 'width': 5}
                    },
                },
            ),
        )
    temp_figure.update_layout(template=theme)
    temp_gauge = dbc.Card(
        [
            dbc.CardBody(
                [
                    dcc.Graph(
                        figure=temp_figure
                        )
                    ]
                )
            ]
        )
    hum_figure = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=ghdata[['HUMIDITY']].values[0][0],
            domain={"x": [0,1], 'y':[0,1],},
            title={"text": f"Humidity (%)"},
            gauge={
                'axis': {'range': [0, 100], 'nticks':10},
                'steps': [
                    {'range': [ghdata[['MIN_HUM']].values[0][0], ghdata[['MAX_HUM']].values[0][0]], 'color': 'blue', 'thickness': 0.85},
#                                 {'range': [wadata[['MIN_HUM']].values[0][0], wadata[['MAX_HUM']].values[0][0]], 'color': 'blue', 'thickness': 0.85},
                    ],
                'threshold': {
                    'value': wadata[['CURRENT_HUMIDITY']].values[0][0],
                    'line': {'color': 'lightgreen', 'width': 5}
                    },
                },
            ),
        )
    hum_figure.update_layout(template=theme)
    hum_gauge = dbc.Card(
        [
            dbc.CardBody(
                [
                    dcc.Graph(
                        figure=hum_figure
                        )
                    ]
                )
            ]
        )
    
    
    card_grp1 = dbc.CardGroup([time_card, wa_currentweather_card])
            
    return dbc.Container(
                    dbc.Col(
                        [
                            html.Br(),
                            dbc.Row(
                                [
                                    dbc.Col(card_grp1),
                                ],
                                justify="center"
                            ),
                            html.Br(),
                            dbc.Row(
                                [
                                    temp_gauge,
                                    hum_gauge
                                ],
                                justify="center"
                            ),
                            ]
                        ),
                    className="dbc"
                    )
                
