"""
"Greenhouse Weather" report page: conditions inside the greenhouse.

Shows the latest temperature, humidity and raw light level from the
controller (with how long ago each was measured and a warning when readings
are too old for automation), and one history chart per measure for the chosen
period. Readings are stored by ``services/ingest.py``.
"""
from datetime import datetime, timedelta, timezone

import streamlit as st

from core import db
from core.indoor_report import PERIODS, age_text, display_value, history_by_measure, is_stale
from core.timeutil import utc_timestamp
from ui import current_device, display_zone, page_setup

page_setup("Greenhouse Weather", layout="wide")
st.title("Greenhouse Weather Data")

LABELS = {"temperature": "Temperature", "humidity": "Humidity", "light_raw": "Light (raw)"}

units = st.session_state["units"]
unit_labels = db.unit_labels(units) or {}
unit_labels.pop("light_raw", None)  # raw ADC counts: no unit to show
now = datetime.now(timezone.utc)
latest = db.latest_sensor_readings(device_id=current_device())

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

columns = st.columns(len(LABELS))
for column, (measure, label) in zip(columns, LABELS.items()):
    if measure in rows.index:
        value = display_value(measure, rows.loc[measure, "value"], units)
        column.metric(
            label=label,
            value=f"{value} {unit_labels.get(measure, '')}".strip(),
            help=f"Measured {age_text(rows.loc[measure, 'reading_utc'], now)}",
            border=True,
        )
    else:
        column.metric(label=label, value="--", border=True)

period = st.segmented_control("Period", list(PERIODS), default="24 hours") or "24 hours"
since = utc_timestamp(now - timedelta(days=PERIODS[period]))
history = db.sensor_history(since, device_id=current_device(), bucket=None if PERIODS[period] == 1 else "hour")
if history is None:
    st.info(f"No readings in the last {period}.")
    st.stop()

series = history_by_measure(history, units, display_zone())
for measure, frame in series.items():
    unit = unit_labels.get(measure, "")
    st.subheader(f"{LABELS[measure]} ({unit})" if unit else LABELS[measure])
    st.line_chart(frame, y="value", x_label="Time", y_label=unit or None, height=240)

with st.expander("Show readings as a table"):
    st.dataframe(history, hide_index=True)
