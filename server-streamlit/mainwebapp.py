import streamlit as st

pages = {
    "Reports": [
        st.Page("weather.py", title="Weather Data"),
        st.Page("greenhouse.py", title="Greenhouse Weather"),
    ],
    "Control": [
        st.Page("greenhousecontrol.py", title="Remote Control"),
        # st.Page("trial.py", title="Try it out"),
    ],
    "Settings": [
        st.Page("appsettings.py", title="App Settings"),
        st.Page("greenhousesettings.py", title="Greenhouse Settings"),
        st.Page("about.py", title="About"),
        st.Page("help.py", title="Help"),

    ]
}

pg = st.navigation(pages)
pg.run()
