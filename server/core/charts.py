"""
Compact time charts for the report pages (Altair, bundled with Streamlit).

Times are shown the way people read them: hours ("3 PM") for a day, weekday
and date ("Mon 27") for a week, and month and day ("Sep 27") for a month,
with the full date and time in the tooltip. Values come in the display zone
already; they are drawn on a UTC scale so the browser's own time zone can't
shift them.
"""
import altair as alt
from pandas import DataFrame

AXIS_FORMATS_12H = {"day": "%-I %p", "week": "%a %-d", "month": "%b %-d"}
AXIS_FORMATS_24H = {"day": "%H:%M", "week": "%a %-d", "month": "%b %-d"}
TOOLTIP_12H = "%a %b %-d, %-I:%M %p"
TOOLTIP_24H = "%a %b %-d, %H:%M"


def span(days: float) -> str:
    """Name the kind of period: ``"day"`` (up to 2 days), ``"week"`` (up to 10) or ``"month"``."""
    if days <= 2:
        return "day"
    return "week" if days <= 10 else "month"


def axis_format(days: float, time_format: str) -> str:
    """
    The time-axis label format for a period.

    Args:
        days (float): Length of the period shown.
        time_format (str): ``"12-hour"`` or ``"24-hour"``.

    Returns:
        str: A d3 time format, e.g. ``"%-I %p"``.
    """
    formats = AXIS_FORMATS_24H if time_format == "24-hour" else AXIS_FORMATS_12H
    return formats[span(days)]


def tooltip_format(time_format: str) -> str:
    """The full date-and-time format for tooltips (Python ``strftime``)."""
    return (TOOLTIP_24H if time_format == "24-hour" else TOOLTIP_12H).replace("%-", "%")


def chart_frame(frame: DataFrame, value: str, time: str, time_format: str) -> DataFrame:
    """
    Prepare data for :func:`time_chart`.

    Args:
        frame (DataFrame): Local (naive) times and values.
        value (str): Value column.
        time (str): Time column (naive, in the display zone).
        time_format (str): ``"12-hour"`` or ``"24-hour"``.

    Returns:
        DataFrame: ``time`` (tagged UTC so the chart shows it unchanged),
        ``value`` and ``when`` (tooltip text).
    """
    data = DataFrame({"time": frame[time], "value": frame[value]}).dropna()
    data["when"] = data["time"].dt.strftime(tooltip_format(time_format)).str.replace(" 0", " ", regex=False)
    data["time"] = data["time"].dt.tz_localize("UTC")
    return data


def time_chart(frame: DataFrame, value: str, unit: str, days: float, time_format: str,
               color: str = "#22c55e", time: str = "time", height: int = 200, log: bool = False,
               decimals: int = 1) -> alt.Chart:
    """
    A small line chart of one measure over time.

    Args:
        frame (DataFrame): Readings: a naive local time column and a value column.
        value (str): Value column.
        unit (str): Unit for the axis and tooltip.
        days (float): Length of the period shown (sets the axis labels).
        time_format (str): ``"12-hour"`` or ``"24-hour"``.
        color (str): Line colour.
        time (str): Time column.
        height (int): Pixels.
        log (bool): Logarithmic value axis (light).
        decimals (int): Decimal places in the tooltip.

    Returns:
        alt.Chart: Ready for ``st.altair_chart``.
    """
    data = chart_frame(frame, value, time, time_format)
    y_scale = alt.Scale(type="symlog") if log else alt.Scale(zero=False, nice=True)
    return (
        alt.Chart(data, height=height)
        .mark_line(color=color, strokeWidth=2, interpolate="monotone")
        .encode(
            x=alt.X("time:T", title=None, scale=alt.Scale(type="utc"),
                    axis=alt.Axis(format=axis_format(days, time_format), labelAngle=0, tickCount=6,
                                  grid=False, labelOverlap=True)),
            y=alt.Y("value:Q", title=unit or None, scale=y_scale, axis=alt.Axis(tickCount=4)),
            tooltip=[alt.Tooltip("when:N", title="Time"),
                     alt.Tooltip("value:Q", title=unit or "Value", format=f",.{decimals}f")],
        )
        .properties(width="container")
    )
