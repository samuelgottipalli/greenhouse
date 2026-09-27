"""
Register another greenhouse controller.

Usage (from the ``server/`` folder)::

    python -m scripts.add_device 2 picow2

Adds the device with relays 1-8 (water, fan, heater, light, spares) and the
default thresholds and watering schedule, then prints the Mosquitto ACL block
and the settings its ``config.json`` needs. The dashboard shows a controller
picker in the sidebar once there are two or more, and the automation service
starts automating the new one on its next pass.
"""
import argparse
import sqlite3
import sys

from core import migrations, settings

ACL_TEMPLATE = """user greenhouse-device-{id}
topic write {prefix}/{id}/telemetry
topic write {prefix}/{id}/status
topic write {prefix}/{id}/relay/+/state
topic read {prefix}/{id}/relay/set
topic read {prefix}/{id}/settings"""


def add_device(device_id: int, name: str, path=None) -> None:
    """
    Create a device with its relays and default settings, in one transaction.

    Args:
        device_id (int): New device ID (a positive integer).
        name (str): Unique name, e.g. ``"picow2"``.
        path (Path | None): Database file; defaults to the configured one.

    Raises:
        ValueError: If the ID or name is invalid or already used.
    """
    if device_id < 1 or not name.strip():
        raise ValueError("Use a positive device ID and a non-empty name")
    conn = migrations.connect(path or settings.sqlite_path(settings.DB_URL))
    try:
        conn.execute("BEGIN")
        try:
            migrations.seed_device(conn, device_id, name.strip())
            conn.execute("COMMIT")
        except sqlite3.IntegrityError as err:
            conn.execute("ROLLBACK")
            raise ValueError(f"Device {device_id} or name {name!r} already exists") from err
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    """
    Command-line entry point.

    Returns:
        int: Process exit code.
    """
    parser = argparse.ArgumentParser(description="Register another greenhouse controller.")
    parser.add_argument("device_id", type=int)
    parser.add_argument("name")
    args = parser.parse_args(argv)
    try:
        add_device(args.device_id, args.name)
    except ValueError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1
    print(f"Added device {args.device_id} ({args.name}).\n")
    print("1. Add to /etc/mosquitto/greenhouse.acl, then restart mosquitto:\n")
    print(ACL_TEMPLATE.format(id=args.device_id, prefix=settings.MQTT_TOPIC_PREFIX))
    print(f"\n2. Create its broker login:  sudo mosquitto_passwd /etc/mosquitto/greenhouse.passwd "
          f"greenhouse-device-{args.device_id}")
    print(f"3. Run picoside/setup_config.py for the new Pico: Device ID {args.device_id}, MQTT user "
          f"greenhouse-device-{args.device_id} (it sets a unique MQTT client ID).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
