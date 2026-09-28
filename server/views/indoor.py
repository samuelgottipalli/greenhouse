"""
"Greenhouse Weather" report page: conditions inside the greenhouse.

* **Gauges** for temperature, humidity and light, with the change over the
  last hour. The temperature and humidity dials are coloured by the
  automation triggers (heater zone, OK, fan zone) from Greenhouse Settings;
  light is shown as estimated lux (``core/light.py``) on a logarithmic dial.
* **Charts** side by side for the chosen period, with readable time labels,
  hover details, and the period's high and low.
* **Table** of readings, one row per time with a column per measure.

Readings are stored by ``services/ingest.py``; a warning shows when they are
too old for automation.
"""
from datetime import datetime, timedelta, timezone

import streamlit as st

from core import db
from core.charts import span, time_chart
from core.gauges import change_over, gauge_svg, greenhouse_temperature_zones, humidity_zones, light_zones
from core.indoor_report import (
    LABELS,
    MEASURE_ORDER,
    PERIODS,
    age_text,
    display_units,
    display_value,
    high_low,
    is_stale,
    local_frame,
    readings_table,
)
from core.timeutil import utc_timestamp
from ui import auto_refresh, current_device, display_zone, page_setup

page_setup("Greenhouse Weather", layout="wide")
auto_refresh("greenhouse", ("device",))
st.title("Greenhouse Weather")

CHART_COLORS = {"temperature": "#ef4444", "humidity": "#3b82f6", "light_raw": "#eab308"}

device = current_device()
units = st.session_state["units"]
time_format = st.session_state["time_format"]
zone = display_zone()
unit_labels = display_units(db.unit_labels(units))
now = datetime.now(timezone.utc)
latest = db.latest_sensor_readings(device_id=device)

if latest is None:
    st.info(
        "No readings from the greenhouse yet. Check that the controller is connected "
        "and the ingest service (`python -m services.ingest`) is running."
    )
    st.stop()

rows = latest.set_index("measure")
newest = rows["reading_utc"].max()
if is_stale(newest, now):
    st.warning(
        f"Latest reading was {age_text(newest, now)}. Automation ignores readings older "
        "than 15 minutes and keeps the heater off until fresh data arrives.",
        icon=":material/warning:",
    )

thresholds = db.read_thresholds(device_id=device)
triggers = {} if thresholds is None else dict(zip(thresholds["name"], thresholds["value"]))
recent = db.sensor_history(utc_timestamp(now - timedelta(hours=2)), device_id=device)
recent = None if recent is None else local_frame(recent, units, zone)

GAUGES = {
    "temperature": (greenhouse_temperature_zones(units, triggers.get("heater_on_temp_c"),
                                                 triggers.get("fan_on_temp_c")), 1, False),
    "humidity": (humidity_zones(triggers.get("fan_on_humidity_pct")), 1, False),
    "light_raw": (light_zones(), 0, True),
}

for column, measure in zip(st.columns(len(MEASURE_ORDER)), MEASURE_ORDER):
    (low, high, zones), decimals, log = GAUGES[measure]
    unit = unit_labels.get(measure, "")
    with column.container(border=True):
        st.markdown(f"**{LABELS[measure]}**" + (" (estimated)" if measure == "light_raw" else ""))
        if measure not in rows.index:
            st.markdown(gauge_svg(None, unit, low, high, zones, title=LABELS[measure]), unsafe_allow_html=True)
            continue
        value = display_value(measure, rows.loc[measure, "value"], units)
        if measure == "light_raw" and value < 10:
            decimals = 1  # 0.3 lux, not "0 lux"
        change = None
        if recent is not None:
            change = change_over(recent[recent["measure"] == measure], "value")
        st.markdown(gauge_svg(value, unit, low, high, zones, change=change, decimals=decimals, log=log,
                          title=f"{LABELS[measure]}: {value} {unit}"), unsafe_allow_html=True)
        raw = f" · raw {rows.loc[measure, 'value']:.0f}" if measure == "light_raw" else ""
        st.caption(f"Measured {age_text(rows.loc[measure, 'reading_utc'], now)}{raw}")

period = st.segmented_control("Period", list(PERIODS), default="24 hours") or "24 hours"
days = PERIODS[period]
since = utc_timestamp(now - timedelta(days=days))
history = db.sensor_history(since, device_id=device, bucket=None if days == 1 else "hour")
if history is None:
    st.info(f"No readings in the last {period}.")
    st.stop()

frame = local_frame(history, units, zone)
clock = "%-I:%M %p" if time_format != "24-hour" else "%H:%M"
when_format = clock if span(days) == "day" else "%a %b %-d, " + clock


def when(moment) -> str:
    """A time for the high/low line (portable: no platform-specific %-codes)."""
    return moment.strftime(when_format.replace("%-", "%")).replace(" 0", " ").lstrip("0")


for column, measure in zip(st.columns(len(MEASURE_ORDER)), MEASURE_ORDER):
    series = frame[frame["measure"] == measure]
    unit = unit_labels.get(measure, "")
    with column.container(border=True):
        st.markdown(f"**{LABELS[measure]}** · last {period}")
        if series.empty:
            st.caption("No readings in this period.")
            continue
        decimals = 0 if measure == "light_raw" else 1
        st.altair_chart(time_chart(series, "value", unit, days, time_format, color=CHART_COLORS[measure],
                                   log=measure == "light_raw", decimals=decimals, height=220),
                        use_container_width=True)
        extremes = high_low(series.set_index("time"))
        if extremes:
            (top, top_at), (bottom, bottom_at) = extremes
            st.caption(f"High {top:g} {unit} at {when(top_at)} · Low {bottom:g} {unit} at {when(bottom_at)}")

with st.expander("Show readings as a table"):
    st.dataframe(readings_table(history, units, zone, unit_labels, time_format), hide_index=True)
    if days > 1:
        st.caption("Hourly averages.")
