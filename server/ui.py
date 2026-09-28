"""
Helpers shared by every Streamlit page: page setup and display preferences.

Display preferences are chosen on Settings › Display, saved in the
``app_preferences`` table, and loaded into ``st.session_state`` when a browser
session starts, under these keys:

* ``units``: "SI" or "US"
* ``date_format``: e.g. "MM/DD/YYYY"
* ``time_format``: "12-hour" or "24-hour"
* ``timezone``: "UTC" or "Local"
* ``timezone_name``: IANA zone used when ``timezone`` is "Local"
* ``theme``: "Use system setting", "Light" or "Dark"
* ``page_width``: "Automatic" (each page's own), "Wide" or "Centered"
* ``auto_refresh``: "On" or "Off": pages reload themselves when new data arrives

Streamlit's own menu (with its theme and wide-mode settings) is hidden
(``.streamlit/config.toml``); the colour scheme (Settings › Display) is applied by writing the
browser setting Streamlit reads at start-up (:func:`apply_theme`).
"""
import json
from datetime import date, datetime, timedelta
from time import sleep
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st
import streamlit.components.v1 as components

from core import db, settings
from core.auth import REMEMBER_DAYS, login_token_valid, make_login_token, verify_password
from core.timeutil import parse_utc_timestamp

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
    "theme": "Use system setting",
    "page_width": "Automatic",
    "auto_refresh": "On",
}
THEMES: list[str] = ["Use system setting", "Light", "Dark"]
PAGE_WIDTHS: list[str] = ["Automatic", "Wide", "Centered"]
# URL paths of the pages (app.py). Streamlit keeps the chosen theme per path.
PAGE_PATHS: list[str] = ["", "home", "reports", "control", "settings", "help"]
REFRESH_EVERY = timedelta(seconds=30)
DATE_FORMATS: dict[str, str] = {"DD/MM/YYYY": "%d/%m/%Y", "MM/DD/YYYY": "%m/%d/%Y", "YYYY/MM/DD": "%Y/%m/%d"}


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
        layout (str): The page's own width, ``"centered"`` or ``"wide"``; the
            *Page width* preference can override it.
    """
    init_preferences()
    st.set_page_config(page_title=title, page_icon=FAVICON,
                       layout=effective_layout(layout, st.session_state["page_width"]))
    st.logo(FAVICON, icon_image=FAVICON, size="large")
    apply_theme(st.session_state["theme"])
    device_selector()


def effective_layout(page_layout: str, page_width: str) -> str:
    """
    The layout a page should use.

    Args:
        page_layout (str): The page's own choice.
        page_width (str): The *Page width* preference.

    Returns:
        str: ``"wide"`` or ``"centered"``.
    """
    return {"Wide": "wide", "Centered": "centered"}.get(page_width, page_layout)


def theme_script(theme: str, paths: list[str] = PAGE_PATHS) -> str:
    """
    JavaScript that makes the browser use a colour scheme.

    Streamlit reads the scheme at start-up from local storage, one entry per
    page path (``stActiveTheme-<path>-v1``). The script writes the entry for
    every page (removing it for *Use system setting*) and reloads the page
    if the current one changed.

    Args:
        theme (str): One of ``THEMES``.
        paths (list[str]): Page URL paths.

    Returns:
        str: A ``<script>`` element.
    """
    wanted = json.dumps({"name": theme}, separators=(",", ":")) if theme in ("Light", "Dark") else None  # as Streamlit writes it
    keys = json.dumps([f"stActiveTheme-/{path}-v1" for path in paths])
    return ("<script>try{const w=window.parent,s=w.localStorage,want=" + json.dumps(wanted) + ";"
            "const keys=new Set(" + keys + ");const here='stActiveTheme-'+w.location.pathname+'-v1';"
            "keys.add(here);let reload=false;"
            "for(const k of keys){if(s.getItem(k)!==want){if(k===here)reload=true;"
            "if(want===null)s.removeItem(k);else s.setItem(k,want);}}"
            "if(reload)w.location.reload();}catch(e){}</script>")


def apply_theme(theme: str) -> None:
    """
    Apply the colour scheme preference, once per session and whenever it changes.

    Args:
        theme (str): One of ``THEMES``.
    """
    if st.session_state.get("_applied_theme") == theme:
        return
    st.session_state["_applied_theme"] = theme
    components.html(theme_script(theme), height=0)


def data_changed(key: str, version: str | None, state=None) -> bool:
    """
    Remember a data fingerprint and tell whether it differs from last time.

    Args:
        key (str): Which page is asking.
        version (str | None): Output of ``db.data_version`` (None = unknown).
        state (dict | None): Where to remember it (default ``st.session_state``).

    Returns:
        bool: True if there was an earlier fingerprint and this one differs.
    """
    state = st.session_state if state is None else state
    if version is None:
        return False
    seen = state.get(key)
    state[key] = version
    return seen is not None and seen != version


def auto_refresh(key: str, parts: tuple[str, ...] = ("device", "relays", "weather", "alerts"),
                 every: timedelta = REFRESH_EVERY) -> None:
    """
    Reload the page when new data arrives (if the *Auto-refresh* preference is on).

    A fragment checks ``db.data_version`` every ``every`` (one tiny query)
    and reruns the whole page only when it changed.

    Args:
        key (str): Page name, so each page tracks its own fingerprint.
        parts (tuple[str, ...]): Which data the page shows (see ``db.data_version``).
        every (timedelta): How often to check.
    """
    if st.session_state.get("auto_refresh", "On") != "On":
        return
    state_key = f"_data_version_{key}"

    @st.fragment(run_every=every)
    def watch():
        if data_changed(state_key, db.data_version(current_device(), parts)):
            st.rerun(scope="app")

    watch()


def display_zone() -> str:
    """
    Return the time zone pages should display times in.

    Returns:
        str: ``"UTC"`` or the chosen IANA zone name.
    """
    if st.session_state["timezone"] == "UTC":
        return "UTC"
    return st.session_state["timezone_name"]


def date_pattern(date_format: str) -> str:
    """The ``strftime`` pattern for a date format preference, e.g. "MM/DD/YYYY"."""
    return DATE_FORMATS.get(date_format, "%A, %d %B %Y")


def time_pattern(time_format: str) -> str:
    """The ``strftime`` pattern for a time format preference ("12-hour" or "24-hour")."""
    return "%I:%M %p" if time_format == "12-hour" else "%H:%M"


def moment_text(moment: datetime, today: date, date_format: str, time_format: str) -> str:
    """
    A time for "last updated" lines: just the time today, the date and time otherwise.

    Args:
        moment (datetime): The moment, in the display zone.
        today (date): Today's date in the display zone.
        date_format (str): Date format preference.
        time_format (str): Time format preference.

    Returns:
        str: e.g. ``"03:45 PM"`` or ``"09/27/2026 03:45 PM"``.
    """
    text = moment.strftime(time_pattern(time_format))
    if moment.date() != today:
        text = f"{moment.strftime(date_pattern(date_format))} {text}"
    return text


@st.fragment(run_every=timedelta(minutes=1))
def date_and_time() -> None:
    """The current date and time in the chosen zone and formats, redrawn every minute."""
    now = datetime.now(ZoneInfo(display_zone()))
    with st.container(border=True, horizontal=True):
        st.metric(":material/calendar_today: Date", now.strftime(date_pattern(st.session_state["date_format"])))
        st.metric(":material/schedule: Time", now.strftime(time_pattern(st.session_state["time_format"])))


def last_updated(moment_utc: str, source: str = "") -> None:
    """
    Say when the data on a tab was last updated.

    Args:
        moment_utc (str): ``YYYY-MM-DD HH:MM:SS`` UTC of the newest data.
        source (str): Where the data comes from, added after the time.
    """
    zone = ZoneInfo(display_zone())
    moment = parse_utc_timestamp(moment_utc).astimezone(zone)
    text = moment_text(moment, datetime.now(zone).date(), st.session_state["date_format"],
                       st.session_state["time_format"])
    st.caption(f":material/update: Data last updated at **{text}**" + (f" · {source}" if source else ""))


def render_markdown(filename: str) -> None:
    """
    Show a markdown file from ``content/``.

    Args:
        filename (str): File name inside ``content/``.
    """
    st.markdown((CONTENT_DIR / filename).read_text(encoding="utf-8"))


def open_tabs(tabs: dict[str, str]) -> list:
    """
    Draw a page's tabs, opening the one named in the address (``?tab=<key>``).

    Links elsewhere in the dashboard use this, e.g. ``/settings?tab=controllers``.

    Args:
        tabs (dict[str, str]): Tab key (for links) to its label, in order.

    Returns:
        list: One container per tab, for ``with`` blocks.
    """
    wanted = st.query_params.get("tab")
    default = tabs.get(wanted) if wanted in tabs else None
    return st.tabs(list(tabs.values()), default=default)
