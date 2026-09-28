# Greenhouse Control System Help

This guide explains how to use the Greenhouse Control System web app.

## Logging in

If a dashboard password has been set, enter it to continue. Use **Log out** at the bottom of
the sidebar when you are done on a shared computer.

## Several controllers

If more than one greenhouse controller is registered, pick one in the **Controller** box at the top
of the sidebar. Every page (readings, switches and settings) then shows and changes that
controller only.

## Navigation

Pick a page from the sidebar on the left.

### Home

System status at a glance:

*   **Controller:** Online or Offline, as last reported by the greenhouse controller.
*   **Greenhouse readings:** Fresh, or Stale if the latest reading is more than 15 minutes old.
*   **Relays:** each device's last recorded state and who set it (web, auto or device).
*   **Controller details:** when it last sent a message, how long it has been running, Wi-Fi signal (good, fair or weak) and free memory.
*   **Alerts** appear at the top in red while a problem lasts (too hot or cold, no readings,
    controller offline, a service down). If push or email is set up, you are also notified.
*   **Services:** the three background services (ingest, automation, weather) show OK, Degraded (running but with a problem, e.g. the MQTT broker is unreachable) or Down (silent for 2 minutes). Down services are restarted automatically.

### Reports › Weather Data

*   Gauges for temperature, humidity and wind speed: the needle shows the current value, the
    coloured zones and the word under it say what it means (e.g. *cool*, *dry*, *breezy*), and the
    line under that is the change over the last hour. A chart of the day is underneath.
*   Cards for sunrise and sunset, conditions, precipitation and wind direction.
*   Refreshes automatically every 15 minutes.

### Reports › Greenhouse Weather

*   Gauges for the latest temperature, humidity and light inside the greenhouse, with the change
    over the last hour. The temperature and humidity zones come from your Greenhouse Settings:
    **heater zone** below the heater trigger, **OK**, and **fan zone** above the fan trigger.
*   **Light** is shown in lux, *estimated* from the light sensor (dark, dim, overcast, daylight,
    full sun). The sensor's raw reading is shown under the gauge; to make the lux accurate, see
    *Calibrating the light sensor* in the RUNBOOK.
*   A warning appears if the readings are more than 15 minutes old.
*   Choose 24 hours, 7 days or 30 days for the charts (hover for exact values; the high and low
    are listed under each). "Show readings as a table" has one row per time, one column per
    measure (hourly averages for 7 and 30 days).

### Control › Remote Control

*   One switch per device: **Fan**, **Heater**, **Light** and **Water**.
*   Flip a switch to turn that device on or off. The badge next to it shows the last recorded
    state.
*   A device you switch here stays as you set it for 60 minutes; after that the automation service follows your Greenhouse Settings again.
*   If the controller is offline the switches are disabled. The controller then runs your Greenhouse Settings itself (its screen shows LOCAL), and it always switches the heater off if its temperature sensor stops responding for 5 minutes.

### Staying logged in

With **Keep me logged in on this device** ticked, the dashboard remembers you for 30 days, so
refreshing the page doesn't ask for the password again. **Log out** forgets it. Changing the
dashboard password logs every device out.

### Settings › App Settings

Choose how the app displays information:

*   **Display Units:** SI (°C, km/h, cm) or US (°F, mph, in).
*   **Date Format** and **Time Format** (12- or 24-hour).
*   **Timezone:** UTC, or a local time zone.
*   **Colour scheme:** Light, Dark, or follow your device's setting.
*   **Page width:** Automatic (reports use the full width, other pages stay narrow), Wide or
    Centered.
*   **Refresh pages automatically:** Home, the reports and Remote Control check for new data every
    30 seconds (one small database query) and update themselves when something changed. Turn it
    off to update only when you reload the page.

These choices are saved and apply to every browser that opens the dashboard.

### Settings › Greenhouse Settings

Set the rules the automation service follows:

*   **Fan:** the temperature and humidity at which the fan turns on. The **Buffer** is how far
    the value must fall before the fan turns off again. This stops the fan switching on and off
    rapidly.
*   **Heater:** the temperature below which the heater turns on, with its own buffer.
*   **Grow light:** in daytime the light turns on when the greenhouse is darker than
    **Grow light on below** and off again above that level plus its **Buffer**. It is always off
    at night. Levels are raw sensor readings (brighter is higher); the Greenhouse Weather page
    shows the current value. See the RUNBOOK section "Calibrating the light sensor".
*   **Water:** up to four daily start times, each with a run time in minutes. Set the run time to 0 to turn a slot off.

Buttons:

*   **Save** stores your changes.
*   **Revert** puts back the last saved settings.
*   **Restore Defaults** puts back the factory settings.

### Settings › Controllers

- **Software:** the version the controller runs and the version this server offers. When they
  differ, press **Update controller** (the controller must be online). It downloads the changed
  files, checks them, and restarts in about a minute. If the new version doesn't start properly,
  it goes back to the old one by itself, and this page says so.
- **Connect it to Wi-Fi:** for a new controller, or to change its Wi-Fi. Hold the controller's
  screen button while switching it on, join the `GreenhouseSetup-…` network shown on its screen
  with your phone, then scan the QR code here (or paste the setup code into the page at
  `http://192.168.4.1`). Choose your Wi-Fi, type its password and save.
- The setup code includes the controller's password for the messaging service, so share it only
  with people you trust.

## Frequently Asked Questions (FAQ)

**Q: The weather data is not updating. What should I do?**

1.  Make sure the weather collector (`python -m services.weather_collector`) is running on the server.
2.  Check that the server has internet access.

**Q: A device did not respond to the switch. What should I do?**

1.  **Check the Pico:** make sure the controller is powered on and connected to Wi-Fi. Press
    button 1 and the screen button together to show its IP address.
2.  **Check MQTT:** make sure the MQTT broker is running, and that the controller and the server
    are configured with the same broker address.

**Q: How do I change what a relay controls?**

This needs a wiring change in the greenhouse. Relays 1-4 are water, fan, heater and light. These
names are currently fixed in the app, so keep the wiring to match.
