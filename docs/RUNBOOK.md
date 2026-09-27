# Runbook: Connecting the Pico W

Step-by-step setup to bring the greenhouse online end to end: server, MQTT broker, services, and
the Pico W controller. Work through the steps in order. Each ends with a **Check** you can see or
run; don't move on until it passes. The [sign-off checklist](#9-sign-off-checklist) at the end
records the hardware checks the plan still needs (PLAN 1.6, 1.7, 2.2; FINDINGS P-03).

Commands marked **server$** run on the always-on Linux machine (e.g. a Raspberry Pi). Commands
marked **pc$** run on the computer the Pico is plugged into by USB. They can be the same machine.

---

## 0. Before you start

**You need**

- Raspberry Pi Pico **W** (the wireless one) with the greenhouse board: DHT22, LDR, 20x4 I2C LCD,
  8-channel relay board, 5 buttons.
- A Linux machine that stays on (Raspberry Pi OS Bookworm or newer, Debian or Ubuntu), with
  Python 3.11+ and SQLite 3.37+ (`python3 -c "import sqlite3; print(sqlite3.sqlite_version)"`).
- A 2.4 GHz Wi-Fi network. **The Pico W cannot use 5 GHz.**
- A micro-USB data cable (not charge-only).

**Security first (FINDINGS SEC-01).** The old Wi-Fi password is in this repository's git
history. Change your Wi-Fi password on the router now, and use the new one in step 6.

**Relays off.** Until step 8 is complete, leave the heater and pump unplugged from the relay
board (or switch off their supply). Relay clicks and LEDs are enough for testing.

---

## 1. Server: code, settings, database

```bash
server$ git clone https://github.com/samuelgottipalli/greenhouse.git
server$ cd greenhouse
server$ python3 -m venv venv
server$ venv/bin/pip install -r server/requirements.txt
server$ cp server/.env.example server/.env
server$ nano server/.env          # TIMEZONE, LATITUDE, LONGITUDE; MQTT_* are filled in step 3
server$ cd server
server$ ../venv/bin/python -m scripts.upgrade_db
server$ ../venv/bin/python -m scripts.set_password
```

If you are moving an existing `greenhouse.db`, copy it to `server/data/greenhouse.db` **before**
running `upgrade_db`. It is backed up and upgraded in place.

**Check:** `upgrade_db` prints `Created …` or `… already at schema version 3`. Run
`../venv/bin/python -m streamlit run app.py`, open `http://<server-ip>:8501`, log in, and see the
Home page (Controller: Unknown). Stop it with Ctrl+C; step 4 runs it as a service.

---

## 2. MQTT broker (Mosquitto), locked down

```bash
server$ sudo apt install mosquitto mosquitto-clients
server$ sudo cp ~/greenhouse/deploy/mosquitto/greenhouse.conf /etc/mosquitto/conf.d/
server$ sudo cp ~/greenhouse/deploy/mosquitto/greenhouse.acl  /etc/mosquitto/
server$ sudo mosquitto_passwd -c /etc/mosquitto/greenhouse.passwd greenhouse-server
server$ sudo mosquitto_passwd    /etc/mosquitto/greenhouse.passwd greenhouse-device-1
server$ sudo chown mosquitto: /etc/mosquitto/greenhouse.passwd /etc/mosquitto/greenhouse.acl
server$ sudo chmod 600 /etc/mosquitto/greenhouse.passwd /etc/mosquitto/greenhouse.acl
server$ sudo systemctl restart mosquitto
```

Write both passwords down; they're needed in steps 3 and 6. `-c` creates the file, so use it only
for the first account.

**Check:** anonymous access is refused, and the server account works:

```bash
server$ mosquitto_pub -h localhost -t greenhouse/test -m hi
#   -> "Connection error: Connection Refused: not authorised."
server$ mosquitto_sub -h localhost -u greenhouse-server -P '<server password>' -t 'greenhouse/#' -v
#   -> waits quietly (leave this running in a second terminal for the next steps)
```

---

## 3. Server MQTT settings

In `server/.env` set:

```ini
MQTT_HOST=localhost
MQTT_PORT=1883
MQTT_USERNAME=greenhouse-server
MQTT_PASSWORD=<server password>
MQTT_TOPIC_PREFIX=greenhouse
DEVICE_ID=1
```

---

## 4. Server services

```bash
server$ cd ~/greenhouse
server$ sudo venv/bin/python deploy/install_services.py --user $USER --enable
server$ systemctl status 'greenhouse-*'
```

This installs and starts `greenhouse-ingest`, `greenhouse-automation`, `greenhouse-weather` and
`greenhouse-web`. Each restarts 5 s after a crash and starts at boot. It also enables
`greenhouse-retention.timer`, which rolls readings older than 90 days into hourly averages every
night at 03:30. Logs: `journalctl -u greenhouse-ingest -f`.

**Check:** all four are `active (running)`, and `systemctl list-timers greenhouse-retention.timer`
shows the next 03:30 run. The ingest log shows `Connected to localhost:1883`
and no `not authorised`. Within 15 minutes the Weather Data page shows today's weather.

---

## 5. Pico W: MicroPython and tools

1. Download the **RPI_PICO_W** firmware (1.22 or newer) from
   <https://micropython.org/download/RPI_PICO_W/>.
2. Hold **BOOTSEL** while plugging the Pico into USB. It appears as a drive called `RPI-RP2`.
   Copy the `.uf2` file onto it; the Pico reboots.
3. On the PC:

```bash
pc$ pip install mpremote
pc$ mpremote connect list        # the Pico shows up as a USB serial port
```

**Check:** `mpremote exec "import sys; print(sys.implementation)"` prints `micropython`.

---

## 6. Controller configuration

```bash
pc$ python picoside/setup_config.py
```

| Question | Answer |
|---|---|
| Wi-Fi network name / password | Your **2.4 GHz** network and the **new** password (step 0) |
| MQTT broker host or IP | The server's LAN IP, e.g. `192.168.1.20` (not `localhost`) |
| MQTT broker port | `1883` |
| MQTT username / password | `greenhouse-device-1` and its password from step 2 |
| Device ID | `1` |
| Time zone | e.g. `America/Los_Angeles` |

This writes `picoside/device/config.json`, which is git-ignored and never committed. For the
first power-up only, open that file and set `"watchdog": false`. With the watchdog on, stopping
the program from the REPL resets the board 8 seconds later, which makes debugging painful.
Step 8 turns it back on.

---

## 7. Copy the code and first boot

```bash
pc$ cd picoside/device
pc$ mpremote cp -r . :
pc$ mpremote ls :            # main.py, controller.py, net.py, ..., config.json, lib/
pc$ mpremote reset
pc$ mpremote repl            # watch the console; Ctrl+] to leave
```

**Check (LCD):** in order,

1. `Initializing.. This may take a moment...`
2. `Connecting to WiFi...`
3. `WiFi connected. Syncing clock...`
4. `Connecting to MQTT...`
5. The main screen: local date and time, `Temp: 21.5C`, `Hum:  45.0%`, `Up   5s OK`.

A `Config: …` message before step 1 means `config.json` is incomplete (see Troubleshooting).
`NoWiFi` or `NoMQTT` in the bottom line tells you which link is down; the device keeps
retrying.

**Check (broker):** the `mosquitto_sub` terminal from step 2 shows, within seconds:

```
greenhouse/1/status online
greenhouse/1/telemetry {"device_id": 1, "ts_utc": "...", "temperature_c": ..., ...}
```

---

## 8. End-to-end checks

Do these with the dashboard open. Each maps to a sign-off line in step 9.

| # | Do this | Expect |
|---|---|---|
| a | Open **Home** | Controller **Online**, readings **Fresh** |
| b | Open **Reports › Greenhouse Weather** | Temperature, humidity and light match the LCD (±1 reading) |
| c | **Control › Remote Control**: turn the **Fan** on | Relay 2 clicks within ~2 s; LCD shows `Relay 2: fan` / `State: On`; toggle stays on |
| d | Turn the fan off again | Relay releases; Home shows Fan Off (web) |
| e | Press relay button **1** once on the device | Relay 1 (water) toggles after ~0.4 s; Home shows Water (device) |
| f | Double-press button **1** quickly | Relay **5** toggles, relay 1 does not |
| g | Press the screen button | LCD cycles Relay 1 … Relay 8, then back to main |
| h | Hold button 1 and press the screen button | LCD shows `IP address:` and the Pico's IP; relay 1 unchanged |
| i | Stop the broker for 4 min: `sudo systemctl stop mosquitto`, then `start` | LCD shows `NoMQTT`, then `NoMQTT LOCAL` after 2 min; Remote Control switches are disabled; after `start`, `OK` again, Home goes Online, and the readings from the outage appear in the 24 h chart |
| i2 | During an outage (as in i), warm or cool the sensor past the heater trigger | Relay 3 follows the heater rule on its own (local mode); after reconnecting Home shows the change as (auto) |
| i3 | Unplug the DHT22 data wire with the heater on | Within ~5.5 min relay 3 switches off by itself, even with the network up |
| j | **Greenhouse Settings**: set "Turn on heater at" just above the current temperature, then Save | Within ~5 s relay 3 clicks and Home shows Heater On (auto). Put the setting back afterwards. |
| k | Power-cycle the Pico | Boots to the main screen without help; all relays start **off** |

When all pass:

1. Set `"watchdog": true` in `config.json`, then run `mpremote cp config.json :` and
   `mpremote reset`.
2. Reconnect the heater and pump loads.

If the relays switch **on** when the Pico shows Off, the board is active-low. Set
`"relay_active_low": true` in `config.json` before connecting any load.

---

## 9. Sign-off checklist

Copy this into an issue or note and tick it off. Items marked ⏳ need time to pass.

- [ ] 0: Wi-Fi password changed (SEC-01)
- [ ] 2: anonymous MQTT refused
- [ ] 4: four services running and surviving `sudo reboot`; Home shows all services **OK**
- [ ] 4: `sudo systemctl kill -s STOP greenhouse-automation` (freeze it): within ~2 min the watchdog restarts it and Home shows it OK again
- [ ] 7: device boots to `OK`; status and telemetry seen on the broker
- [ ] 8a–b: Home Online/Fresh; indoor values match the LCD
- [ ] 8c–d: web toggle moves the relay and the state is confirmed (P-03, PLAN 2.2)
- [ ] 8e–h: buttons, double press, screens and IP combo (P-11)
- [ ] 8i: recovers from a broker outage; queued readings arrive (P-05)
- [ ] 8i2–i3: local mode and the sensor-fault heater cut-off work on the hardware (P-15)
- [ ] 8j: automation switches the heater (source auto)
- [ ] 8k: relays off after a power cycle
- [ ] ⏳ LCD clock still correct 48 h after boot, including across midnight (P-02, PLAN 1.7)
- [ ] ⏳ 24 h: at least 285 of 288 expected telemetry rows stored (PLAN 2.3)
- [ ] ⏳ 7 days: no hang or reboot loop, with at least one Wi-Fi outage; `telemetry_report --hours 168` at 99 % or more (PLAN 3.2; simulated in `tests/picoside/test_soak.py`)
- [ ] ⏳ Next morning: `journalctl -u greenhouse-retention` shows a successful 03:30 run (PLAN 3.4)
- [ ] Watchdog re-enabled; loads reconnected

Check 24 hours of telemetry on the server (exit code 0 means at least 99 % arrived):

```bash
server$ cd ~/greenhouse/server && ../venv/bin/python -m scripts.telemetry_report
Device 1, last 24 h: 287 of 288 expected readings (99.7%)
```

---

## Health checks

What watches what, and how often:

| Where | Check | Interval | What happens |
|---|---|---|---|
| Pico | Hardware watchdog | fed every loop (~50 ms) | If the program hangs for 8 s the board resets |
| Pico | Wi-Fi / MQTT link | every loop | Reconnects with backoff from 2 s up to 5 min |
| Pico | MQTT keep-alive | ping every 30 s | If the device goes silent, the broker publishes its `offline` status after ~90 s |
| Pico | Sensors | every 30 s | No good DHT22 reading for 5 min: heater off |
| Pico | Link lost | continuous | After 2 min offline, runs the rules itself (`LOCAL` on the LCD) |
| Pico | Clock | daily (every 5 min until the first success) | NTP re-sync |
| Pico → server | Health report | every 5 min, in telemetry | Uptime, free memory and Wi-Fi signal shown on Home |
| Server | Service heartbeats | each pass (automation 5 s, ingest 10 s, weather 10 s); stored every 30 s | Home shows OK / Degraded / Down (no beat for 2 min) |
| Server | systemd watchdog | `WatchdogSec=120` on ingest, automation, weather | A service that stops beating is killed and restarted |
| Server | systemd restart | on exit | A crashed service restarts after 5 s |
| Server | Automation data checks | every 5 s | Readings older than 15 min: heater off; controller offline: automation stands back |

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| LCD `Config: No Wi-Fi SSID set` / `No MQTT broker set` | `config.json` missing or incomplete on the Pico | Re-run step 6, then `mpremote cp config.json :` |
| Stuck on `Connecting to WiFi...` then `WiFi unavailable, will retry.` | 5 GHz network, wrong password, or out of range | Use 2.4 GHz; check the password; move closer |
| Bottom line `NoMQTT` | Broker IP wrong, mosquitto down, or wrong device password | `mosquitto_sub` from the PC with the device account; check the REPL for `MQTT connect failed: …` |
| REPL shows `MQTT connect failed: 5` | Not authorised: username or password wrong | Recreate with `mosquitto_passwd`; re-run step 6 |
| Broker gets telemetry but Home stays **Unknown** / no readings | Ingest service not running or wrong server credentials | `journalctl -u greenhouse-ingest -f`; check `MQTT_*` in `server/.env` |
| Web toggle snaps back / relay doesn't move | Device offline, or ACL blocks the command | Home shows Online? Check `greenhouse.acl` has `topic read greenhouse/1/relay/set` |
| `Clock not set` on the LCD | NTP blocked or no internet | The device retries every 5 min; check the router allows NTP (UDP 123) |
| Clock off by exactly 1 h | Time zone with an unsupported DST rule | `setup_config.py` warns about this; the LCD shows standard time all year |
| Home: a service shows **Down** | It has not sent a heartbeat for 2 min (stopped, hung or failing every pass); systemd should already be restarting it | `systemctl status greenhouse-<name>`; `journalctl -u greenhouse-<name> -n 50` |
| Home: **Ingest Degraded · broker unreachable** | The ingest service is running but cannot reach Mosquitto | `systemctl status mosquitto`; check `MQTT_*` in `server/.env` |
| Home: Wi-Fi **weak** | Signal below -75 dBm; expect dropouts and `LOCAL` spells | Move the router or Pico, or add an access point |
| Board resets every ~8 s | Watchdog on while stopped at the REPL, or a crash loop | Set `"watchdog": false` while debugging; read the REPL for the error |
| Relays on when they should be off | Active-low relay board | `"relay_active_low": true` in `config.json` |
| Heater switches off by itself | The controller's sensor gave no reading for 5 min (safety cut-off), or server readings are over 15 min old | Check the DHT22 wiring; get telemetry flowing again |
| LCD shows `LOCAL` | MQTT has been down for over 2 min, so the controller is running the rules itself | Normal during outages; fix the link (see `NoMQTT`). Check `settings.json` exists on the Pico (`mpremote ls :`) |
| Remote Control switches are greyed out | The controller reported offline | Wait for it to reconnect; it is running its own rules meanwhile |
| Dashboard asks for a password you don't know | `APP_PASSWORD_HASH` set in `.env` | Run `python -m scripts.set_password` again and restart `greenhouse-web` |

## Rolling back

- **Database:** every upgrade leaves `server/data/greenhouse.v<N>-backup-<time>.db`. Stop the
  services (`sudo systemctl stop 'greenhouse-*'`) and copy a backup over `greenhouse.db`.
- **Services:** `sudo systemctl disable --now greenhouse-ingest greenhouse-automation greenhouse-weather greenhouse-web`.
- **Controller:** relays default to off at boot. To stop the program entirely, `mpremote rm :main.py`
  (copy it back later with `mpremote cp main.py :`).
