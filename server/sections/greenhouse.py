"""
Reports › Greenhouse tab: conditions inside the greenhouse.

* **Gauges** for temperature, humidity and light, with the change over the
  last hour. The temperature and humidity dials are coloured by the
  automation triggers (heater zone, OK, fan zone) from Settings › Greenhouse rules;
  light is shown as estimated lux (``core/light.py``) on a logarithmic dial.
* **Charts** side by side for the chosen period (24 hours, 7 days, 30 days
  or a date range within the last 6 months; ``core/periods.py``), with
  readable time labels, hover details, and the period's high and low.
* **Table** of readings, one row per time with a column per measure.

Readings are stored by ``services/ingest.py``. The tab says when they were
last updated, and warns when they are too old for automation.
"""
from datetime import datetime, timedelta, timezone

import streamlit as st

from core import db
from core.charts import span, time_chart
from core.gauges import change_over, gauge_svg, greenhouse_temperature_zones, humidity_zones, light_zones
from core.indoor_report import (
    LABELS,
    MEASURE_ORDER,
    age_text,
    daily_means,
    display_units,
    display_value,
    high_low,
    is_stale,
    local_frame,
    readings_table,
)
from core.timeutil import utc_timestamp
from ui import current_device, display_zone, last_updated, period_picker


CHART_COLORS = {"temperature": "#ef4444", "humidity": "#3b82f6", "light_raw": "#eab308"}


def render() -> None:
    """Draw this section (called by its tabbed page)."""
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
        return

    rows = latest.set_index("measure")
    newest = rows["reading_utc"].max()
    last_updated(newest, "from the controller")
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

    period = period_picker("greenhouse", db.first_reading_utc("greenhouse", device))
    history = db.sensor_history(period.since_utc, device_id=device,
                                bucket=None if period.detail == "raw" else "hour", until_utc=period.until_utc)
    if history is None:
        st.info(f"No readings for {period.label}.")
        return

    frame = local_frame(history, units, zone)
    if period.detail == "day":
        frame = daily_means(frame)
    clock = "%-I:%M %p" if time_format != "24-hour" else "%H:%M"
    if period.detail == "day":
        when_format = "%a %b %-d"
    else:
        when_format = clock if span(period.days) == "day" else "%a %b %-d, " + clock

    def when(moment) -> str:
        """A time for the high/low line (portable: no platform-specific %-codes)."""
        return moment.strftime(when_format.replace("%-", "%")).replace(" 0", " ").lstrip("0")

    for column, measure in zip(st.columns(len(MEASURE_ORDER)), MEASURE_ORDER):
        series = frame[frame["measure"] == measure]
        unit = unit_labels.get(measure, "")
        with column.container(border=True):
            st.markdown(f"**{LABELS[measure]}** · {period.label}")
            if series.empty:
                st.caption("No readings in this period.")
                continue
            decimals = 0 if measure == "light_raw" else 1
            st.altair_chart(time_chart(series, "value", unit, period.days, time_format,
                                       color=CHART_COLORS[measure], log=measure == "light_raw", decimals=decimals,
                                       height=220),
                            use_container_width=True)
            extremes = high_low(series.set_index("time"))
            if extremes:
                (top, top_at), (bottom, bottom_at) = extremes
                st.caption(f"High {top:g} {unit} at {when(top_at)} · Low {bottom:g} {unit} at {when(bottom_at)}")

    with st.expander("Show readings as a table"):
        if period.detail == "day":
            table = frame.pivot_table(index="time", columns="measure", values="value").sort_index(ascending=False)
            table = table[[m for m in MEASURE_ORDER if m in table.columns]]
            table.columns = [f"{LABELS[m]} ({unit_labels.get(m, '')})".replace(" ()", "") for m in table.columns]
            table.insert(0, "Day", [t.strftime("%a %b %d, %Y") for t in table.index])
            st.dataframe(table.reset_index(drop=True), hide_index=True)
            st.caption("Daily averages.")
        else:
            st.dataframe(readings_table(history, units, zone, unit_labels, time_format), hide_index=True)
            if period.detail == "hour":
                st.caption("Hourly averages.")
