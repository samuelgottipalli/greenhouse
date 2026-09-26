"""
Create ``picoside/device/config.json`` for the greenhouse controller.

Run on a computer (not the Pico) before the first upload, or whenever Wi-Fi,
broker or time zone change::

    python picoside/setup_config.py

It asks for Wi-Fi, MQTT broker, device ID and time zone, keeping the current
answers (or the example defaults) when you press Enter. The time zone is asked
as an IANA name such as ``America/Los_Angeles``. The device can't hold the full
time-zone database, so this works out the standard UTC offset and which
daylight-saving rule (``us``, ``eu`` or ``none``) matches, by checking every day
of the year against Python's ``zoneinfo``.

Then copy the ``device/`` folder to the Pico, e.g.
``mpremote cp -r picoside/device/. :``.
"""
import getpass
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

DEVICE_DIR = Path(__file__).resolve().parent / "device"
EXAMPLE_FILE = DEVICE_DIR / "config.example.json"
CONFIG_FILE = DEVICE_DIR / "config.json"

sys.path.insert(0, str(DEVICE_DIR))
from clock import DST_RULES, utc_offset_minutes  # noqa: E402  (device code, pure Python)


def timezone_settings(name: str, year: int | None = None) -> tuple[dict, str | None]:
    """
    Derive the device's time-zone settings from an IANA zone name.

    Args:
        name (str): e.g. ``"America/Los_Angeles"``.
        year (int | None): Year to check the rules against (default: this year).

    Returns:
        tuple[dict, str | None]: Config keys ``timezone``,
        ``utc_offset_minutes`` and ``dst_rule``, and a warning if no rule
        reproduces the zone exactly (the device clock will then be an hour off
        for part of the year).

    Raises:
        ZoneInfoNotFoundError: If the zone name is unknown.
    """
    zone = ZoneInfo(name)
    year = year or datetime.now().year
    start = datetime(year, 1, 1, 12, tzinfo=timezone.utc)
    moments = [start + timedelta(days=d) for d in range(365)]
    actual = [int(m.astimezone(zone).utcoffset().total_seconds() // 60) for m in moments]
    standard = min(actual)
    for rule in DST_RULES:
        if all(utc_offset_minutes(int(m.timestamp()), standard, rule) == a for m, a in zip(moments, actual)):
            return {"timezone": name, "utc_offset_minutes": standard, "dst_rule": rule}, None
    warning = (f"{name} uses a daylight-saving rule the device does not know; "
               "the LCD clock will show standard time all year.")
    return {"timezone": name, "utc_offset_minutes": standard, "dst_rule": "none"}, warning


def load_base() -> dict:
    """
    Load the existing config, or the example if there is none.

    Returns:
        dict: Starting values for the prompts.
    """
    source = CONFIG_FILE if CONFIG_FILE.exists() else EXAMPLE_FILE
    return json.loads(source.read_text(encoding="utf-8"))


def build_config(base: dict, answers: dict) -> tuple[dict, str | None]:
    """
    Merge answers into a config and fill in the time-zone keys.

    Args:
        base (dict): Existing or example config.
        answers (dict): New values; must include ``timezone``.

    Returns:
        tuple[dict, str | None]: The config to write, and any time-zone warning.
    """
    config = dict(base)
    config.update({k: v for k, v in answers.items() if k != "timezone"})
    tz, warning = timezone_settings(answers["timezone"])
    config.update(tz)
    for key in ("mqtt_user", "mqtt_password"):
        if config.get(key) == "":
            config[key] = None
    return config, warning


def ask(prompt: str, default, secret: bool = False) -> str:
    """
    Prompt for a value, returning the default when the answer is empty.

    Args:
        prompt (str): Question.
        default: Value kept on Enter.
        secret (bool): Hide input and the current value.

    Returns:
        str: The answer or the default (as text).
    """
    shown = "(unchanged)" if secret and default else default
    question = f"{prompt} [{shown if shown is not None else ''}]: "
    answer = getpass.getpass(question) if secret else input(question)
    return answer.strip() or ("" if default is None else str(default))


def main() -> int:
    """
    Interactive entry point.

    Returns:
        int: Process exit code.
    """
    base = load_base()
    print(f"Writing {CONFIG_FILE}. Press Enter to keep the value in brackets.\n")
    answers = {
        "wifi_ssid": ask("Wi-Fi network name", base.get("wifi_ssid")),
        "wifi_password": ask("Wi-Fi password", base.get("wifi_password"), secret=True),
        "mqtt_broker": ask("MQTT broker host or IP", base.get("mqtt_broker")),
        "mqtt_port": int(ask("MQTT broker port", base.get("mqtt_port", 1883))),
        "mqtt_user": ask("MQTT username (blank for none)", base.get("mqtt_user")),
        "mqtt_password": ask("MQTT password (blank for none)", base.get("mqtt_password"), secret=True),
        "device_id": int(ask("Device ID (matches the server database)", base.get("device_id", 1))),
    }
    while True:
        name = ask("Time zone (IANA name, e.g. America/Los_Angeles)", base.get("timezone", "UTC"))
        if name in available_timezones():
            break
        print(f"  Unknown time zone {name!r}; try e.g. Europe/London or America/New_York.")
    answers["timezone"] = name
    try:
        config, warning = build_config(base, answers)
    except ZoneInfoNotFoundError as err:
        print(f"Error: {err}")
        return 1
    if warning:
        print(f"Warning: {warning}")
    CONFIG_FILE.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"\nSaved. Time zone {config['timezone']}: UTC{config['utc_offset_minutes'] / 60:+g} h, "
          f"daylight saving rule '{config['dst_rule']}'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
