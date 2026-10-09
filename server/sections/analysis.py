"""
Analysis page tabs: month by month over the last year, as box plots.

For each measure, one box per month for the last 12 months and this month so
far (``core/history.py``, :func:`history.year_view`): whiskers from the 2.5th
to the 97.5th percentile (the middle 95 %), the box from the 25th to the 75th
(the middle half), a line at the median and a diamond at the average. This
month is highlighted next to the same month last year, with a sentence
comparing them. Finished months come from the stored monthly summaries, so
they stay after their raw readings are deleted (6 months on).
"""
from datetime import datetime, timezone

import altair as alt
import streamlit as st
from pandas import DataFrame

from core import history
from core.conversions import celsius_to_fahrenheit, kmph_to_mph, mm_to_inches

VALUE_COLUMNS = ("mean", "median", "p2_5", "p25", "p75", "p97_5", "minimum", "maximum", "total")
THIS_MONTH, LAST_YEAR, OTHER = "This month so far", "Same month last year", "Other months"
COLORS = {THIS_MONTH: "#f97316", LAST_YEAR: "#3b82f6", OTHER: "#94a3b8"}


@st.cache_data(ttl=600, show_spinner=False)
def year_of(source: str, device_id: int, measure: str, month: str) -> DataFrame | None:
    """The year view, cached for 10 minutes (``month`` keys the cache to this month)."""
    return history.year_view(source, device_id, measure)


def display_units(measure: str, units: str) -> tuple[str, callable]:
    """The unit label and conversion for a measure (stored values are metric)."""
    if measure == "temperature":
        return ("°F", lambda v: celsius_to_fahrenheit(v, 1)) if units == "US" else ("°C", lambda v: v)
    if measure == "wind":
        return ("mph", lambda v: kmph_to_mph(v, 1)) if units == "US" else ("km/h", lambda v: v)
    if measure == "rain":
        return ("in", lambda v: mm_to_inches(v, 2)) if units == "US" else ("mm", lambda v: v)
    return history.MEASURES["greenhouse" if measure == "light" else "weather"].get(measure, ("", ""))[1], \
        (lambda v: v)


def decimals_for(measure: str, units: str) -> int:
    """Sensible decimals: whole % and lux, tenths of a degree or km/h, rain to 0.1 mm or 0.01 in."""
    if measure in ("humidity", "light"):
        return 0
    if measure == "rain":
        return 2 if units == "US" else 1
    return 1


def prepare(view: DataFrame, measure: str, units: str, this_month: str) -> DataFrame:
    """Convert units, round, and label each month for the chart."""
    _unit, convert = display_units(measure, units)
    places = decimals_for(measure, units)
    frame = view.copy()
    for column in VALUE_COLUMNS:
        frame[column] = [None if v is None or v != v else round(float(convert(v)), places) for v in frame[column]]
    last_year = history.add_months(this_month, -12)
    frame["group"] = [THIS_MONTH if m == this_month else LAST_YEAR if m == last_year else OTHER
                      for m in frame["month"]]
    frame["label"] = [datetime(int(m[:4]), int(m[5:]), 1).strftime("%b %y") for m in frame["month"]]
    return frame


def box_chart(frame: DataFrame, unit: str, rain: bool = False, log: bool = False) -> alt.LayerChart:
    """
    Box plots from precomputed statistics: whiskers, box, median line and average diamond.

    ``log`` compresses the scale (light, which spans dark nights to full sun),
    as the light chart on Reports does.
    """
    order = list(frame["label"])
    x = alt.X("label:N", sort=order, title=None, axis=alt.Axis(labelAngle=0))
    color = alt.Color("group:N", scale=alt.Scale(domain=list(COLORS), range=list(COLORS.values())),
                      legend=alt.Legend(title=None, orient="bottom"))
    tooltip = [alt.Tooltip("label:N", title="Month"), alt.Tooltip("samples:Q", title="Samples"),
               alt.Tooltip("mean:Q", title=f"Average ({unit})"), alt.Tooltip("median:Q", title="Median"),
               alt.Tooltip("p25:Q", title="25th percentile"), alt.Tooltip("p75:Q", title="75th percentile"),
               alt.Tooltip("p2_5:Q", title="2.5th percentile"), alt.Tooltip("p97_5:Q", title="97.5th percentile"),
               alt.Tooltip("minimum:Q", title="Lowest"), alt.Tooltip("maximum:Q", title="Highest")]
    if rain:
        tooltip.append(alt.Tooltip("total:Q", title=f"Month's total ({unit})"))
    base = alt.Chart(frame).encode(x=x, tooltip=tooltip)
    y_title = f"{unit} per day" if rain else unit
    whiskers = base.mark_rule(strokeWidth=1.5).encode(
        y=alt.Y("p2_5:Q", title=y_title, scale=alt.Scale(type="symlog") if log else alt.Scale(zero=False)),
        y2="p97_5:Q", color=color)
    box = base.mark_bar(size=18, opacity=0.55).encode(y="p25:Q", y2="p75:Q", color=color)
    median = base.mark_tick(size=18, thickness=2, color="currentColor").encode(y="median:Q")
    mean = base.mark_point(shape="diamond", size=45, filled=True, color="currentColor").encode(y="mean:Q")
    return (whiskers + box + median + mean).properties(height=260, width="container")


def comparison(frame: DataFrame, unit: str, rain: bool) -> str | None:
    """A sentence comparing this month so far with the same month last year."""
    now = frame[frame["group"] == THIS_MONTH]
    before = frame[frame["group"] == LAST_YEAR]
    if now.empty:
        return None
    this = now.iloc[0]
    name = datetime(int(this["month"][:4]), int(this["month"][5:]), 1).strftime("%B")
    if rain:
        text = f"{name} so far: {this['total']:g} {unit} of rain"
        return text + (f" (all of last {name}: {before.iloc[0]['total']:g} {unit})." if not before.empty
                       else ". No figures for last year yet.")
    text = f"{name} so far: median {this['median']:g} {unit}, average {this['mean']:g} {unit}"
    if before.empty:
        return text + ". No figures for last year yet."
    last = before.iloc[0]
    change = this["median"] - last["median"]
    trend = "the same as" if abs(change) < 0.05 else f"{abs(change):g} {unit} {'higher' if change > 0 else 'lower'} than"
    return (f"{text}: {trend} last {name} (median {last['median']:g} {unit}, "
            f"average {last['mean']:g} {unit}).")


def stats_table(frame: DataFrame, unit: str, rain: bool) -> DataFrame:
    """The numbers behind a chart, newest month first."""
    columns = {"label": "Month", "samples": "Samples", "mean": f"Average ({unit})", "median": "Median",
               "p2_5": "2.5th %", "p25": "25th %", "p75": "75th %", "p97_5": "97.5th %",
               "minimum": "Lowest", "maximum": "Highest"}
    if rain:
        columns["total"] = f"Total ({unit})"
    return frame[list(columns)].rename(columns=columns).iloc[::-1].reset_index(drop=True)


def render(source: str, device_id: int) -> None:
    """
    Draw one tab.

    Args:
        source (str): ``"greenhouse"`` or ``"weather"``.
        device_id (int): The controller, for ``"greenhouse"``.
    """
    units = st.session_state["units"]
    this_month = history.current_month(datetime.now(timezone.utc))
    measures = history.MEASURES[source]
    shown = 0
    for column, (measure, (label, _stored)) in zip(st.columns(2) * 2, measures.items()):
        view = year_of(source, device_id if source == "greenhouse" else history.WEATHER_DEVICE, measure, this_month)
        with column.container(border=True):
            rain = measure == "rain"
            st.markdown(f"**{label}**" + (" (estimated)" if measure == "light" else ""))
            if view is None:
                st.caption("No readings yet.")
                continue
            unit = display_units(measure, units)[0]
            frame = prepare(view, measure, units, this_month)
            st.altair_chart(box_chart(frame, unit, rain, log=measure == "light"), use_container_width=True)
            sentence = comparison(frame, unit, rain)
            if sentence:
                st.caption(sentence)
            with st.expander("Numbers"):
                st.dataframe(stats_table(frame, unit, rain), hide_index=True)
            shown += 1
    if not shown:
        st.info("No readings yet. Months appear here as readings build up.")


# --- period comparisons (today / this week / this month against the one before) ---------------

COMPARISONS = {
    # kind: (current label, previous label, "so far" phrase, "by then" phrase)
    "day": ("Today", "Yesterday", "Today so far", "yesterday by this time"),
    "week": ("This week", "Last week", "This week so far", "last week by this point"),
    "month": ("This month", "Last month", "This month so far", "last month by this date"),
}
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@st.cache_data(ttl=300, show_spinner=False)
def comparison_data(source: str, device_id: int, measure: str, kind: str, zone: str, minute: str,
                    place: tuple | None):
    """Both curves and the like-for-like figures, cached for 5 minutes (``minute`` keys the cache)."""
    from core import comparisons

    now = datetime.now(timezone.utc)
    where = {"latitude": place[0], "longitude": place[1]} if place else None
    frame, windows = comparisons.curves(source, device_id, measure, now, zone, kind, where)
    return frame, windows, comparisons.compare(source, device_id, measure, now, zone, kind, where)


def x_axis(kind: str, time_format: str) -> alt.Axis:
    """The shared axis: hours of the day, weekdays, or days of the month."""
    if kind == "day":
        hours = "datum.value % 12 == 0 ? 12 : datum.value % 12"
        label = (f"({hours}) + (datum.value < 12 ? ' AM' : ' PM')" if time_format != "24-hour"
                 else "datum.value + ':00'")
        return alt.Axis(values=list(range(0, 24, 3)), labelExpr=label, title=None, grid=False)
    if kind == "week":
        names = "[" + ", ".join(f"'{d}'" for d in WEEKDAYS) + "]"
        return alt.Axis(values=list(range(0, 168, 24)), labelExpr=f"{names}[floor(datum.value / 24)]",
                        title=None, grid=False)
    return alt.Axis(values=[1, 5, 10, 15, 20, 25, 30], title="Day of the month", grid=False)


def comparison_chart(frame: DataFrame, kind: str, unit: str, time_format: str, log: bool = False,
                     rain: bool = False) -> alt.Chart:
    """The current period so far (orange) over the whole previous one (blue)."""
    now_label, before_label = COMPARISONS[kind][:2]
    data = frame.assign(series=frame["period"].map({"current": now_label, "previous": before_label}))
    domain = [now_label, before_label]
    color = alt.Color("series:N", scale=alt.Scale(domain=domain, range=[COLORS[THIS_MONTH], COLORS[LAST_YEAR]]),
                      legend=alt.Legend(title=None, orient="bottom"))
    upper = 23 if kind == "day" else 167 if kind == "week" else 31
    x = alt.X("x:Q", scale=alt.Scale(domain=[0 if kind != "month" else 1, upper]), axis=x_axis(kind, time_format))
    y_title = f"{unit} per {'hour' if kind != 'month' else 'day'}" if rain else unit
    y = alt.Y("value:Q", title=y_title, scale=alt.Scale(type="symlog") if log else alt.Scale(zero=False))
    tooltip = [alt.Tooltip("series:N", title=""), alt.Tooltip("value:Q", title=unit, format=",.2f")]
    lines = alt.Chart(data).mark_line(strokeWidth=2, interpolate="monotone").encode(x=x, y=y, color=color,
                                                                                  tooltip=tooltip)
    # Dots for this period, so even its first hour or day shows (and stays on top of the previous one).
    dots = alt.Chart(data[data["period"] == "current"]).mark_point(filled=True, size=40).encode(
        x=x, y=y, color=color, tooltip=tooltip)
    return (lines + dots).properties(height=240, width="container")


def comparison_sentence(kind: str, figures: dict, unit: str, convert, places: int, measure: str) -> str | None:
    """Like-for-like: the current period so far against the previous one up to the same point."""
    _now, _before, so_far, by_then = COMPARISONS[kind]
    current, previous = figures["current"], figures["previous"]
    if current is None:
        return None

    def show(value):
        return f"{round(float(convert(value)), places):g}"

    if measure == "rain":
        text = f"{so_far}: {show(current['total'])} {unit} of rain"
        return text + (f" ({by_then}: {show(previous['total'])} {unit})." if previous else ".")
    text = f"{so_far}: average {show(current['mean'])} {unit} (low {show(current['minimum'])}, " \
           f"high {show(current['maximum'])})"
    if previous is None:
        return text + f"; no readings from {by_then.split(' by ')[0]} to compare with."
    change = round(float(convert(current["mean"])) - float(convert(previous["mean"])), places)
    if measure == "temperature":
        words = ("warmer", "cooler")
    else:
        words = ("higher", "lower")
    trend = "about the same as" if abs(change) < 10 ** -places else \
        f"{abs(change):g} {unit} {words[0] if change > 0 else words[1]} than"
    return f"{text}: {trend} {by_then} (average {show(previous['mean'])} {unit})."


def render_comparison(kind: str, source: str, device_id: int, place: dict | None = None) -> None:
    """
    One tab of a period comparison: a chart per measure with a like-for-like sentence.

    Args:
        kind (str): ``"day"``, ``"week"`` or ``"month"``.
        source (str): ``"greenhouse"`` or ``"weather"``.
        device_id (int): The controller, for ``"greenhouse"``.
        place (dict | None): For weather, the chosen location.
    """
    from ui import display_zone

    units = st.session_state["units"]
    time_format = st.session_state["time_format"]
    zone = display_zone()
    minute = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")[:-1]  # changes every 10 minutes
    where = (place["latitude"], place["longitude"]) if place else None
    shown = 0
    for column, (measure, (label, _stored)) in zip(st.columns(2) * 2, history.MEASURES[source].items()):
        frame, _windows, figures = comparison_data(source, device_id, measure, kind, zone, minute, where)
        with column.container(border=True):
            st.markdown(f"**{label.replace(' per day', '')}**" + (" (estimated)" if measure == "light" else ""))
            if frame.empty:
                st.caption("No readings in these periods.")
                continue
            unit, convert = display_units(measure, units)
            places = decimals_for(measure, units)
            shown_frame = frame.assign(value=[round(float(convert(v)), places) for v in frame["value"]])
            st.altair_chart(comparison_chart(shown_frame, kind, unit, time_format, log=measure == "light",
                                             rain=measure == "rain"), use_container_width=True)
            sentence = comparison_sentence(kind, figures, unit, convert, places, measure)
            if sentence:
                st.caption(sentence)
            shown += 1
    if not shown:
        st.info("No readings yet for these periods.")
