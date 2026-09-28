"""
App Settings additions (colour scheme, page width, auto-refresh), the hidden
Streamlit menu, and the cheap "has anything changed?" check pages use to
refresh themselves.
"""
import json
import tomllib

import pytest
from streamlit.testing.v1 import AppTest

from core import db
from support import SERVER_DIR, run_section, section_app


def run_page(page):
    return AppTest.from_file(str(SERVER_DIR / page), default_timeout=30).run()


def test_streamlit_menu_is_hidden():
    config = tomllib.loads((SERVER_DIR / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    assert config["client"]["toolbarMode"] == "minimal"


# --- preferences -------------------------------------------------------------------


def test_new_preference_defaults(seeded_db):
    at = run_section("display")
    assert at.session_state["theme"] == "Use system setting"
    assert at.session_state["page_width"] == "Automatic"
    assert at.session_state["auto_refresh"] == "On"


def test_app_settings_saves_theme_width_and_refresh(seeded_db):
    at = run_section("display")
    radios = {radio.label: radio for radio in at.radio}
    radios["Colour scheme"].set_value("Dark").run()
    {radio.label: radio for radio in at.radio}["Page width"].set_value("Wide").run()
    at.toggle[0].set_value(False).run()
    assert not at.exception
    stored = db.read_preferences()
    assert {k: stored[k] for k in ("theme", "page_width", "auto_refresh")} == {
        "theme": "Dark", "page_width": "Wide", "auto_refresh": "Off"}
    fresh = run_page("views/home.py")
    assert fresh.session_state["theme"] == "Dark" and fresh.session_state["auto_refresh"] == "Off"


@pytest.mark.parametrize("page_layout, width, expected", [
    ("wide", "Automatic", "wide"), ("centered", "Automatic", "centered"),
    ("centered", "Wide", "wide"), ("wide", "Centered", "centered"),
])
def test_effective_layout(page_layout, width, expected):
    import ui

    assert ui.effective_layout(page_layout, width) == expected


def test_theme_script_sets_every_page():
    import ui

    dark = ui.theme_script("Dark")
    assert json.dumps(json.dumps({"name": "Dark"}, separators=(",", ":"))) in dark  # exactly as Streamlit stores it
    for path in ("stActiveTheme-/-v1", "stActiveTheme-/reports-v1", "stActiveTheme-/settings-v1"):
        assert path in dark
    assert "location.reload()" in dark
    system = ui.theme_script("Use system setting")
    assert "want=null" in system and "removeItem" in system


def test_page_paths_match_the_navigation():
    import re

    import ui

    app = (SERVER_DIR / "app.py").read_text(encoding="utf-8")
    assert set(re.findall(r'url_path="(\w+)"', app)) == set(ui.PAGE_PATHS) - {""}


def test_theme_is_applied_once_per_session(seeded_db, monkeypatch):
    import ui

    scripts = []
    monkeypatch.setattr(ui.components, "html", lambda html, height=0: scripts.append(html))
    at = run_page("views/home.py")
    at.run()
    assert len(scripts) == 1
    at.session_state["theme"] = "Light"
    at.run()
    assert len(scripts) == 2 and "Light" in scripts[-1]


# --- auto-refresh ------------------------------------------------------------------


def test_data_changed():
    import ui

    state = {}
    assert ui.data_changed("k", "v1", state) is False  # first look
    assert ui.data_changed("k", "v1", state) is False
    assert ui.data_changed("k", "v2", state) is True
    assert ui.data_changed("k", None, state) is False  # unknown (database error)
    assert state["k"] == "v2"


def test_data_version_follows_new_data(seeded_db, db_conn):
    first = db.data_version(1)
    assert first == db.data_version(1)
    db.update_device_health(1, "2030-01-01 00:00:00", uptime_s=5)
    second = db.data_version(1)
    assert second != first
    db_conn.execute("INSERT INTO relay_events (device_id, relay_id, state, source, event_utc) "
                    "VALUES (1, 2, 1, 'web', '2030-01-01 00:00:01')")
    db_conn.commit()
    third = db.data_version(1)
    assert third != second
    weather_before = db.data_version(1, ("weather",))
    db.update_device_health(1, "2030-01-01 00:05:00", uptime_s=305)
    assert db.data_version(1, ("weather",)) == weather_before  # the weather page ignores telemetry
    assert db.data_version(1) != third


def test_data_version_never_scans_a_table(seeded_db, db_conn):
    """The check runs every 30 s per open page, so every part must be an index or key lookup."""
    import re

    captured = {}
    real_read = db._read

    def spy(sql, params=None):
        captured["sql"] = sql
        return real_read(sql, params)

    db._read = spy
    try:
        db.data_version(1)
    finally:
        db._read = real_read
    plan = db_conn.execute("EXPLAIN QUERY PLAN " + captured["sql"], {"device_id": 1}).fetchall()
    details = [row[-1] for row in plan]
    full_scans = [d for d in details if re.match(r"SCAN (device_status|relay_events|weather_readings)\b", d)
                  and "USING" not in d]
    assert full_scans == [], details
