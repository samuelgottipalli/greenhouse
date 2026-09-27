"""
Entry point for the Greenhouse Control System web app.

Every page request runs this file first, so the login check here
(``ui.require_login``) protects all pages.

Run from the ``server/`` folder with ``streamlit run app.py``. Defines the
sidebar navigation and runs whichever page the user selects. Pages live in
``views/``; About and Help render markdown from ``content/``.
"""
import streamlit as st

from ui import render_markdown, require_login


def about_page() -> None:
    """Render ``content/about.md``."""
    render_markdown("about.md", "About")


def help_page() -> None:
    """Render ``content/help.md``."""
    render_markdown("help.md", "Help")


pages = {
    "Home": [
        st.Page("views/home.py", title="Home", url_path="home"),
    ],
    "Reports": [
        st.Page("views/weather.py", title="Weather Data", url_path="weather"),
        st.Page("views/indoor.py", title="Greenhouse Weather", url_path="greenhouse"),
    ],
    "Control": [
        st.Page("views/control.py", title="Remote Control", url_path="control"),
    ],
    "Settings": [
        st.Page("views/app_settings.py", title="App Settings", url_path="appsettings"),
        st.Page("views/greenhouse_settings.py", title="Greenhouse Settings", url_path="greenhousesettings"),
        st.Page("views/controllers.py", title="Controllers", url_path="controllers"),
        st.Page(about_page, title="About", url_path="about"),
        st.Page(help_page, title="Help", url_path="help"),
    ],
}

if not require_login():
    st.stop()

st.navigation(pages).run()
