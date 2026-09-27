"""
Helpers shared by every Streamlit page: page setup and display preferences.

Display preferences are chosen on the App Settings page, saved in the
``app_preferences`` table, and loaded into ``st.session_state`` when a browser
session starts, under these keys:

* ``units``: "SI" or "US"
* ``date_format``: e.g. "MM/DD/YYYY"
* ``time_format``: "12-hour" or "24-hour"
* ``timezone``: "UTC" or "Local"
* ``timezone_name``: IANA zone used when ``timezone`` is "Local"
"""
from time import sleep
from pathlib import Path

import streamlit as st

from core import db, settings
from core.auth import verify_password

APP_DIR: Path = Path(__file__).resolve().parent
FAVICON: str = str(APP_DIR / "images" / "favicon.png")
CONTENT_DIR: Path = APP_DIR / "content"

PREFERENCE_DEFAULTS: dict[str, str] = {
    "units": "US",
    "date_format": "MM/DD/YYYY",
    "time_format": "12-hour",
    "timezone": "Local",
    "timezone_name": settings.TIMEZONE,
}


def init_preferences() -> None:
    """
    Fill in display preferences the session does not have yet: stored values
    first, then the defaults. The database is read once per session.
    """
    if all(key in st.session_state for key in PREFERENCE_DEFAULTS):
        return
    stored = db.read_preferences()
    for key, value in PREFERENCE_DEFAULTS.items():
        st.session_state.setdefault(key, stored.get(key, value))


def save_preferences() -> bool:
    """
    Store the session's display preferences for future sessions.

    Returns:
        bool: True if saved.
    """
    return db.save_preferences({key: st.session_state[key] for key in PREFERENCE_DEFAULTS})


def require_login() -> bool:
    """
    Gate the dashboard behind the password in ``APP_PASSWORD_HASH``.

    Called by ``app.py`` before any page runs, so it protects every page.
    Without a configured password the dashboard stays open and the sidebar
    says so.

    Returns:
        bool: True if the visitor may see the dashboard.
    """
    if not settings.APP_PASSWORD_HASH:
        st.sidebar.warning(
            "No dashboard password is set. Run `python -m scripts.set_password`.",
            icon=":material/lock_open:",
        )
        return True
    if st.session_state.get("authenticated"):
        if st.sidebar.button("Log out", icon=":material/logout:"):
            del st.session_state["authenticated"]
            st.rerun()
        return True
    st.title("Greenhouse")
    with st.form("login"):
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")
    if submitted:
        if verify_password(password, settings.APP_PASSWORD_HASH):
            st.session_state["authenticated"] = True
            st.rerun()
        sleep(1)  # slow down guessing
        st.error("Wrong password.")
    return False


def page_setup(title: str, layout: str = "centered") -> None:
    """
    Configure the page, show the logo and make sure preferences exist.

    Call this first on every page.

    Args:
        title (str): Browser tab title.
        layout (str): ``"centered"`` or ``"wide"``.
    """
    st.set_page_config(page_title=title, page_icon=FAVICON, layout=layout)
    st.logo(FAVICON, icon_image=FAVICON, size="large")
    init_preferences()


def display_zone() -> str:
    """
    Return the time zone pages should display times in.

    Returns:
        str: ``"UTC"`` or the chosen IANA zone name.
    """
    if st.session_state["timezone"] == "UTC":
        return "UTC"
    return st.session_state["timezone_name"]


def render_markdown(filename: str, title: str) -> None:
    """
    Render a markdown file from ``content/`` as a page.

    Args:
        filename (str): File name inside ``content/``.
        title (str): Browser tab title.
    """
    page_setup(title)
    st.markdown((CONTENT_DIR / filename).read_text(encoding="utf-8"))
