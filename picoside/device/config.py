"""
Load and check ``config.json`` for the greenhouse controller.

``config.json`` holds Wi-Fi and broker credentials, so it is not committed.
It is written by the controller's setup hotspot (``provision.py``), by the
desktop installer, or on a computer with ``python picoside/setup_config.py``
and then copied to the Pico. Any key missing from the
file falls back to ``DEFAULTS``. Files in the original format (``relay1_pin``
... keys and ``timezone_offset`` in hours) are converted on load.

``standalone`` (set from the setup page) means there is no server: the
controller runs its own rules all the time, and Wi-Fi, if set, only keeps
the clock right.

The defaults favour low power (for running on a battery): MQTT keep-alive
5 min with a ping every 2 min, Wi-Fi power-save mode, sensors read every
minute, a 100 ms main loop and the LCD backlight off after 60 s without a
button press (``backlight_timeout_s``: 0 keeps it on).
"""
import json

DEFAULTS = {
    "device_id": 1,
    "wifi_ssid": "",
    "wifi_password": "",
    "wifi_timeout_s": 20,
    "wifi_power_save": True,
    "standalone": False,
    "mqtt_broker": "",
    "mqtt_port": 1883,
    "mqtt_user": None,
    "mqtt_password": None,
    "mqtt_tls": False,
    "mqtt_ca": "",
    "mqtt_client_id": "greenhouse_pico",
    "mqtt_topic_prefix": "greenhouse",
    "mqtt_keepalive_s": 300,
    "mqtt_ping_s": 120,
    "timezone": "UTC",
    "utc_offset_minutes": 0,
    "dst_rule": "none",
    "ntp_host": "pool.ntp.org",
    "ntp_resync_hours": 24,
    "sensor_interval_s": 60,
    "publish_interval_s": 300,
    "loop_ms": 100,
    "watchdog": True,
    "dht_pin": 16,
    "ldr_pin": 28,
    "ldr_inverted": False,
    "relay_pins": [17, 18, 19, 20, 21, 22, 26, 27],
    "relay_active_low": False,
    "relay_names": ["water", "fan", "heater", "light", "spare5", "spare6", "spare7", "spare8"],
    "button_toggle_pin": 15,
    "button_relay_pins": [14, 13, 12, 11],
    "lcd_sda_pin": 0,
    "lcd_scl_pin": 1,
    "lcd_address": 63,
    "backlight_timeout_s": 60,
}

PLACEHOLDER_BROKERS = ("", "YOUR_MQTT_BROKER")


def upgrade_legacy_keys(raw):
    """
    Convert a config in the original format to the current keys, in place.

    * ``relay1_pin`` ... ``relay8_pin`` -> ``relay_pins``
    * ``button_relay1_pin`` ... ``button_relay4_pin`` -> ``button_relay_pins``
    * ``timezone_offset`` (hours) -> ``utc_offset_minutes``
    * GPS pins and the old fixed topics are dropped.

    Args:
        raw (dict): Parsed JSON.

    Returns:
        dict: The same dict.
    """
    if "relay1_pin" in raw:
        raw["relay_pins"] = [raw.pop("relay{}_pin".format(n)) for n in range(1, 9)]
    if "button_relay1_pin" in raw:
        raw["button_relay_pins"] = [raw.pop("button_relay{}_pin".format(n)) for n in range(1, 5)]
    if "timezone_offset" in raw:
        raw["utc_offset_minutes"] = int(raw.pop("timezone_offset") * 60)
    for key in ("gps_tx_pin", "gps_rx_pin", "mqtt_topic_publish", "mqtt_topic_subscribe"):
        raw.pop(key, None)
    return raw


def load_config(filename="config.json"):
    """
    Read the config file and fill in defaults.

    Args:
        filename (str): Path to the JSON file.

    Returns:
        dict: Complete configuration. If the file is missing or invalid, the
        defaults alone (which have no Wi-Fi or broker settings).
    """
    try:
        with open(filename, "r") as f:
            raw = json.load(f)
    except (OSError, ValueError) as err:
        print("Error loading config:", err)
        raw = {}
    config = dict(DEFAULTS)
    config.update(upgrade_legacy_keys(raw))
    return config


def save_config(config, filename="config.json"):
    """
    Write the configuration, replacing the file in one step.

    The new file is written next to the old one and then renamed over it, so
    a power cut while saving leaves either the old or the new settings.

    Args:
        config (dict): Complete configuration.
        filename (str): Path to the JSON file.
    """
    import os

    temporary = filename + ".tmp"
    with open(temporary, "w") as f:
        json.dump(config, f)
    try:
        os.rename(temporary, filename)  # replaces the old file on the Pico (LittleFS)
    except OSError:  # Windows won't rename over a file (only matters in tests)
        os.remove(filename)
        os.rename(temporary, filename)


def config_problems(config):
    """
    List settings that will stop the controller from working fully.

    Args:
        config (dict): Output of :func:`load_config`.

    Returns:
        list[str]: Short messages (fit on the LCD); empty if all is well.
    """
    problems = []
    if not config["wifi_ssid"] and not config["standalone"]:
        problems.append("No Wi-Fi SSID set")
    if config["mqtt_broker"] in PLACEHOLDER_BROKERS and not config["standalone"]:
        problems.append("No MQTT broker set")
    if config["dst_rule"] not in ("none", "us", "eu"):
        problems.append("Bad dst_rule")
    if len(config["relay_pins"]) != 8:
        problems.append("Need 8 relay_pins")
    if len(config["button_relay_pins"]) != 4:
        problems.append("Need 4 button pins")
    if not 0 < config["mqtt_ping_s"] < config["mqtt_keepalive_s"]:
        problems.append("Ping must be < keepalive")
    return problems
