# MQTT Message Contract

This is how the greenhouse controller (Pico) and the server talk. Every topic
sits under `<prefix>/<device_id>/`. The prefix is `greenhouse` by default and
is set by `mqtt_topic_prefix` on the device and `MQTT_TOPIC_PREFIX` on the
server. `device_id` is an integer that matches `devices.device_id` in the
database.

All payloads are JSON. Timestamps are UTC strings in the form
`YYYY-MM-DD HH:MM:SS`. The `ts_utc` field is `null` when the device clock has
not been set yet (NTP has not succeeded since boot); the server should then use
the time it received the message.

| Topic | Direction | Retained | QoS | Payload |
|---|---|---|---|---|
| `greenhouse/1/telemetry` | device → server | no | 0 | Sensor snapshot (below) |
| `greenhouse/1/relay/<n>/state` | device → server | **yes** | 0 | Relay state after every change |
| `greenhouse/1/status` | device → server | **yes** | 0 | `online` (plain text), or `offline` sent by the broker as the device's last will |
| `greenhouse/1/relay/set` | server → device | no | 1 | Relay command |
| `greenhouse/1/settings` | server → device | **yes** | 1 | Automation settings for local mode |
| `greenhouse/1/firmware/update` | server → device | no | 1 | Over-the-air update manifest |
| `greenhouse/1/firmware` | device → server | **yes** | 0 | Installed version and update progress |

## Telemetry

The device publishes telemetry at boot and then every `publish_interval_s`
seconds (default 300). While offline it queues the newest 48 messages and
sends them after reconnecting.

```json
{
  "device_id": 1,
  "ts_utc": "2026-09-26 19:00:00",
  "temperature_c": 21.5,
  "humidity_pct": 45.0,
  "light_raw": 30000,
  "relays": [0, 1, 0, 0, 0, 0, 0, 0],
  "uptime_s": 86400,
  "mem_free": 142336,
  "rssi_dbm": -61
}
```

- `temperature_c` and `humidity_pct` are `null` until the first good DHT22
  reading. After a failed read they keep the last good values.
- `light_raw` is the uncalibrated 16-bit ADC reading from the light sensor
  (see FINDINGS P-10).
- `relays` lists relays 1–8, where 1 means on.
- `uptime_s`, `mem_free` (free heap in bytes) and `rssi_dbm` (Wi-Fi signal; closer to 0 is
  stronger, below about -80 is weak) are the device's health. The ingest service keeps the
  latest values in `device_status`, and the Home page shows them. `mem_free` and `rssi_dbm` may be
  `null`.

## Relay state

The device publishes relay state on `relay/<n>/state` whenever relay `n`
changes, whatever caused the change: a server command or a button press on the
device. The message is retained, so a server that connects later still sees
every relay's current state.

```json
{"device_id": 1, "relay": 2, "state": 1, "source": "web", "ts_utc": "2026-09-26 19:00:03"}
```

All eight states are also re-published whenever the device's MQTT link comes up (after boot or a
reconnect). A reboot switches every relay off, and this is how the server learns about it.

`source` is one of:
- `device`: a button press on the device.
- `web` or `auto`: copied from the command that caused the change.
- `auto` is also used for the re-published states after boot or reconnect, so server automation
  (not a manual override) decides what happens next.

These values match `relay_events.source` in the database.

## Relay command

The server sends commands to `relay/set` using `core.mqtt.publish_relay_command`:

```json
{"relay": 2, "state": 1, "source": "web"}
```

- `relay`: an integer from 1 to 8.
- `state`: 1 for on, 0 for off. This sets the relay to that state; it does not
  toggle it.
- `source`: optional, `web` or `auto`. Any other value is treated as `web`.

The device ignores invalid commands. It confirms a valid command by
publishing the relay's state message, so the server should treat that state
message, not its own command, as the confirmation.

The same topic carries one other command, from the dashboard's Settings › System
(`core.mqtt.publish_controller_restart`):

```json
{"action": "restart", "source": "web"}
```

The controller (1.3.0 and later) shows "Restarting…", sends anything queued and
restarts; its status goes `offline` (last will) and back to `online`. Older
controllers ignore it. It uses this topic so the controller's existing broker
login and topic rules need no change.

## Settings and local mode

The automation service publishes the current thresholds and watering schedule, retained, whenever
they change. The device therefore gets the latest copy each time it connects, and saves it to
`settings.json` on its flash:

```json
{"fan_on_temp_c": [32.0, 2.0], "fan_on_humidity_pct": [50.0, 2.0],
 "heater_on_temp_c": [18.0, 2.0], "watering": [["06:00", 30], ["00:00", 0], ["00:00", 0], ["00:00", 0]]}
```

Each threshold is `[value, buffer]`. Each watering slot is `[local start "HH:MM", minutes]`, and 0
minutes means the slot is off.

- **Keep-alive:** the device pings every 2 minutes with a 5-minute keep-alive, so the broker
  publishes its `offline` status about 7.5 minutes after it vanishes. If the broker stays silent
  for 5 minutes, the device treats the link as dead and reconnects.
- **Local mode:** if the device's MQTT link has been down for 2 minutes, it applies the same fan,
  heater and watering rules itself (`picoside/device/local_rules.py`, checked against the server's
  rules in the tests). The LCD shows `LOCAL`. Its changes are queued as `auto` state messages
  and delivered when the link returns. Without saved settings it only enforces safety: heater
  and water off.
- **Sensor fault, always on:** if the DHT22 has given no good reading for 5 minutes, the device
  switches the heater off itself.
- **Server:** while the device reports `offline`, the automation service sends nothing (the broker
  would drop it) and the dashboard disables its switches.

## Over-the-air updates

**Update controller** on the dashboard's Controllers page publishes a manifest of the code in
`picoside/device/` (`server/core/firmware.py`) to `firmware/update`. It is not retained, so the
controller must be online:

```json
{"version": "3f9a0c1b2d4e", "name": "1.1.0", "url": "http://192.168.1.20:8081/",
 "files": [{"path": "controller.py", "sha256": "9b1c…(64 hex digits)", "size": 17342}]}
```

- `version`: the *build*: the first 12 hex digits of a SHA-256 over every file's path and hash,
  so it changes whenever any file does. (It keeps this key because 1.0.0 controllers compare it.)
- `name`: the version people read, from `picoside/device/version.py` (added in 1.1.0; 1.0.0
  controllers ignore it).
- `url`: the server's `greenhouse-firmware` service. The controller downloads
  `<url>files/<path>` for each file whose hash differs from its own copy.
- `files`: every updatable file. `boot.py`, `main.py` and the settings files are never listed,
  and the controller refuses paths outside its folder.

The controller checks every download's size and hash before changing anything, then swaps the
files in and restarts. If the new code hasn't reached the broker after 3 starts or 10 minutes,
`boot.py` restores the old files (`picoside/device/ota.py` explains the steps).

The controller reports on `firmware`, retained, each time its link comes up and during an update:

```json
{"device_id": 1, "version": "3f9a0c1b2d4e", "name": "1.1.0", "state": "running", "detail": "",
 "ts_utc": "2026-09-27 10:00:00"}
```

- `version`: the installed build, or `unknown` for code copied by hand (the dashboard then
  compares version names instead).
- `name`: the installed version name (from 1.1.0; a report without one comes from 1.0.0).
- `state`: `running`, `updating`, `restarting`, `updated` (first report after a successful
  update), `failed` (nothing changed) or `rolled_back`.
- `detail`: a short explanation, e.g. why an update failed.

## How the server stores these messages

`services/ingest.py` subscribes to `<prefix>/+/telemetry`,
`<prefix>/+/relay/+/state`, `<prefix>/+/status` and `<prefix>/+/firmware`:

- **Telemetry** goes to `sensor_readings`, one row per non-null value
  (`temperature_c` becomes `temperature`, `humidity_pct` becomes `humidity`,
  `light_raw` stays `light_raw`). Replayed messages from the device's
  offline queue are ignored.
- **State** goes to `relay_events` only when it differs from the last logged
  state. The web app and automation log their own commands, so the device's
  echo is not stored twice.
- **Status** goes to `device_status`.
- **Firmware** goes to `device_status` too (`firmware_version`, `firmware_name`,
  `firmware_state`, `firmware_detail`, `firmware_utc`).

The contract is checked end to end in
`tests/picoside/test_contract_with_server.py`.
