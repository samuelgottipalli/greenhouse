"""
Smoke and behaviour tests for the Streamlit app using ``AppTest``.

Pages build their file paths from ``__file__``, so tests run from the repo
root; ``support`` puts ``server/`` on ``sys.path`` the way ``streamlit run
app.py`` does.
"""
import pytest
from streamlit.testing.v1 import AppTest

from support import SERVER_DIR, TEST_DB_PATH, build_db

PAGES = [
    "app.py",
    "views/home.py",
    "views/app_settings.py",
    "views/indoor.py",
    "views/weather.py",
    "views/control.py",
    "views/greenhouse_settings.py",
]


def run_page(page: str) -> AppTest:
    return AppTest.from_file(str(SERVER_DIR / page), default_timeout=30).run()


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_without_exception(seeded_db, page):
    at = run_page(page)
    assert not at.exception, [e.message for e in at.exception]


def _markdown_script(filename):
    from ui import render_markdown

    render_markdown(filename, "Test")


@pytest.mark.parametrize(
    "filename, heading",
    [("about.md", "# About the Greenhouse"), ("help.md", "# Greenhouse Control System Help")],
)
def test_markdown_pages(filename, heading):
    at = AppTest.from_function(_markdown_script, args=(filename,), default_timeout=30).run()
    assert not at.exception
    assert at.markdown[0].value.startswith(heading)


def test_weather_page_shows_latest_reading(seeded_db):
    at = run_page("views/weather.py")
    labels = [m.label for m in at.metric]
    assert {"Sunrise \U0001f305", "Temperature", "Humidity", "Wind Speed"} <= set(labels)


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
    assert published == [{"relay_id": 3, "state": 1, "source": "web"}]
    assert latest_event(db_conn, 3) == (1, "web")


def test_settings_save_round_trips_temperatures(seeded_db, db_conn):
    at = run_page("views/greenhouse_settings.py")
    assert at.number_input(key="fan_on_temp").value == 89.6  # 32 C shown in F
    next(b for b in at.button if b.label == "Save").click().run()
    assert not at.exception
    assert db_conn.execute(
        "SELECT value FROM thresholds WHERE profile = 'current' AND name = 'fan_on_temp_c'"
    ).fetchone() == (32.0,)


def test_settings_save_keeps_hh_mm_and_minutes(seeded_db, db_conn):
    # Formerly known bug S-02: times were saved as HH:MM:SS.
    at = run_page("views/greenhouse_settings.py")
    at.number_input(key="water_run_time_2").set_value(20)
    next(b for b in at.button if b.label == "Save").click().run()
    assert db_conn.execute(
        "SELECT slot, start_local, duration_min FROM watering_schedule WHERE profile = 'current' ORDER BY slot"
    ).fetchall()[:2] == [(1, "06:00", 30), (2, "00:00", 20)]


def test_settings_revert_discards_edits(seeded_db):
    at = run_page("views/greenhouse_settings.py")
    at.number_input(key="fan_on_humidity").set_value(80.0).run()
    next(b for b in at.button if b.label == "Revert").click().run()
    assert at.number_input(key="fan_on_humidity").value == 50.0


def test_settings_restore_defaults(seeded_db, db_conn):
    db_conn.execute("UPDATE thresholds SET value = 99 WHERE profile = 'current' AND name = 'fan_on_humidity_pct'")
    db_conn.commit()
    at = run_page("views/greenhouse_settings.py")
    assert at.number_input(key="fan_on_humidity").value == 99.0
    next(b for b in at.button if b.label == "Restore Defaults").click().run()
    assert at.number_input(key="fan_on_humidity").value == 50.0


def test_settings_page_without_settings_shows_error(seeded_db, db_conn):
    db_conn.execute("DELETE FROM thresholds")
    db_conn.commit()
    at = run_page("views/greenhouse_settings.py")
    assert not at.exception
    assert "not found" in at.error[0].value


def test_control_first_toggle_off_sends_off(seeded_db, db_conn, published):
    # Formerly known bug S-03: the first toggle after page load sent "on".
    at = run_page("views/control.py")
    at.toggle(key="2").set_value(False).run()  # fan on -> off
    assert published == [{"relay_id": 2, "state": 0, "source": "web"}]
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
    assert published == [{"relay_id": 1, "state": 1, "source": "web"}]


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
    at = run_page("views/weather.py")
    assert not at.exception
    assert "No weather readings yet today" in at.info[0].value


def test_weather_page_handles_single_reading_today(seeded_db):
    # Formerly known bug S-04: deltas needed two readings.
    build_db(TEST_DB_PATH, weather_rows=1)
    at = run_page("views/weather.py")
    assert not at.exception
    temperature = next(m for m in at.metric if m.label == "Temperature")
    assert temperature.value == "50.0 °F"  # 10 C in the default US units


def test_weather_page_handles_north_wind(seeded_db):
    # Formerly known bug S-05: 348.75-360 degrees gave compass index 16.
    build_db(TEST_DB_PATH, wind_direction=350)
    at = run_page("views/weather.py")
    assert not at.exception
    assert next(m for m in at.metric if m.label == "Wind Direction").value.endswith("- N")


def test_weather_page_us_values(seeded_db):
    # Latest fixture row: 10 C, apparent 8 C, 0.2 mm precipitation, 5 km/h.
    at = run_page("views/weather.py")
    value = {m.label: m.value for m in at.metric}
    assert value["Temperature"] == "50.0 °F"
    assert value["Precipitation"] == "0.01 in"
    assert value["Wind Speed"] == "3.11 mph"


def test_weather_page_empty_table_says_so(seeded_db):
    build_db(TEST_DB_PATH, weather_rows=0)
    at = run_page("views/weather.py")
    assert "No weather readings yet" in at.info[0].value
