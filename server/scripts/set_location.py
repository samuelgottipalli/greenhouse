"""
Set the greenhouse's location (for the outdoor weather and sunrise/sunset),
as Settings › Location does. The installer runs it; it also works by hand.

Run from ``server/``::

    python -m scripts.set_location --latitude 39.5349 --longitude -119.7527 --name "Sparks, Nevada"

The weather collector picks the change up at its next reading.
"""
import argparse
import sys

from core import places


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Set the greenhouse's location.")
    parser.add_argument("--latitude", type=float, required=True)
    parser.add_argument("--longitude", type=float, required=True)
    parser.add_argument("--name", default="")
    parser.add_argument("--timezone", default="")
    args = parser.parse_args(argv)
    place = {"name": args.name.strip() or f"{args.latitude:.4f}, {args.longitude:.4f}",
             "latitude": args.latitude, "longitude": args.longitude, "timezone": args.timezone or None}
    try:
        stored = places.save(place)
    except ValueError as err:
        print(f"Error: {err}")
        return 2
    if not stored:
        print("Error: the location couldn't be stored (is the database set up?)")
        return 1
    print(f"Location set to {place['name']} ({args.latitude:.4f}, {args.longitude:.4f}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
