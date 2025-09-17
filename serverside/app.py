from dash import Dash, html, Input, Output, clientside_callback, callback
import dash_bootstrap_components as dbc
import time
from random import randint
from app_settings import *
from app_overview import *
from app_weather import *
from app_device_info import *

google_material_css = "https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded"
dbc_css = "https://cdn.jsdelivr.net/gh/AnnMarieW/dash-bootstrap-templates/dbc.min.css"
app = Dash(__name__, external_stylesheets=[dbc.themes.FLATLY, google_material_css, dbc.icons.BOOTSTRAP, dbc_css])
app.config.suppress_callback_exceptions = True

color_mode_switch = html.Span(
    [
        dbc.Label("Dark", html_for="color-mode-switch"),
        dbc.Switch(id="color-mode-switch", value=False, className="d-inline-block ms-1", persistence=True),
        dbc.Label("Light", html_for="color-mode-switch"),
    ]
)
unit_switch = html.Span(
        [
            dbc.Label("SI", html_for="unit-switch"),
            dbc.Switch(id="unit-switch", value=True, className="d-inline-block ms-1", persistence=True),
            dbc.Label("Metric", html_for="unit-switch"),
        ]
    )
app.layout = dbc.Container(
    [
        dbc.Row(
            dbc.Col(
                [
                    html.H1(
                            children="Control Center",
                            style={"textAlign": "center", "color": "green"}
                        ),
                    html.Br(),
                    dbc.Row(
                        [
                            dbc.Col(color_mode_switch,),
                            dbc.Col(unit_switch,),
                        ],
                        className="text-center"
                    ),
                    html.Hr(),
                    dbc.Tabs(
                        children=
                            [
                                dbc.Tab(label="Overview", tab_id="Overview", className="material-symbols-rounded", style={"font-size": "4rem",}),
                                dbc.Tab(label="Device Info", tab_id="Devices",),
                                dbc.Tab(label="Weather Conditions", tab_id="WC",),
                            ],
                        id="main-tabs",
                        active_tab="WC",
                    ),
                    dbc.Spinner(
                        html.Div(id="dashboard-content",className="dbc"),
                        color="success",
                        type="grow",
                        spinner_style={"width": "3rem", "height": "3rem", "verticalAlign": "middle"},
                    ),
                ],
                width=9
            ),
            justify="center"
        )
    ], 
)

@app.callback(
    Output("dashboard-content", "children"),
    [
        Input("main-tabs", "active_tab"),
        Input("unit-switch", "value"),
        Input("color-mode-switch", "value")
    ]
)
def on_form_change(at, unit, theme):
    if unit:
        cur_unit = "METRIC"
    else:
        cur_unit = "SI"
    if theme:
        theme = 'plotly'
    else:
        theme='plotly_dark'
    engine = create_engine("sqlite:///greenhouse.db", echo=False)
    with engine.connect() as conn:
        sel_unit = pd.read_sql(f"""select TEMPERATURE from UNITS where UNIT = '{cur_unit}';""", conn).values[0][0]
        try:
            conn.execute(f"""update
                                 SETTING_DATA
                             set
                                 UNIT = '{cur_unit}',
                                 THEME = '{theme}'
                            where
                                 MEASURE_DATE in (select
                                     max(MEASURE_DATE)
                                 from
                                     SETTING_DATA
                                 group by
                                     DEVICE_NAME);""")
        except Exception as e:
            print(e)
    if at == "Overview":
        return overview()
    elif at == "WC":
        return weather()
    elif at == "Devices":
        return device_info()
            
clientside_callback(
    """ 
    (switchOn) => {
       document.documentElement.setAttribute('data-bs-theme', switchOn ? 'light' : 'dark');  
       return window.dash_clientside.no_update
    }
    """,
    Output("color-mode-switch", "id"),
    Input("color-mode-switch", "value"),
)

if __name__ == '__main__':
    app.run(debug = True, host="localhost", port=8050)