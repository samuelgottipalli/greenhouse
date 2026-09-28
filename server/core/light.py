"""
Turn the controller's raw light reading into an estimate in lux.

The controller reports the light sensor (an LDR) as a raw 16-bit number,
0-65535, higher when brighter. With the usual wiring (the LDR from 3.3 V to
the analogue pin and a fixed resistor from the pin to ground) the reading
gives the LDR's resistance, and an LDR's resistance follows a power law in
the light falling on it::

    R_ldr = R_fixed * (65535 / raw - 1)
    lux   = 10 * (R_ldr / R10) ** (-1 / gamma)

``R10`` is the LDR's resistance at 10 lux and ``gamma`` its slope; both vary
between parts, so the result is an *estimate* (shown as "≈ lux"). The
defaults suit a common GL5528 with a 10 kΩ resistor; ``LDR_FIXED_OHMS``,
``LDR_R10_OHMS`` and ``LDR_GAMMA`` in ``server/.env`` override them, and
``python -m scripts.calibrate_light <raw> <lux>`` sets ``LDR_R10_OHMS`` from one
reading taken next to a phone light-meter app.

Stored readings stay raw (``light_raw``); only the display is converted.
"""
from core import settings

RAW_MAX = 65535
LUX_MAX = 120_000.0  # brighter than full sun: the sensor is saturated

# Upper bound (lux) and a plain-words name for each light level, darkest first.
LIGHT_LEVELS: list[tuple[float, str]] = [
    (10.0, "dark"),
    (200.0, "dim"),
    (2_000.0, "overcast"),
    (20_000.0, "daylight"),
    (float("inf"), "full sun"),
]


def ldr_resistance(raw: float, fixed_ohms: float) -> float | None:
    """
    Work out the LDR's resistance from a raw reading.

    Args:
        raw (float): Raw reading, 0-65535 (higher is brighter).
        fixed_ohms (float): The fixed resistor.

    Returns:
        float | None: Ohms; None when the reading is 0 (no light, or no
        sensor) and the resistance is effectively infinite.
    """
    if raw <= 0:
        return None
    raw = min(float(raw), RAW_MAX - 0.5)
    return fixed_ohms * (RAW_MAX / raw - 1)


def raw_to_lux(raw: float, fixed_ohms: float | None = None, r10_ohms: float | None = None,
               gamma: float | None = None) -> float:
    """
    Estimate the light level in lux.

    Args:
        raw (float): Raw reading, 0-65535.
        fixed_ohms (float | None): Fixed resistor (default ``settings.LDR_FIXED_OHMS``).
        r10_ohms (float | None): LDR resistance at 10 lux (default ``settings.LDR_R10_OHMS``).
        gamma (float | None): LDR slope (default ``settings.LDR_GAMMA``).

    Returns:
        float: Estimated lux, 0 to ``LUX_MAX``.
    """
    fixed_ohms = fixed_ohms or settings.LDR_FIXED_OHMS
    r10_ohms = r10_ohms or settings.LDR_R10_OHMS
    gamma = gamma or settings.LDR_GAMMA
    resistance = ldr_resistance(raw, fixed_ohms)
    if resistance is None:
        return 0.0
    if resistance <= 0:
        return LUX_MAX
    return min(10.0 * (resistance / r10_ohms) ** (-1.0 / gamma), LUX_MAX)


def round_lux(lux: float) -> float:
    """
    Round lux sensibly for display: one decimal below 10, whole numbers
    below 1000, else to the nearest 10.

    Args:
        lux (float): Lux.

    Returns:
        float: Rounded value.
    """
    if lux < 10:
        return round(lux, 1)
    if lux < 1000:
        return float(round(lux))
    return float(round(lux, -1))


def light_level_name(lux: float) -> str:
    """
    Describe a light level in words.

    Args:
        lux (float): Lux.

    Returns:
        str: ``"dark"``, ``"dim"``, ``"overcast"``, ``"daylight"`` or ``"full sun"``.
    """
    for upper, name in LIGHT_LEVELS:
        if lux < upper:
            return name
    return LIGHT_LEVELS[-1][1]


def r10_from_reading(raw: float, lux: float, fixed_ohms: float | None = None, gamma: float | None = None) -> float:
    """
    Calibrate: the ``R10`` that makes a raw reading come out as a known lux.

    Args:
        raw (float): Raw reading taken at the same time as ``lux``.
        lux (float): Light level measured with a light meter (e.g. a phone app).
        fixed_ohms (float | None): Fixed resistor (default from settings).
        gamma (float | None): LDR slope (default from settings).

    Returns:
        float: Ohms.

    Raises:
        ValueError: If the reading is out of range or the lux is not positive.
    """
    fixed_ohms = fixed_ohms or settings.LDR_FIXED_OHMS
    gamma = gamma or settings.LDR_GAMMA
    if not 0 < raw < RAW_MAX or lux <= 0:
        raise ValueError("Use a raw reading between 1 and 65534 and a lux value above 0.")
    return ldr_resistance(raw, fixed_ohms) * (lux / 10.0) ** gamma
