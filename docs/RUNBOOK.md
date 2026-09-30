# Runbook: Connecting the Pico W

Step-by-step setup to bring the greenhouse online end to end: server, MQTT broker, services, and
the Pico W controller. Work through the steps in order. Each ends with a **Check** you can see or
run; don't move on until it passes. The [sign-off checklist](#9-sign-off-checklist) at the end
records the hardware checks the plan still needs (PLAN 1.6, 1.7, 2.2; FINDINGS P-03).

**Easier:** the installer (`setup.bat` / `sh setup.sh`, see the README's *Getting started*) does
steps 1–7 for you. Use this runbook to do them by hand, or to find out what the installer did,
and use steps 8–9 for the hardware checks either way. The [setup hotspot](#setup-hotspot-wi-fi-from-a-phone)
and [updates over Wi-Fi](#updating-the-controller-over-wi-fi) are described at the end.

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
#   (the location can be changed later on the dashboard: Settings › Location, which takes precedence)
server$ cd server
server$ ../venv/bin/python -m scripts.upgrade_db
server$ ../venv/bin/python -m scripts.set_password
```

If you are moving an existing `greenhouse.db`, copy it to `server/data/greenhouse.db` **before**
running `upgrade_db`. It is backed up and upgraded in place.

**Check:** `upgrade_db` prints `Created …` or `… already at schema version 6`. Run
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

This installs and starts `greenhouse-ingest`, `greenhouse-automation`, `greenhouse-weather`,
`greenhouse-firmware` (controller updates, port 8081) and `greenhouse-web`. Each restarts 5 s after a crash and starts at boot.
With `--enable` it also writes `/etc/sudoers.d/greenhouse-dashboard` (checked with `visudo` first), which
lets the services' account run exactly two commands as administrator without a password: restarting the
greenhouse services, and rebooting (the buttons on Settings › System). Delete that file to turn the
buttons off. It also enables two timers:
`greenhouse-alerts.timer` (alert check every 2 minutes, see [Alerts](#alerts)) and
`greenhouse-retention.timer`, the monthly job: on the 1st at 03:30 (or at the next start if the
server was off then, and again 10 minutes after every start) it summarises each finished month for
the Analysis page, copies the database to `server/data/backups/`, and deletes readings older than
6 whole months. It only does what is missing, so extra runs change nothing. Logs:
`journalctl -u greenhouse-ingest -f`, `journalctl -u greenhouse-retention`.

**Check:** all five are `active (running)`, and `systemctl list-timers greenhouse-retention.timer`
shows the next run (the 1st, 03:30). The ingest log shows `Connected to localhost:1883`
and no `not authorised`. Within 15 minutes Reports › Outdoor weather shows today's weather.

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
first power-up only, you may open that file and set `"watchdog": false`. The watchdog starts
30 seconds after the main loop does; once it runs, stopping the program from the REPL resets the
board 8 seconds later. `mpremote reset` followed by any `mpremote` command within 30 seconds is
always safe. Step 8 turns it back on.

Instead of this step you can let the controller set itself up from a phone: copy the code
(step 7) without a `config.json`, and follow [Setup hotspot](#setup-hotspot-wi-fi-from-a-phone).

---

## 7. Copy the code and first boot

```bash
pc$ cd picoside/device
pc$ mpremote cp -r . :
pc$ mpremote rm -r :__pycache__ + rm -r :lib/umqtt/__pycache__ + rm :config.example.json
#   (removes copies the Pico doesn't need; "No such file" for any of them is fine.
#    The installer and over-the-air updates only ever copy what's needed.)
pc$ mpremote ls :            # boot.py, main.py, controller.py, ..., config.json, lib/
pc$ mpremote reset
pc$ mpremote repl            # watch the console; Ctrl+] to leave
```

**Check (LCD):** in order,

1. `Initializing.. This may take a moment...`
2. `Greenhouse v1.1.0. Connecting to WiFi...` (the controller's version)
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
| b | Open **Reports › Greenhouse** | Temperature, humidity and light match the LCD (±1 reading) |
| c | **Control › Remote Control**: turn the **Fan** on | Relay 2 clicks within ~2 s; LCD shows `Relay 2: fan` / `State: On`; toggle stays on |
| d | Turn the fan off again | Relay releases; Home shows Fan Off (web) |
| e | Press relay button **1** once on the device | Relay 1 (water) toggles after ~0.4 s; Home shows Water (device) |
| f | Double-press button **1** quickly | Relay **5** toggles, relay 1 does not |
| g | Press the screen button | LCD cycles Relay 1 … Relay 8, then back to main |
| h | Hold button 1 and press the screen button | LCD shows `IP address:` and the Pico's IP; relay 1 unchanged |
| i | Stop the broker for 4 min: `sudo systemctl stop mosquitto`, then `start` | LCD shows `NoMQTT`, then `NoMQTT LOCAL` after 2 min; after `start`, `OK` again (reconnect can take up to ~5 min of backoff), and the readings from the outage appear in the 24 h chart |
| i1 | Unplug the Pico's power for 10 min | Home shows the controller **Offline** after up to ~7.5 min and Remote Control switches are disabled; after power returns, Online again |
| i2 | During an outage (as in i), warm or cool the sensor past the heater trigger | Relay 3 follows the heater rule on its own (local mode); after reconnecting Home shows the change as (auto) |
| i3 | Unplug the DHT22 data wire with the heater on | Within ~5.5 min relay 3 switches off by itself, even with the network up |
| j | **Settings › Greenhouse rules**: set "Turn on heater at" just above the current temperature, then Save | Within ~5 s relay 3 clicks and Home shows Heater On (auto). Put the setting back afterwards. |
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
- [ ] 4: five services running and surviving `sudo reboot`; Home shows all services **OK**
- [ ] 4: `sudo systemctl kill -s STOP greenhouse-automation` (freeze it): within ~2 min the watchdog restarts it and Home shows it OK again
- [ ] 7: device boots to `OK`; status and telemetry seen on the broker
- [ ] 8a–b: Home Online/Fresh; indoor values match the LCD
- [ ] 8c–d: web toggle moves the relay and the state is confirmed (P-03, PLAN 2.2)
- [ ] 8e–h: buttons, double press, screens and IP combo (P-11)
- [ ] 8i: recovers from a broker outage; queued readings arrive (P-05)
- [ ] 8i2–i3: local mode and the sensor-fault heater cut-off work on the hardware (P-15)
- [ ] 8j: automation switches the heater (source auto)
- [ ] 8k: relays off after a power cycle
- [ ] Light sensor calibrated (direction, on-level, buffer) and the grow light switches on on a dull day (PLAN 4.7)
- [ ] ⏳ LCD clock still correct 48 h after boot, including across midnight (P-02, PLAN 1.7)
- [ ] ⏳ 24 h: at least 285 of 288 expected telemetry rows stored (PLAN 2.3)
- [ ] ⏳ 7 days: no hang or reboot loop, with at least one Wi-Fi outage; `telemetry_report --hours 168` at 99 % or more (PLAN 3.2; simulated in `tests/picoside/test_soak.py`)
- [ ] ⏳ After the next start or the 1st: `journalctl -u greenhouse-retention` shows the monthly job
  ran ("Summarised ... month(s)"), and Analysis shows "Monthly summaries made through ..."
- [ ] Alerts: test alert received on phone/email and resolved (PLAN 4.6)
- [ ] Installer: a fresh computer set up with `setup.bat` / `setup.sh` only; controller online (PLAN 5.5)
- [ ] Setup hotspot: Wi-Fi changed from a phone; a wrong password brings the hotspot back (PLAN 5.1)
- [ ] Update over Wi-Fi: *Update controller* installs a changed file; a deliberately broken file rolls back after 3 restarts (PLAN 5.3)
- [ ] Watchdog re-enabled; loads reconnected

### Bench results so far

2026-09-27, Pico W on USB (MicroPython 1.29.0), standalone mode, no server yet:

| Check | Result |
|---|---|
| All controller code loads on the Pico | ✅ 130 KB of memory still free with everything loaded |
| Setup hotspot and page (5.1) | ✅ after fixes: pages in 0.2–0.8 s, including bursts and idle connections; form checks work over Wi-Fi |
| DHT22 and light sensor | ✅ 25.8 °C, 21 % RH, light ~22 400 (three steady reads) |
| Relay outputs 1–8 | ✅ every pin switches on and off and ends off. Still to confirm by eye/ear: each relay clicks, and **on** means on (else set `"relay_active_low": true`) |
| Controller loop in standalone/local mode | ✅ 75 s with no errors |
| Hardware watchdog | ✅ stopping the program resets the board after ~8 s (reset cause 3 = watchdog) |
| Update rollback on the board (5.3) | ✅ a broken `controller.py` crash-looped and `boot.py` restored the old files on the 4th start |
| Wi-Fi to the home network | ✅ connected within 40 s of a restart (-44 dBm). (Hand-driven connection attempts made while the program was interrupted mid-connect stayed stuck on "connecting"; the controller itself connects fine) |
| NTP clock and daylight saving (P-02) | ✅ an RTC set to 2020 was corrected by NTP; local time matched the PC (PDT) to the second |
| Server on a Raspberry Pi (Debian 13, Python 3.13) | ✅ set up over SSH following steps 1–4: broker refuses anonymous and wrong logins; all five services running and healthy; dashboard and firmware service reachable from the LAN |
| Controller → server (7) | ✅ online in the database, 8 relay states and readings stored within seconds of connecting (-42 dBm) |
| Server → controller relay command (8c–d, P-03, PLAN 2.2) | ✅ fan on and off from the server, each confirmed back in 0.5 s, logged as `web` |
| Update over Wi-Fi (PLAN 5.3) | ✅ `unknown` → `0da9f7b0fa0c`: updating, restarting, back online and **updated** in ~40 s; only the 4 changed files were downloaded |
| Buttons, relay clicks and polarity, outage tests, 48 h clock, 24 h / 7 day telemetry | ⏳ need a person at the board, or time |

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
| Pico | Hardware watchdog | fed every loop (~100 ms), from 30 s after start | If the program hangs for 8 s the board resets |
| Pico | Wi-Fi / MQTT link | every loop | Reconnects with backoff from 2 s up to 5 min |
| Pico | MQTT keep-alive | ping every 2 min; keep-alive 5 min | No reply from the broker for 5 min: the Pico reconnects. If the Pico goes silent, the broker publishes its `offline` status after ~7.5 min |
| Pico | Sensors | read every 60 s; safety checked every loop | No good DHT22 reading for 5 min: heater off |
| Pico | LCD backlight | 60 s after the last button press | Backlight off (the next press only wakes it) |
| Pico | Link lost | continuous | After 2 min offline, runs the rules itself (`LOCAL` on the LCD) |
| Pico | Clock | daily (every 5 min until the first success) | NTP re-sync |
| Pico → server | Health report | every 5 min, in telemetry | Uptime, free memory and Wi-Fi signal shown on Home |
| Server | Service heartbeats | each pass (automation 5 s, ingest 10 s, weather 10 s); stored every 30 s | Home shows OK / Degraded / Down (no beat for 2 min) |
| Server | systemd watchdog | `WatchdogSec=120` on ingest, automation, weather | A service that stops beating is killed and restarted |
| Server | systemd restart | on exit | A crashed service restarts after 5 s |
| Server | Alert check | every 2 min (timer) | Notifies by push/email; repeats at most hourly; sends "Resolved" when cleared |
| Server | Automation data checks | every 5 s | Readings older than 15 min: heater off; controller offline: automation stands back |

## Alerts

Every 2 minutes `greenhouse-alerts.timer` checks for:
- greenhouse temperature below `ALERT_TEMP_LOW_C` (default 5 °C) or above `ALERT_TEMP_HIGH_C`
  (default 40 °C);
- no readings for 15 minutes;
- a controller offline;
- a service down or degraded.

Each problem is sent once, repeated at most every `ALERT_COOLDOWN_MIN` (default 60) while it
lasts, followed by one "Resolved" message. Active alerts also appear at the top of Home.

To receive them, set in `server/.env` (either or both):

- **Phone push (ntfy):** install the ntfy app, subscribe to a topic name nobody will guess, and
  set `NTFY_URL=https://ntfy.sh/<that-topic>`.
- **Email:** `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `ALERT_EMAIL_FROM` and
  `ALERT_EMAIL_TO`. For Gmail, use an app password.

With neither set, alerts are only logged (`journalctl -u greenhouse-alerts`) and shown on Home.

**Test:** set `ALERT_TEMP_HIGH_C` just below the current greenhouse temperature and wait up to
2 minutes. You should get an alert, and Home shows it. Put the value back, and a "Resolved"
follows within 2 minutes.

## Calibrating the light sensor

The grow light (relay 4) is automated in daytime only (between sunrise and sunset from the weather
collector). It switches on when the raw light level is below **Grow light on below**, and off
again above that level plus **Buffer** (Settings › Greenhouse rules). The level is the LDR's raw reading,
0-65535, not lux, so it has to be calibrated once:

1. **Check the direction.** On **Reports › Greenhouse**, note the *Light (raw)* value,
   then cover the sensor for a minute (readings come every 60 s). It must go **down**. If it goes
   up, set `"ldr_inverted": true` in `config.json`, copy it to the Pico and reset.
2. **Pick the on-level.** On a day that is dull enough that you'd want the lamp on, note the
   reading and enter it as **Grow light on below**. The default is 15000.
3. **Measure the lamp.** At dusk, switch the light on from Remote Control and note how much the
   reading rises. Set **Buffer** to more than that rise, with some margin. Otherwise the lamp's own
   light would switch it off again. The default buffer is 10000.
4. **Check.** Automation changes the light at most once every 30 minutes in daytime, and always
   switches it off at sunset. A light you switch by hand is left alone for 60 minutes.

**Lux estimate.** The dashboard shows light in lux, estimated from the raw reading with a typical
LDR's curve (`server/core/light.py`). To make it accurate, calibrate once in daylight (not direct
sun): put a phone light-meter app next to the sensor, note its lux and, at the same time, the
*raw* number under the light gauge on Reports › Greenhouse, then:

```bash
server$ cd ~/greenhouse/server && ../venv/bin/python -m scripts.calibrate_light <raw> <lux>
server$ sudo systemctl restart greenhouse-web
```

The automation still works on the raw level; Settings › Greenhouse rules shows the lux it matches.

Without weather data (collector not running), the light is left as it is. The controller's local
mode does not drive the light, because it has no sunrise data.

## Adding another controller

```bash
server$ cd ~/greenhouse/server && ../venv/bin/python -m scripts.add_device 2 picow2
```

This registers device 2 with relays 1-8 and default settings, and prints the Mosquitto ACL block
and broker login it needs. Then:

1. Add the printed block to `/etc/mosquitto/greenhouse.acl`, create the login with
   `mosquitto_passwd`, and restart mosquitto.
2. Run `picoside/setup_config.py` for the new Pico with Device ID `2` and user
   `greenhouse-device-2`. It gives the Pico its own MQTT client ID, which matters: two controllers
   with the same client ID keep disconnecting each other.
3. Copy the code to it as in step 7.

The dashboard shows a **Controller** picker in the sidebar once there are two or more, and every
page, the switches and the greenhouse rules then apply to the chosen controller. The automation
service handles all controllers on every pass, each with its own settings.

## Running on battery

The defaults already favour low power: Wi-Fi power-save mode, an MQTT ping every 2 minutes
(keep-alive 5 minutes), sensor reads every minute, a 100 ms main loop, and the LCD backlight off
after 60 s without a button press. Things to know before moving off mains power:

- **Relay coils are the biggest draw.** Each energised relay typically draws 60-80 mA at 5 V,
  more than the Pico itself. Use a separate supply for the relay board and loads, or latching
  relays.
- **The backlight** is the next biggest. Keep `backlight_timeout_s` short, or set it to 0 only
  while debugging.
- **Wi-Fi** is always associated; power-save mode lets the radio sleep between access-point
  beacons. `publish_interval_s` (default 300) sets how often the radio sends.
- **Trade-off:** with a 5-minute keep-alive, the dashboard notices a vanished controller after
  ~7.5 minutes instead of ~90 s, and a silently dropped connection is re-established within
  ~5 minutes. Heater safety does not depend on this; the controller enforces it itself.
- Measure the real current with a USB power meter, once on mains with the defaults, before
  sizing a battery. These figures are typical values, not measurements of this board.

## Setup hotspot (Wi-Fi from a phone)

The controller can take its Wi-Fi and server settings from a phone, like most smart-home gadgets
(`picoside/device/provision.py`). It starts setup mode:

- by itself when it has no Wi-Fi or server settings (a new controller);
- when you **hold the screen button while switching it on** (until the screen says setup);
- by itself when newly saved Wi-Fi settings don't work on the first try.

A router outage never starts setup mode: the controller keeps running its rules and retrying.

1. The LCD shows `SETUP: join WiFi`, the network name (`GreenhouseSetup-XXXX`), a password and
   `then open 192.168.4.1`.
2. Join that network with your phone. Most phones then open the setup page by themselves; if not,
   browse to `http://192.168.4.1`.
3. On the dashboard (another device, or before you switch networks) open **Settings ›
   Controllers**. Scan its QR code with the phone (the setup page opens with the code filled in),
   or copy the **setup code** into the page. The code holds the server's address and this
   controller's broker login; without one, open *Enter the server details* and type them.
4. Pick your Wi-Fi network (2.4 GHz), type its password, check the time zone and tap **Save and
   connect**. The controller restarts and joins.

**Without a server.** Choose **On its own, without a server** on the setup page instead of
entering a setup code. The server fields are then ignored, Wi-Fi is optional (it only sets the
clock; without it the watering times can't run, but the fan and heater rules do), and the
*Rules for running on its own* section sets the fan, heater and two watering times (saved to
`settings.json`). The controller starts in local mode and shows `LOCAL` on its screen. To change
the rules, or to connect it to a server later, hold the screen button at power-on and run setup
again.

The setup page never shows saved passwords; leaving a password field empty keeps the saved one.
Setup mode started with the button gives up after 15 minutes and restarts with the old settings.
The setup code contains the controller's broker password, so don't share it.

## Updating the controller over Wi-Fi

When the code in `picoside/device/` changes (after the installer's **Update**, or `git pull`), the
dashboard's **Settings › Controllers** page shows **Update available** and the Home page says so.
Press **Update controller** while the controller is online:

1. The server sends a list of files with checksums (`firmware/update`, docs/MQTT.md).
2. The controller shows `Updating the controller's software`, downloads only the files that
   changed from the `greenhouse-firmware` service, and checks every checksum. Any problem: it
   reports `failed` and nothing changes.
3. It swaps the files in and restarts. When the new version reaches the broker it is kept, and the
   page shows **Updated**.
4. If the new version keeps crashing (3 restarts) or can't reach the broker for 10 minutes,
   `boot.py` puts the old files back and the page shows the update was undone.

`boot.py` and `main.py` are never changed over Wi-Fi; copy them by USB if they ever change.
Controllers need to reach the server on port **8081** (and 1883 for the broker); allow both in the
server's firewall.

The page shows version names (for example *Installed 1.0.0*, *Available 1.1.0*) with the exact
builds underneath. After an update the controller reports *Updated from 1.0.0 to 1.1.0*, and it
shows its version on its screen while starting. What changed in each version is in
[CHANGELOG.md](../CHANGELOG.md).

## Using a cloud MQTT service

Instead of running Mosquitto, the server and the controllers can meet at a hosted MQTT service.
Connections are encrypted (TLS on port 8883) and the controller checks the service's certificate.
Readings and switch commands then travel through the service over the internet; software updates
still come straight from the server, so the server must be on the same network as the controllers.

**HiveMQ Cloud (free plan), step by step** (other services work the same way; the console's
wording may differ slightly):

1. Sign up at <https://console.hivemq.cloud> and create a free (*Serverless*) cluster.
2. Open the cluster. Its **Overview** shows the address, like `abc123.s1.eu.hivemq.cloud`, and the
   TLS port **8883**.
3. Under **Access management**, create two logins, each allowed to *publish and subscribe*:
   one for the server (e.g. `greenhouse-server`) and one for controller 1 (e.g.
   `greenhouse-device-1`). Use long random passwords. If the service can limit a login to some
   topics, limit controller *N* to `greenhouse/N/#`.
4. Run the installer and, on **Messaging**, choose **Use a cloud MQTT service**. Enter the address,
   port 8883 and both logins. It checks both logins and which certificate the controller needs.
5. Set up the controller as usual (USB on the next page, or the setup code from
   **Settings › Controllers**, which now holds the service's address and *encrypted*).

By hand instead of the installer, set in `server/.env`:

```ini
MQTT_HOST=abc123.s1.eu.hivemq.cloud
MQTT_PORT=8883
MQTT_TLS=true
MQTT_USERNAME=greenhouse-server
MQTT_PASSWORD=<server password>
PUBLIC_HOST=<this computer's LAN address, for software updates>
```

and on the controller `mqtt_broker`, `mqtt_port` 8883, `mqtt_tls` true and its own login
(`mqtt_ca` can stay empty). Add more controllers with a login each in the service's console, then
enter it on **Settings › Controllers**.

**Certificates.** The controller carries a few common root certificates in
`picoside/device/certs/` (Let's Encrypt, Amazon, DigiCert, GlobalSign, Google, Sectigo, Microsoft).
The first time it connects it tries them in turn and remembers the one that works (`mqtt_ca`).
It needs the correct time for this, so it waits for NTP first. If a service's certificate chains
to none of them, the installer and the Controllers page say so; add that root to
`server/scripts/update_controller_certs.py`, run `python -m scripts.update_controller_certs` and
update the controllers.

On the Pico W an encrypted connection takes about 5 seconds to open and uses about 30 KB of
memory while connected (measured 2026-09-28: 144 KB free with the controller loaded).

## Troubleshooting

**Cloud service: the controller never comes online.** On its USB console it prints why:
`waiting for the clock before an encrypted connection` (it can't reach an NTP server yet),
`broker certificate not accepted` for every root (the service's certificate isn't covered; see
*Certificates* above), or `MQTT connect failed` (address, port 8883 or login wrong).

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
| No `GreenhouseSetup-…` network appears | The controller isn't in setup mode | Hold the screen button from before power-on until the screen says setup; a controller with working settings starts normally otherwise |
| Joined `GreenhouseSetup-…` but `192.168.4.1` doesn't load | The phone sends it over mobile data because the hotspot has no internet | Turn mobile data off during setup, or choose *Stay connected* when the phone warns about no internet; reload `http://192.168.4.1` (not https) |
| Phone won't stay on the setup network ("no internet") | The phone prefers networks with internet | Choose *Stay connected* / *Use without internet*, then browse to `http://192.168.4.1` |
| Setup page: "setup code wasn't recognised" | The code was cut short when copying | Copy it again from **Settings › Controllers**, or scan the QR code |
| Controllers page: *Update controller* greyed out | The controller is offline, or the server's address is unknown | Wait until it's online; set `PUBLIC_HOST` in `server/.env` |
| Update shows **failed** | The controller couldn't download from port 8081, or a file was damaged | Check `greenhouse-firmware` is running and port 8081 is open; press Update again |
| Update was **undone** | The new version didn't start properly | Nothing to do on the controller (it runs the old version); report the problem |
| Installer: *No controller found* | Charge-only cable, or a new Pico not in BOOTSEL mode | Use a data cable; hold BOOTSEL while plugging in a new Pico |
| Dashboard asks for a password you don't know | `APP_PASSWORD_HASH` set in `.env` | Run `python -m scripts.set_password` again and restart `greenhouse-web` |

## Rolling back

- **Backups:** every upgrade leaves `server/data/greenhouse.v<N>-backup-<time>.db`. For a manual
  backup at any time, even while the services run, use `python -m scripts.backup_db [target]`.
  The database uses WAL mode, so recent changes may still be in `greenhouse.db-wal`; a plain file
  copy of `greenhouse.db` alone can miss them.
- **Restore:** stop everything (`sudo systemctl stop 'greenhouse-*'`), delete `greenhouse.db-wal`
  and `greenhouse.db-shm` if present, copy the backup over `greenhouse.db`, then start the services
  again.
- **Services:** `sudo systemctl disable --now greenhouse-ingest greenhouse-automation greenhouse-weather greenhouse-firmware greenhouse-web`.
- **Controller:** relays default to off at boot. To stop the program entirely, `mpremote rm :main.py`
  (copy it back later with `mpremote cp main.py :`).
