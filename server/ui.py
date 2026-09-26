"""
Helpers shared by every Streamlit page: page setup and display preferences.

Display preferences live in ``st.session_state`` (per browser session) under
these keys, set on the App Settings page:

* ``units``: "SI" or "US"
* ``date_format``: e.g. "MM/DD/YYYY"
* ``time_format``: "12-hour" or "24-hour"
* ``timezone``: "UTC" or "Local"
* ``timezone_name``: IANA zone used when ``timezone`` is "Local"
"""
from pathlib import Path

import streamlit as st

from core import settings

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
    """Fill in any display preference the session does not have yet."""
    for key, value in PREFERENCE_DEFAULTS.items():
        st.session_state.setdefault(key, value)


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
