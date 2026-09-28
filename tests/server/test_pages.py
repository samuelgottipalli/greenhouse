"""
Smoke and behaviour tests for the Streamlit app using ``AppTest``.

Pages build their file paths from ``__file__``, so tests run from the repo
root; ``support`` puts ``server/`` on ``sys.path`` the way ``streamlit run
app.py`` does.
"""
import pytest
from streamlit.testing.v1 import AppTest

from support import SERVER_DIR, TEST_DB_PATH, build_db, run_section, section_app

PAGES = [
    "app.py",
    "views/home.py",
    "views/reports.py",
    "views/control.py",
    "views/settings.py",
    "views/help.py",
]


def run_page(page: str) -> AppTest:
    return AppTest.from_file(str(SERVER_DIR / page), default_timeout=30).run()


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_without_exception(seeded_db, page):
    at = run_page(page)
    assert not at.exception, [e.message for e in at.exception]


@pytest.mark.parametrize(
    "tab, heading",
    [(0, "# How to use the greenhouse dashboard"), (1, "# About this greenhouse")],
)
def test_help_page_tabs(seeded_db, tab, heading):
    at = run_page("views/help.py")
    assert not at.exception
    assert [t.label for t in at.tabs] == ["How to use it", "About"]
    assert at.tabs[tab].markdown[0].value.startswith(heading)


def test_about_gives_credit():
    about = (SERVER_DIR / "content" / "about.md").read_text(encoding="utf-8")
    assert "Samuel Gottipalli" in about and "Claude" in about and "Anthropic" in about


@pytest.mark.parametrize("page, labels", [
    ("views/reports.py", ["Greenhouse", "Outdoor weather"]),
    ("views/settings.py", ["Display", "Greenhouse rules", "Controllers"]),
])
def test_tabbed_pages(seeded_db, page, labels):
    at = run_page(page)
    assert not at.exception, [e.message for e in at.exception]
    assert [t.label for t in at.tabs] == labels


def test_reports_tabs_hold_their_sections(seeded_db):
    at = run_page("views/reports.py")
    greenhouse, outdoor = at.tabs
    assert "Automation ignores readings older" in greenhouse.warning[0].value  # fixture readings are old
    assert any(m.value.startswith("<svg") for m in outdoor.markdown)  # outdoor gauges drawn


def test_a_link_can_open_a_tab(seeded_db):
    at = AppTest.from_file(str(SERVER_DIR / "views/settings.py"), default_timeout=30)
    at.query_params["tab"] = "controllers"
    at.run()
    assert not at.exception
    # The chosen tab is the default one in the page's tab bar.
    assert at.tabs[2].label == "Controllers"


def test_help_mentions_every_page_and_tab():
    text = (SERVER_DIR / "content" / "help.md").read_text(encoding="utf-8")
    for name in ("Home", "Reports", "Greenhouse", "Outdoor weather", "Remote Control", "Settings", "Display",
                 "Greenhouse rules", "Controllers", "About"):
        assert name in text, name


def gauges(at):
    """Weather gauges by title: the SVG's accessible title starts with the label."""
    found = {}
    for element in at.markdown:
        body = element.value
        if body.startswith("<svg") and "<title>" in body:
            found[body.split("<title>")[1].split(":")[0]] = body
    return found


def test_weather_page_shows_latest_reading(seeded_db):
    at = run_section("weather")
    labels = [m.label for m in at.metric]
    assert labels == [":material/cloud: Conditions", ":material/wb_twilight: Sunrise",
                      ":material/nights_stay: Sunset", ":material/sunny: Daylight"]
    values = [m.value for m in at.metric]
    assert values[0] == "Overcast" and values[3] == "12 h 00 min"  # fixture sun: 06:00-18:00 UTC
    assert set(gauges(at)) == {"Temperature", "Humidity", "Precipitation", "Wind speed"}
    assert len(at.get("arrow_vega_lite_chart")) == 4  # a chart of the day under each gauge
    captions = [c.value for c in at.caption]
    assert captions[0] == ":material/update: Data last updated at **12:00 PM** · from Open-Meteo"
    assert "Today's total 0.03 in" in captions  # 4 x 0.2 mm, fixture units are US
    assert "From the south-southwest" in captions
    assert "Feels like 46.4 °F" in captions and "Today 50–53 %" in captions
    assert not any(ord(ch) > 0x2000 for m in at.metric for ch in m.label + m.value)  # no emoji


def test_reports_date_and_time_sit_above_the_tabs(seeded_db):
    at = run_page("views/reports.py")
    assert not at.exception
    labels = [m.label for m in at.metric]
    assert labels[:2] == [":material/calendar_today: Date", ":material/schedule: Time"]
    for tab in at.tabs:  # not repeated inside a tab
        assert ":material/calendar_today: Date" not in [m.label for m in tab.metric]
    greenhouse, outdoor = at.tabs
    assert greenhouse.caption[0].value.startswith(":material/update: Data last updated at **")
    assert greenhouse.caption[0].value.endswith("· from the controller")
    assert outdoor.caption[0].value.startswith(":material/update: Data last updated at **")


@pytest.mark.parametrize("sun, icon", [(("+1 hours", "+12 hours"), ":material/clear_night:"),
                                        (("-6 hours", "+6 hours"), ":material/sunny:")])
def test_conditions_icon_follows_day_and_night(seeded_db, db_conn, sun, icon):
    """Clear sky shows a sun between sunrise and sunset, and a moon otherwise."""
    db_conn.execute("UPDATE weather_readings SET weather_code = 0, sunrise_utc = datetime(measured_utc, ?), "
                    "sunset_utc = datetime(measured_utc, ?)", sun)
    db_conn.commit()
    at = run_section("weather")
    assert at.metric[0].label == f"{icon} Conditions"


@pytest.fixture
def published(monkeypatch):
    """Capture relay commands instead of sending them to a broker."""
    import core.mqtt

    sent = []
    monkeypatch.setattr(core.mqtt, "publish_relay_command", lambda **kw: sent.append(kw) or True)
    return sent


def latest_event(db_conn, relay_id):
    return db_conn.execute(
        "SELECT state, source FROM relay_events WHERE relay_id = ? ORDER BY event_utc DESC, event_id DESC LIMIT 1",
        (relay_id,),
    ).fetchone()


def test_control_reflects_relay_state(seeded_db):
    at = run_page("views/control.py")
    # Fixture: fan last switched on, heater off.
    assert at.toggle(key="2").value is True
    assert at.toggle(key="3").value is False


def test_control_toggle_on_publishes_and_logs(seeded_db, db_conn, published):
    at = run_page("views/control.py")
    at.toggle(key="3").set_value(True).run()  # heater off -> on
    assert published == [{"relay_id": 3, "state": 1, "source": "web", "device_id": 1}]
    assert latest_event(db_conn, 3) == (1, "web")


def test_settings_save_round_trips_temperatures(seeded_db, db_conn):
    at = run_section("rules")
    assert at.number_input(key="fan_on_temp").value == 89.6  # 32 C shown in F
    next(b for b in at.button if b.label == "Save").click().run()
    assert not at.exception
    assert db_conn.execute(
        "SELECT value FROM thresholds WHERE profile = 'current' AND name = 'fan_on_temp_c'"
    ).fetchone() == (32.0,)


def test_settings_buffers_convert_as_differences(seeded_db, db_conn):
    # Formerly S-08: buffers were labelled F but stored unconverted.
    at = run_section("rules")
    assert at.number_input(key="fan_on_temp_buffer").value == 3.6  # 2 C difference
    at.number_input(key="heater_on_temp_buffer").set_value(2.0)
    next(b for b in at.button if b.label == "Save").click().run()
    rows = dict(db_conn.execute(
        "SELECT name, buffer FROM thresholds WHERE profile = 'current'"
    ).fetchall())
    assert rows["heater_on_temp_c"] == 1.11  # 2 F difference
    assert rows["fan_on_temp_c"] == 2.0  # unchanged round trip


def test_settings_si_units_are_stored_as_entered(seeded_db, db_conn):
    at = section_app("rules")
    at.session_state["units"] = "SI"
    at.run()
    assert at.number_input(key="fan_on_temp").value == 32.0
    at.number_input(key="fan_on_temp_buffer").set_value(3.0)
    next(b for b in at.button if b.label == "Save").click().run()
    assert db_conn.execute(
        "SELECT value, buffer FROM thresholds WHERE profile = 'current' AND name = 'fan_on_temp_c'"
    ).fetchone() == (32.0, 3.0)


def test_settings_save_keeps_hh_mm_and_minutes(seeded_db, db_conn):
    # Formerly known bug S-02: times were saved as HH:MM:SS.
    at = run_section("rules")
    at.number_input(key="water_run_time_2").set_value(20)
    next(b for b in at.button if b.label == "Save").click().run()
    assert db_conn.execute(
        "SELECT slot, start_local, duration_min FROM watering_schedule WHERE profile = 'current' ORDER BY slot"
    ).fetchall()[:2] == [(1, "06:00", 30), (2, "00:00", 20)]


def test_settings_revert_discards_edits(seeded_db):
    at = run_section("rules")
    at.number_input(key="fan_on_humidity").set_value(80.0).run()
    next(b for b in at.button if b.label == "Revert").click().run()
    assert at.number_input(key="fan_on_humidity").value == 50.0


def test_settings_restore_defaults(seeded_db, db_conn):
    db_conn.execute("UPDATE thresholds SET value = 99 WHERE profile = 'current' AND name = 'fan_on_humidity_pct'")
    db_conn.commit()
    at = run_section("rules")
    assert at.number_input(key="fan_on_humidity").value == 99.0
    next(b for b in at.button if b.label == "Restore Defaults").click().run()
    assert at.number_input(key="fan_on_humidity").value == 50.0


def test_settings_page_without_settings_shows_error(seeded_db, db_conn):
    db_conn.execute("DELETE FROM thresholds")
    db_conn.commit()
    at = run_section("rules")
    assert not at.exception
    assert "not found" in at.error[0].value


def test_control_first_toggle_off_sends_off(seeded_db, db_conn, published):
    # Formerly known bug S-03: the first toggle after page load sent "on".
    at = run_page("views/control.py")
    at.toggle(key="2").set_value(False).run()  # fan on -> off
    assert published == [{"relay_id": 2, "state": 0, "source": "web", "device_id": 1}]
    assert latest_event(db_conn, 2) == (0, "web")
    assert at.toggle(key="2").value is False


def test_control_toggle_on_then_off(seeded_db, db_conn, published):
    at = run_page("views/control.py")
    at.toggle(key="4").set_value(True).run()
    at.toggle(key="4").set_value(False).run()
    assert [p["state"] for p in published] == [1, 0]
    assert latest_event(db_conn, 4) == (0, "web")


def test_control_shows_changes_made_elsewhere(seeded_db, db_conn):
    at = run_page("views/control.py")
    assert at.toggle(key="3").value is False
    db_conn.execute(
        "INSERT INTO relay_events (device_id, relay_id, event_utc, state, source) "
        "VALUES (1, 3, '2031-01-01 00:00:00', 1, 'auto')"
    )
    db_conn.commit()
    at.run()
    assert at.toggle(key="3").value is True


def test_control_page_with_no_relay_history(seeded_db, db_conn, published):
    # S-09: the page used to crash when relay_events was empty.
    db_conn.execute("DELETE FROM relay_events")
    db_conn.commit()
    at = run_page("views/control.py")
    assert not at.exception
    assert [t.value for t in at.toggle] == [False, False, False, False]
    at.toggle(key="1").set_value(True).run()
    assert published == [{"relay_id": 1, "state": 1, "source": "web", "device_id": 1}]


def test_control_page_without_relays_shows_error(seeded_db, db_conn):
    db_conn.execute("PRAGMA foreign_keys = OFF")
    db_conn.execute("DELETE FROM relays")
    db_conn.commit()
    at = run_page("views/control.py")
    assert not at.exception
    assert "not found" in at.error[0].value


def test_weather_page_handles_no_data_today(seeded_db):
    # Formerly known bug S-04: crashed when the latest reading was not from today.
    build_db(TEST_DB_PATH, weather_days_ago=1)
    at = run_section("weather")
    assert not at.exception
    assert "No weather readings yet today" in at.info[0].value


def test_weather_page_handles_single_reading_today(seeded_db):
    # Formerly known bug S-04: deltas needed two readings.
    build_db(TEST_DB_PATH, weather_rows=1)
    at = run_section("weather")
    assert not at.exception
    temperature = gauges(at)["Temperature"]
    assert "50 °F" in temperature  # 10 C in the default US units
    assert " in 1 h" not in temperature  # no change shown without an older reading


def test_weather_page_handles_north_wind(seeded_db):
    # Formerly known bug S-05: 348.75-360 degrees gave compass index 16.
    build_db(TEST_DB_PATH, wind_direction=350)
    at = run_section("weather")
    assert not at.exception
    assert "From the north" in [c.value for c in at.caption]


def test_weather_page_us_values(seeded_db):
    # Latest fixture row: 10 C, apparent 8 C, 0.2 mm precipitation, 5 km/h.
    at = run_section("weather")
    found = gauges(at)
    assert "0.03 in/h" in found["Precipitation"] and "light" in found["Precipitation"]  # 0.8 mm/h
    assert "50 °F" in found["Temperature"] and "cool" in found["Temperature"]  # 10 C
    assert "3.1 mph" in found["Wind speed"] and "light" in found["Wind speed"]


def test_weather_page_empty_table_says_so(seeded_db):
    build_db(TEST_DB_PATH, weather_rows=0)
    at = run_section("weather")
    assert "No weather readings yet" in at.info[0].value


def test_preferences_persist_across_sessions(seeded_db):
    # Formerly S-18: preferences reset with every browser session.
    at = run_section("display")
    at.radio[0].set_value("SI").run()
    at.radio[2].set_value("24-hour").run()
    fresh = run_section("display")
    assert fresh.session_state["units"] == "SI"
    assert fresh.session_state["time_format"] == "24-hour"
    weather = run_section("weather")
    assert "10 °C" in gauges(weather)["Temperature"]


def test_unchanged_preferences_are_not_rewritten(seeded_db, db_conn):
    run_section("display")
    assert db_conn.execute("SELECT count(*) FROM app_preferences").fetchone() == (0,)


def test_control_failed_publish_is_not_logged(seeded_db, db_conn, monkeypatch):
    # S-19: a command the broker never accepted was still logged as done.
    import core.mqtt

    monkeypatch.setattr(core.mqtt, "publish_relay_command", lambda **kw: False)
    before = db_conn.execute("SELECT count(*) FROM relay_events").fetchone()
    at = run_page("views/control.py")
    at.toggle(key="3").set_value(True).run()
    assert db_conn.execute("SELECT count(*) FROM relay_events").fetchone() == before
    assert at.toggle(key="3").value is False  # snaps back to the real state


def test_control_disabled_while_controller_offline(seeded_db, db_conn):
    # S-20: commands to an offline controller are lost.
    db_conn.execute("INSERT INTO device_status (device_id, status, updated_utc) VALUES (1, 'offline', '2026-09-26 19:00:00')")
    db_conn.commit()
    at = run_page("views/control.py")
    assert "controller is offline" in at.warning[0].value
    assert all(t.disabled for t in at.toggle)


def test_control_enabled_when_online(seeded_db, db_conn):
    db_conn.execute("INSERT INTO device_status (device_id, status, updated_utc) VALUES (1, 'online', '2026-09-26 19:00:00')")
    db_conn.commit()
    at = run_page("views/control.py")
    assert not at.warning
    assert not any(t.disabled for t in at.toggle)


def test_sidebar_and_about_show_the_server_version(seeded_db):
    from version import VERSION

    at = AppTest.from_file(str(SERVER_DIR / "app.py"), default_timeout=30).run()
    assert any(f"Greenhouse {VERSION}" in c.value for c in at.sidebar.caption)
    about = run_page("views/help.py").tabs[1]
    assert any(f"Server software {VERSION}" in c.value for c in about.caption)
