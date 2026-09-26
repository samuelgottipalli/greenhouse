"""
Unit conversion helpers for the greenhouse web app.

Ported from the retired Dash app (``serverside/conversions.py``). The original
helpers rounded to whole integers, which lost precision on settings round-trips
(e.g. 18.5 C -> 65 F -> 18 C). These versions return floats rounded to
``ndigits`` places.

The database stores SI values (C, km/h, mm/cm); convert only for display and
convert back before writing.
"""

KM_PER_MILE: float = 1.609344
CM_PER_INCH: float = 2.54
MM_PER_INCH: float = 25.4
COMPASS_POINTS: int = 16


def celsius_to_fahrenheit(temp_c: float, ndigits: int = 2) -> float:
    """
    Convert an absolute temperature from Celsius to Fahrenheit.

    Args:
        temp_c (float): Temperature in degrees Celsius.
        ndigits (int): Decimal places to round to.

    Returns:
        float: Temperature in degrees Fahrenheit.
    """
    return round(temp_c * 9 / 5 + 32, ndigits)


def fahrenheit_to_celsius(temp_f: float, ndigits: int = 2) -> float:
    """
    Convert an absolute temperature from Fahrenheit to Celsius.

    Args:
        temp_f (float): Temperature in degrees Fahrenheit.
        ndigits (int): Decimal places to round to.

    Returns:
        float: Temperature in degrees Celsius.
    """
    return round((temp_f - 32) * 5 / 9, ndigits)


def celsius_delta_to_fahrenheit(delta_c: float, ndigits: int = 2) -> float:
    """
    Convert a temperature *difference* (e.g. a hysteresis buffer) from C to F.

    Unlike :func:`celsius_to_fahrenheit` this does not add the 32 degree offset,
    because a 2 C buffer is a 3.6 F buffer, not a 35.6 F one.

    Args:
        delta_c (float): Temperature difference in Celsius degrees.
        ndigits (int): Decimal places to round to.

    Returns:
        float: Temperature difference in Fahrenheit degrees.
    """
    return round(delta_c * 9 / 5, ndigits)


def fahrenheit_delta_to_celsius(delta_f: float, ndigits: int = 2) -> float:
    """
    Convert a temperature *difference* (e.g. a hysteresis buffer) from F to C.

    Args:
        delta_f (float): Temperature difference in Fahrenheit degrees.
        ndigits (int): Decimal places to round to.

    Returns:
        float: Temperature difference in Celsius degrees.
    """
    return round(delta_f * 5 / 9, ndigits)


def kmph_to_mph(speed_kmph: float, ndigits: int = 2) -> float:
    """
    Convert a speed from kilometres per hour to miles per hour.

    Args:
        speed_kmph (float): Speed in km/h.
        ndigits (int): Decimal places to round to.

    Returns:
        float: Speed in mph.
    """
    return round(speed_kmph / KM_PER_MILE, ndigits)


def mph_to_kmph(speed_mph: float, ndigits: int = 2) -> float:
    """
    Convert a speed from miles per hour to kilometres per hour.

    Args:
        speed_mph (float): Speed in mph.
        ndigits (int): Decimal places to round to.

    Returns:
        float: Speed in km/h.
    """
    return round(speed_mph * KM_PER_MILE, ndigits)


def mm_to_cm(length_mm: float, ndigits: int = 2) -> float:
    """
    Convert a length from millimetres to centimetres.

    Open-Meteo reports rain, showers and precipitation in mm.

    Args:
        length_mm (float): Length in mm.
        ndigits (int): Decimal places to round to.

    Returns:
        float: Length in cm.
    """
    return round(length_mm / 10, ndigits)


def mm_to_inches(length_mm: float, ndigits: int = 2) -> float:
    """
    Convert a length from millimetres to inches.

    Args:
        length_mm (float): Length in mm.
        ndigits (int): Decimal places to round to.

    Returns:
        float: Length in inches.
    """
    return round(length_mm / MM_PER_INCH, ndigits)


def cm_to_inches(length_cm: float, ndigits: int = 2) -> float:
    """
    Convert a length from centimetres to inches.

    Open-Meteo reports snowfall in cm.

    Args:
        length_cm (float): Length in cm.
        ndigits (int): Decimal places to round to.

    Returns:
        float: Length in inches.
    """
    return round(length_cm / CM_PER_INCH, ndigits)


def inches_to_cm(length_in: float, ndigits: int = 2) -> float:
    """
    Convert a length from inches to centimetres.

    Args:
        length_in (float): Length in inches.
        ndigits (int): Decimal places to round to.

    Returns:
        float: Length in cm.
    """
    return round(length_in * CM_PER_INCH, ndigits)


def degrees_to_compass_index(degrees: float) -> int:
    """
    Map a wind direction in degrees to a 16-point compass index.

    The index is a key into ``config.wind_direction_descr`` (0 = N, 4 = E, ...).
    Values at or above 348.75 degrees wrap back to 0 (N) instead of producing an
    out-of-range index of 16.

    Args:
        degrees (float): Direction in degrees, measured clockwise from north.

    Returns:
        int: Compass index in the range 0-15.
    """
    return int(round((degrees % 360) / (360 / COMPASS_POINTS))) % COMPASS_POINTS
