"""
Calibrate the light sensor's lux estimate from one light-meter reading.

Usage (from the ``server/`` folder)::

    python -m scripts.calibrate_light 22437 350

1. Put a phone light-meter app (e.g. "Lux Light Meter") right next to the
   greenhouse light sensor, facing the same way.
2. Note the lux it shows, and at the same time the *Light (raw)* reading on
   the controller: Reports › Greenhouse Weather, *Show readings as a table*.
3. Run this with both numbers. It writes ``LDR_R10_OHMS`` to ``server/.env``;
   restart the dashboard (``sudo systemctl restart greenhouse-web``).

Daylight away from direct sun (a few hundred to a few thousand lux) gives the
best calibration. See ``core/light.py`` for the formula.
"""
import argparse
import sys

from core.light import r10_from_reading, raw_to_lux
from core.settings import ENV_FILE


def write_setting(env_file, key: str, value: str) -> None:
    """
    Put ``KEY=value`` into an env file, replacing any old value.

    Args:
        env_file (Path): ``.env`` file (created if missing).
        key (str): Setting name.
        value (str): Setting value.
    """
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    lines = [line for line in lines if not line.strip().startswith(f"{key}=")]
    lines.append(f"{key}={value}")
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None, env_file=ENV_FILE) -> int:
    """
    Command-line entry point.

    Returns:
        int: Process exit code.
    """
    parser = argparse.ArgumentParser(description="Calibrate the light sensor from one light-meter reading.")
    parser.add_argument("raw", type=float, help="the controller's raw light reading (0-65535)")
    parser.add_argument("lux", type=float, help="lux measured next to the sensor at the same time")
    args = parser.parse_args(argv)
    try:
        r10 = r10_from_reading(args.raw, args.lux)
    except ValueError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1
    before = raw_to_lux(args.raw)
    write_setting(env_file, "LDR_R10_OHMS", f"{r10:.0f}")
    print(f"Raw {args.raw:.0f} was estimated at {before:.0f} lux; now {raw_to_lux(args.raw, r10_ohms=r10):.0f} lux.")
    print(f"Wrote LDR_R10_OHMS={r10:.0f} to {env_file}. Restart the dashboard to use it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
