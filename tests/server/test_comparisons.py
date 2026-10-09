"""
Tests for the Analysis page's period comparisons: core/comparisons.py and the
today / this week / this month views (sections/analysis.py, views/analysis.py).
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from streamlit.testing.v1 import AppTest

from core import comparisons
from support import SERVER_DIR

ZONE = "America/Los_Angeles"
TZ = ZoneInfo(ZONE)


def local(*args):
    return datetime(*args, tzinfo=TZ)


# --- windows --------------------------------------------------------------------------------


def test_day_window():
    w = comparisons.windows("day", local(2026, 10, 8, 14, 30), ZONE)
    assert (w.current_start, w.previous_start, w.previous_end) == (
        local(2026, 10, 8), local(2026, 10, 7), local(2026, 10, 8))
    assert w.previous_same_point == local(2026, 10, 7, 14, 30)


def test_week_window_starts_on_monday():
    w = comparisons.windows("week", local(2026, 10, 8, 9, 0), ZONE)  # a Thursday
    assert w.current_start == local(2026, 10, 5) and w.previous_start == local(2026, 9, 28)
    assert w.previous_same_point == local(2026, 10, 1, 9, 0)  # last Thursday, 9 AM


def test_month_window():
    w = comparisons.windows("month", local(2026, 10, 8, 9, 0), ZONE)
    assert (w.current_start, w.previous_start) == (local(2026, 10, 1), local(2026, 9, 1))
    assert w.previous_same_point == local(2026, 9, 8, 9, 0)


def test_month_window_when_last_month_was_shorter():
    w = comparisons.windows("month", local(2026, 3, 31, 12, 0), ZONE)
    assert w.previous_same_point == local(2026, 2, 28, 12, 0)


def test_month_window_in_january():
    w = comparisons.windows("month", local(2027, 1, 15, 8, 0), ZONE)
    assert w.previous_start == local(2026, 12, 1) and w.previous_same_point == local(2026, 12, 15, 8, 0)


def test_unknown_kind():
    with pytest.raises(ValueError):
        comparisons.windows("year", local(2026, 1, 1), ZONE)


def test_positions():
    monday = local(2026, 10, 5)
    assert comparisons.position("day", local(2026, 10, 5, 13, 0), monday) == 13.0
    assert comparisons.position("week", local(2026, 10, 7, 6, 0), monday) == 54.0  # Wed 6 AM
    assert comparisons.position("month", local(2026, 10, 7, 6, 0), monday) == 7.0


# --- readings, curves and figures --------------------------------------------------------------


NOW = local(2026, 10, 8, 12, 30)


@pytest.fixture
def two_days(seeded_db, db_conn):
    """Temperature at every half hour: 20 °C yesterday, 22 °C today (until now); rain both days."""
    db_conn.execute("DELETE FROM sensor_readings")
    db_conn.execute("DELETE FROM weather_readings")
    rows, weather = [], []
    for day, value in ((7, 20.0), (8, 22.0)):
        moment = local(2026, 10, day)
        while moment < (local(2026, 10, 9) if day == 7 else NOW):
            if day == 7 and moment >= local(2026, 10, 8):
                break
            stamp = moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            rows.append((1, 1, stamp, value + (1 if moment.hour >= 12 else 0)))
            if moment.minute == 0:
                weather.append((stamp, 39.53, -119.75, value, 0.5 if moment.hour < 2 else 0.0))
            moment += timedelta(minutes=30)
    db_conn.executemany("INSERT INTO sensor_readings VALUES (?, ?, ?, ?)", rows)
    db_conn.executemany("INSERT INTO weather_readings (measured_utc, latitude, longitude, temperature_c, "
                        "precipitation_mm) VALUES (?, ?, ?, ?, ?)", weather)
    db_conn.commit()


def test_curves(two_days):
    frame, w = comparisons.curves("greenhouse", 1, "temperature", NOW, ZONE, "day")
    today = frame[frame["period"] == "current"]
    yesterday = frame[frame["period"] == "previous"]
    assert list(yesterday["x"]) == [float(h) for h in range(24)]  # all of yesterday
    assert list(today["x"]) == [float(h) for h in range(13)]  # today until 12:30
    assert yesterday.iloc[0]["value"] == 20.0 and yesterday.iloc[-1]["value"] == 21.0
    assert today.iloc[0]["value"] == 22.0


def test_compare_is_like_for_like(two_days):
    figures = comparisons.compare("greenhouse", 1, "temperature", NOW, ZONE, "day")
    # Today until 12:30: 24 readings of 22 and one of 23. Yesterday until 12:30: the same shape at 20/21.
    assert figures["current"]["samples"] == figures["previous"]["samples"] == 25
    assert figures["current"]["mean"] - figures["previous"]["mean"] == pytest.approx(2.0)


def test_rain_is_totalled(two_days):
    frame, _ = comparisons.curves("weather", 0, "rain", NOW, ZONE, "day")
    yesterday = frame[frame["period"] == "previous"]
    assert list(yesterday["value"][:3]) == [0.5, 0.5, 0.0]
    figures = comparisons.compare("weather", 0, "rain", NOW, ZONE, "day")
    assert figures["current"]["total"] == figures["previous"]["total"] == 1.0


def test_weather_only_for_the_chosen_place(two_days):
    london = {"latitude": 51.5, "longitude": -0.12}
    frame, _ = comparisons.curves("weather", 0, "temperature", NOW, ZONE, "day", london)
    assert frame.empty


def test_no_readings(seeded_db, db_conn):
    db_conn.execute("DELETE FROM sensor_readings")
    db_conn.commit()
    frame, _ = comparisons.curves("greenhouse", 1, "temperature", NOW, ZONE, "week")
    assert frame.empty
    assert comparisons.compare("greenhouse", 1, "temperature", NOW, ZONE, "week") == {"current": None,
                                                                                      "previous": None}


# --- wording and charts ----------------------------------------------------------------------


def test_sentences():
    from sections import analysis

    def figures(mean, low, high, total=None):
        return {"mean": mean, "minimum": low, "maximum": high, "total": total}

    same = lambda v: v  # noqa: E731
    text = analysis.comparison_sentence("day", {"current": figures(22.0, 18, 26), "previous": figures(20.0, 15, 24)},
                                        "°C", same, 1, "temperature")
    assert text == ("Today so far: average 22 °C (low 18, high 26): 2 °C warmer than yesterday by this time "
                    "(average 20 °C).")
    text = analysis.comparison_sentence("week", {"current": figures(40, 30, 50), "previous": figures(45, 35, 55)},
                                        "%", same, 0, "humidity")
    assert "5 % lower than last week by this point" in text
    text = analysis.comparison_sentence("month", {"current": figures(0, 0, 0, 12.5), "previous": None},
                                        "mm", same, 1, "rain")
    assert text == "This month so far: 12.5 mm of rain."
    assert analysis.comparison_sentence("day", {"current": None, "previous": None}, "°C", same, 1,
                                        "temperature") is None


@pytest.mark.parametrize("kind, ticks", [("day", 8), ("week", 7), ("month", 7)])
def test_chart_axes(kind, ticks):
    from pandas import DataFrame

    from sections import analysis

    frame = DataFrame({"period": ["current", "previous"], "x": [1.0, 2.0], "value": [1.0, 2.0]})
    spec = analysis.comparison_chart(frame, kind, "°C", "12-hour").to_dict()
    lines, dots = spec["layer"]
    assert len(lines["encoding"]["x"]["axis"]["values"]) == ticks
    assert lines["encoding"]["color"]["scale"]["domain"] == list(analysis.COMPARISONS[kind][:2])
    assert dots["mark"]["type"] == "point"


def test_month_curve_leaves_out_today(two_days):
    frame, _ = comparisons.curves("greenhouse", 1, "temperature", NOW, ZONE, "month")
    assert list(frame[frame["period"] == "current"]["x"]) == [7.0]  # the 7th; not the 8th (today)
    figures = comparisons.compare("greenhouse", 1, "temperature", NOW, ZONE, "month")
    assert figures["current"]["samples"] == 48 + 25  # the sentence still counts today


# --- the page -----------------------------------------------------------------------------------


@pytest.mark.parametrize("view", ["Today vs yesterday", "This week vs last week", "This month vs last month",
                                  "Last 12 months"])
def test_each_view(seeded_db, db_conn, view):
    now = datetime.now(timezone.utc)
    db_conn.executemany("INSERT INTO sensor_readings VALUES (1, 1, ?, ?)",
                        [((now - timedelta(minutes=1 + 10 * i)).strftime("%Y-%m-%d %H:%M:%S"), 20.0 + i % 5)
                         for i in range(6 * 24 * 40)])  # every 10 minutes for 40 days, up to a minute ago
    db_conn.commit()
    at = AppTest.from_file(str(SERVER_DIR / "views/analysis.py"), default_timeout=60)
    at.session_state["analysis_view"] = view  # set before the only run (see test_history_views.with_date_range)
    at.run()
    assert not at.exception, [e.message for e in at.exception]
    assert [t.label for t in at.tabs] == ["Greenhouse", "Outdoor weather"]
    assert len(at.tabs[0].get("arrow_vega_lite_chart")) >= 1
    if view != "Last 12 months":
        assert any(" so far: average " in c.value for c in at.tabs[0].caption)
