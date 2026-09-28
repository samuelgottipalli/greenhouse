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
import streamlit.components.v1 as components

from core import db, settings
from core.auth import REMEMBER_DAYS, login_token_valid, make_login_token, verify_password

AUTH_COOKIE: str = "greenhouse_auth"
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

    Streamlit forgets a session when the page is reloaded, so a successful
    login also stores a signed token in a browser cookie (``AUTH_COOKIE``;
    see ``core.auth``). It lasts ``REMEMBER_DAYS`` with *Keep me logged in*,
    otherwise until the browser closes. *Log out* deletes it.

    Returns:
        bool: True if the visitor may see the dashboard.
    """
    if not settings.APP_PASSWORD_HASH:
        st.sidebar.warning(
            "No dashboard password is set. Run `python -m scripts.set_password`.",
            icon=":material/lock_open:",
        )
        return True
    if not st.session_state.get("authenticated") and not st.session_state.get("logged_out"):
        if login_token_valid(request_cookie(AUTH_COOKIE), settings.APP_PASSWORD_HASH):
            st.session_state["authenticated"] = True
    if st.session_state.get("authenticated"):
        pending = st.session_state.pop("set_login_cookie", None)
        if pending:
            write_cookie(AUTH_COOKIE, *pending)
        if st.sidebar.button("Log out", icon=":material/logout:"):
            del st.session_state["authenticated"]
            st.session_state["logged_out"] = True
            st.rerun()
        return True
    if st.session_state.get("logged_out"):
        write_cookie(AUTH_COOKIE, "", 0)
    st.title("Greenhouse")
    with st.form("login"):
        password = st.text_input("Password", type="password")
        remember = st.checkbox("Keep me logged in on this device", value=True,
                               help=f"For {REMEMBER_DAYS} days. Otherwise until the browser is closed.")
        submitted = st.form_submit_button("Log in")
    if submitted:
        if verify_password(password, settings.APP_PASSWORD_HASH):
            st.session_state["authenticated"] = True
            st.session_state.pop("logged_out", None)
            days = REMEMBER_DAYS if remember else 1
            st.session_state["set_login_cookie"] = (
                make_login_token(settings.APP_PASSWORD_HASH, days), days * 86400 if remember else None)
            st.rerun()
        sleep(1)  # slow down guessing
        st.error("Wrong password.")
    return False


def request_cookie(name: str) -> str | None:
    """
    Read a cookie the browser sent with this session.

    Args:
        name (str): Cookie name.

    Returns:
        str | None: Its value, or None.
    """
    try:
        return st.context.cookies.get(name)
    except Exception:  # no browser (tests, bare mode)
        return None


def cookie_script(name: str, value: str, max_age: int | None) -> str:
    """
    JavaScript that sets (or, with ``max_age`` 0, deletes) a cookie for the dashboard.

    Args:
        name (str): Cookie name.
        value (str): Value (letters, digits and ``.`` only).
        max_age (int | None): Lifetime in seconds; None for a browser-session cookie.

    Returns:
        str: A ``<script>`` element.
    """
    lifetime = "" if max_age is None else f"; Max-Age={int(max_age)}"
    cookie = f"{name}={value}; Path=/; SameSite=Strict{lifetime}"
    return ("<script>try{window.parent.document.cookie=" + repr(cookie) +
            "}catch(e){document.cookie=" + repr(cookie) + "}</script>")


def write_cookie(name: str, value: str, max_age: int | None) -> None:
    """
    Set a cookie in the visitor's browser (Streamlit can only read them itself).

    Args:
        name (str): Cookie name.
        value (str): Value.
        max_age (int | None): Lifetime in seconds; 0 deletes it; None lasts
            until the browser is closed.
    """
    components.html(cookie_script(name, value, max_age), height=0)


def current_device() -> int:
    """
    Return the controller the dashboard is showing.

    Returns:
        int: Device ID chosen in the sidebar (``DEVICE_ID`` until one is chosen).
    """
    return st.session_state.get("device_id", settings.DEVICE_ID)


def device_selector() -> None:
    """
    Offer a controller picker in the sidebar when more than one is registered.

    The choice is kept in ``st.session_state["device_id"]`` and used by every
    page through :func:`current_device`.
    """
    devices = db.list_devices() or {}
    if current_device() not in devices and devices:
        st.session_state["device_id"] = next(iter(devices))
    if len(devices) < 2:
        return
    ids = list(devices)
    st.session_state["device_id"] = st.sidebar.selectbox(
        "Controller",
        ids,
        index=ids.index(current_device()),
        format_func=lambda device_id: f"{devices[device_id]} (#{device_id})",
    )


def page_setup(title: str, layout: str = "centered") -> None:
    """
    Configure the page, show the logo, make sure preferences exist and show
    the controller picker.

    Call this first on every page.

    Args:
        title (str): Browser tab title.
        layout (str): ``"centered"`` or ``"wide"``.
    """
    st.set_page_config(page_title=title, page_icon=FAVICON, layout=layout)
    st.logo(FAVICON, icon_image=FAVICON, size="large")
    init_preferences()
    device_selector()


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
