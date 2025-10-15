import streamlit as st

pages = {
    "Home": [
        st.Page("home.py", title="Home", url_path="home")
    ],
    "Reports": [
        st.Page(
            "weather.py",
            title="Weather Data",
            url_path="weather",
            
        ),
        st.Page(
            "greenhouse.py",
            title="Greenhouse Weather",
            url_path="greenhouse",
            
        ),
    ],
    "Control": [
        st.Page(
            "greenhousecontrol.py",
            title="Remote Control",
            url_path="control",
            
        ),
    ],
    "Settings": [
        st.Page(
            "appsettings.py",
            title="App Settings",
            url_path="appsettings",
            
        ),
        st.Page(
            "greenhousesettings.py",
            title="Greenhouse Settings",
            url_path="greenhousesettings",
            
        ),
        st.Page(
            "about.py",
            title="About",
            url_path="about",
            
        ),
        st.Page(
            "help.py",
            title="Help",
            url_path="help",
            
        ),
    ],
}

pg = st.navigation(pages)
pg.run()
