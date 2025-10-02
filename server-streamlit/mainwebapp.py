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
}

pg = st.navigation(pages)
pg.run()