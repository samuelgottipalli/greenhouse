"""
Speedometer-style gauges for the report pages, drawn as inline SVG.

A gauge is a half circle split into coloured zones (e.g. heater zone, OK,
fan zone), with a needle at the current value, the value and its zone name
in the middle, and the change over the last hour underneath. Text uses
``currentColor``, so it follows Streamlit's light or dark theme; zone
colours are mid-tones that read on both.

:func:`gauge_svg` is pure (tested without Streamlit). Zone presets for each
measure are built by the ``*_zones`` functions, in display units.
"""
import math
from dataclasses import dataclass
from html import escape

from pandas import DataFrame, Timedelta

from core.conversions import celsius_to_fahrenheit, kmph_to_mph

BLUE = "#3b82f6"
SKY = "#7dd3fc"
TEAL = "#14b8a6"
GREEN = "#22c55e"
AMBER = "#f59e0b"
ORANGE = "#f97316"
RED = "#ef4444"
SLATE = "#64748b"
YELLOW = "#facc15"
NAVY = "#1e3a8a"


@dataclass(frozen=True)
class Zone:
    """A coloured stretch of a gauge, from the previous zone's end up to ``upto``."""

    upto: float
    color: str
    name: str


# --- geometry ------------------------------------------------------------------

CX, CY, R = 100.0, 100.0, 78.0
WIDTH = 16.0


def fraction(value: float, low: float, high: float, log: bool = False) -> float:
    """
    Where a value sits on the dial, from 0 (left end) to 1 (right end).

    Args:
        value (float): Value.
        low (float): Left end.
        high (float): Right end.
        log (bool): Logarithmic dial (for light, which spans many powers of ten).

    Returns:
        float: 0-1, clamped.
    """
    if log:
        low, high = math.log10(low), math.log10(high)
        value = math.log10(max(value, 10 ** low))
    if high <= low:
        return 0.0
    return min(max((value - low) / (high - low), 0.0), 1.0)


def _point(frac: float, radius: float = R) -> tuple[float, float]:
    """Point on the half circle for a dial fraction (0 left, 1 right)."""
    angle = math.pi * (1.0 - frac)
    return CX + radius * math.cos(angle), CY - radius * math.sin(angle)


def _arc(start: float, end: float, color: str) -> str:
    """An SVG arc between two dial fractions."""
    (x0, y0), (x1, y1) = _point(start), _point(end)
    return (f'<path d="M {x0:.2f} {y0:.2f} A {R} {R} 0 0 1 {x1:.2f} {y1:.2f}" fill="none" '
            f'stroke="{color}" stroke-width="{WIDTH}"/>')


def zone_of(value: float, zones: list[Zone]) -> Zone | None:
    """The zone a value falls in (the last one if above them all)."""
    for zone in zones:
        if value < zone.upto:
            return zone
    return zones[-1] if zones else None


def format_number(value: float, decimals: int = 1) -> str:
    """Format a number without a pointless ``.0``."""
    text = f"{value:,.{decimals}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def gauge_svg(value: float | None, unit: str, low: float, high: float, zones: list[Zone],
              change: float | None = None, change_text: str = "in 1 h", decimals: int = 1,
              log: bool = False, title: str = "") -> str:
    """
    Draw a gauge.

    Args:
        value (float | None): Current value in display units; None shows "--".
        unit (str): Unit shown after the value.
        low (float): Left end of the dial.
        high (float): Right end of the dial.
        zones (list[Zone]): Coloured zones, in increasing ``upto`` order.
        change (float | None): Change over the recent period (None hides it).
        change_text (str): What the period is, e.g. ``"in 1 h"``.
        decimals (int): Decimal places for the value and change.
        log (bool): Logarithmic dial.
        title (str): Accessible title.

    Returns:
        str: An ``<svg>`` element.
    """
    parts = [f'<svg viewBox="0 0 200 168" role="img" aria-label="{escape(title)}" '
             'style="width:100%;max-width:260px;display:block;margin:auto;font-family:inherit" xmlns="http://www.w3.org/2000/svg">',
             f"<title>{escape(title)}</title>"]
    start = 0.0
    for zone in zones:
        end = fraction(zone.upto, low, high, log) if math.isfinite(zone.upto) else 1.0
        if end > start:
            parts.append(_arc(start, end, zone.color))
        start = max(start, end)
    if start < 1.0:
        parts.append(_arc(start, 1.0, SLATE))
    for frac, text in ((0.0, low), (1.0, high)):
        x, _y = _point(frac)
        anchor = "start" if frac == 0 else "end"
        parts.append(f'<text x="{x - 8 if frac == 0 else x + 8:.1f}" y="{CY + 16}" font-size="10" '
                     f'text-anchor="{anchor}" fill="currentColor" opacity="0.6">{format_number(text, 0)}</text>')
    if value is None:
        parts.append(f'<text x="{CX}" y="{CY + 27}" font-size="22" text-anchor="middle" fill="currentColor">--</text>')
    else:
        frac = fraction(value, low, high, log)
        x, y = _point(frac, R - WIDTH / 2 - 6)
        parts.append(f'<line x1="{CX}" y1="{CY}" x2="{x:.2f}" y2="{y:.2f}" stroke="currentColor" '
                     'stroke-width="3" stroke-linecap="round"/>')
        parts.append(f'<circle cx="{CX}" cy="{CY}" r="5" fill="currentColor"/>')
        zone = zone_of(value, zones)
        parts.append(f'<text x="{CX}" y="{CY + 27}" font-size="20" font-weight="600" text-anchor="middle" '
                     f'fill="currentColor">{escape(format_number(value, decimals))} {escape(unit)}</text>')
        if zone:
            parts.append(f'<text x="{CX}" y="{CY + 44}" font-size="12" text-anchor="middle" fill="currentColor">'
                         f'<tspan fill="{zone.color}">●</tspan> {escape(zone.name)}</text>')
    if change is not None and value is not None:
        arrow = "▲" if change > 0 else "▼" if change < 0 else "■"
        sign = "+" if change > 0 else ""
        parts.append(f'<text x="{CX}" y="{CY + 62}" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.75">'
                     f'{arrow} {sign}{escape(format_number(change, decimals))} {escape(unit)} {escape(change_text)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def change_over(frame: DataFrame, column: str, minutes: int = 60, time_column: str = "time") -> float | None:
    """
    How much a value changed over the last ``minutes``.

    Compares the newest value with the last one at least ``minutes`` older
    (or, when readings are sparse, the oldest one within twice that).

    Args:
        frame (DataFrame): Readings with a datetime ``time_column``, any order.
        column (str): Value column.
        minutes (int): Period.
        time_column (str): Time column.

    Returns:
        float | None: Newest minus older value; None without an older reading.
    """
    data = frame[[time_column, column]].dropna().sort_values(time_column)
    if len(data) < 2:
        return None
    newest_time, newest = data.iloc[-1][time_column], data.iloc[-1][column]
    older = data[data[time_column] <= newest_time - Timedelta(minutes=minutes)]
    if older.empty:
        return None
    before_time, before = older.iloc[-1][time_column], older.iloc[-1][column]
    if newest_time - before_time > Timedelta(minutes=2 * minutes):
        return None
    return float(newest - before)


# --- zone presets (display units) ---------------------------------------------


def _temp(value_c: float, units: str) -> float:
    """A Celsius boundary in display units."""
    return celsius_to_fahrenheit(value_c, 1) if units == "US" else value_c


def outdoor_temperature_zones(units: str) -> tuple[float, float, list[Zone]]:
    """Dial range and zones for outdoor temperature: freezing, cold, cool, mild, warm, hot."""
    zones = [Zone(_temp(0, units), BLUE, "freezing"), Zone(_temp(10, units), SKY, "cold"),
             Zone(_temp(18, units), TEAL, "cool"), Zone(_temp(27, units), GREEN, "mild"),
             Zone(_temp(35, units), AMBER, "warm"), Zone(math.inf, RED, "hot")]
    return _temp(-20, units), _temp(45, units), zones


def humidity_zones(fan_on_pct: float | None = None) -> tuple[float, float, list[Zone]]:
    """
    Dial range and zones for relative humidity.

    Args:
        fan_on_pct (float | None): The greenhouse fan's humidity trigger; when
            given, the zone above it is marked as the fan zone.
    """
    if fan_on_pct is not None:
        zones = [Zone(30, AMBER, "dry"), Zone(fan_on_pct, GREEN, "OK"), Zone(math.inf, BLUE, "fan zone")]
    else:
        zones = [Zone(30, AMBER, "dry"), Zone(60, GREEN, "comfortable"), Zone(80, SKY, "humid"),
                 Zone(math.inf, BLUE, "very humid")]
    return 0.0, 100.0, zones


def wind_zones(units: str) -> tuple[float, float, list[Zone]]:
    """Dial range and zones for wind speed (calm ... gale)."""
    speed = (lambda kmh: kmph_to_mph(kmh, 1)) if units == "US" else (lambda kmh: kmh)
    zones = [Zone(speed(20), GREEN, "light"), Zone(speed(40), AMBER, "breezy"),
             Zone(speed(60), ORANGE, "strong"), Zone(math.inf, RED, "gale")]
    return 0.0, speed(80), zones


def greenhouse_temperature_zones(units: str, heater_on_c: float | None,
                                 fan_on_c: float | None) -> tuple[float, float, list[Zone]]:
    """
    Dial range and zones for the greenhouse temperature, from the automation
    triggers: below the heater trigger, OK, above the fan trigger.
    """
    heater = _temp(heater_on_c if heater_on_c is not None else 18, units)
    fan = _temp(fan_on_c if fan_on_c is not None else 32, units)
    zones = [Zone(heater, BLUE, "heater zone"), Zone(fan, GREEN, "OK"), Zone(math.inf, RED, "fan zone")]
    return _temp(0, units), _temp(45, units), zones


def light_zones() -> tuple[float, float, list[Zone]]:
    """Dial range (logarithmic, lux) and zones for light, dark ... full sun."""
    from core.light import LIGHT_LEVELS

    colors = [NAVY, SLATE, SKY, GREEN, YELLOW]
    zones = [Zone(upper, color, name) for (upper, name), color in zip(LIGHT_LEVELS, colors)]
    return 1.0, 100_000.0, zones
