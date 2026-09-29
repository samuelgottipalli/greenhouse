"""
Entry point for the Greenhouse Control System web app.

Every page request runs this file first, so the login check here
(``ui.require_login``) protects all pages.

Run from the ``server/`` folder with ``streamlit run app.py``. Five pages,
the larger ones split into tabs (``ui.open_tabs``; the tabs' contents are in
``sections/``):

* **Home**: everything at a glance.
* **Reports**: Greenhouse | Outdoor weather.
* **Analysis**: month by month over the last year (Greenhouse | Outdoor weather).
* **Remote Control**: switch the equipment by hand.
* **Settings**: Display | Greenhouse rules | Controllers.
* **Help**: How to use it | About.
"""
import streamlit as st

from ui import require_login
from version import VERSION

pages = [
    st.Page("views/home.py", title="Home", icon=":material/home:", url_path="home", default=True),
    st.Page("views/reports.py", title="Reports", icon=":material/monitoring:", url_path="reports"),
    st.Page("views/analysis.py", title="Analysis", icon=":material/analytics:", url_path="analysis"),
    st.Page("views/control.py", title="Remote Control", icon=":material/toggle_on:", url_path="control"),
    st.Page("views/settings.py", title="Settings", icon=":material/settings:", url_path="settings"),
    st.Page("views/help.py", title="Help", icon=":material/help:", url_path="help"),
]

if not require_login():
    st.stop()
st.sidebar.caption(f"Greenhouse {VERSION} · [What's new](/help?tab=about)")

st.navigation(pages).run()
