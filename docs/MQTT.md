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
  "uptime_s": 86400
}
```

- `temperature_c` and `humidity_pct` are `null` until the first good DHT22
  reading. After a failed read they keep the last good values.
- `light_raw` is the uncalibrated 16-bit ADC reading from the light sensor
  (see FINDINGS P-10).
- `relays` lists relays 1–8, where 1 means on.

## Relay state

The device publishes relay state on `relay/<n>/state` whenever relay `n`
changes, whatever caused the change: a server command or a button press on the
device. The message is retained, so a server that connects later still sees
every relay's current state.

```json
{"device_id": 1, "relay": 2, "state": 1, "source": "web", "ts_utc": "2026-09-26 19:00:03"}
```

`source` is one of:
- `device`: a button press on the device.
- `web` or `auto`: copied from the command that caused the change.

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

## How the server stores these messages

`services/ingest.py` subscribes to `<prefix>/+/telemetry`,
`<prefix>/+/relay/+/state` and `<prefix>/+/status`:

- **Telemetry** goes to `sensor_readings`, one row per non-null value
  (`temperature_c` becomes `temperature`, `humidity_pct` becomes `humidity`,
  `light_raw` stays `light_raw`). Replayed messages from the device's
  offline queue are ignored.
- **State** goes to `relay_events` only when it differs from the last logged
  state. The web app and automation log their own commands, so the device's
  echo is not stored twice.
- **Status** goes to `device_status`.

The contract is checked end to end in
`tests/picoside/test_contract_with_server.py`.
