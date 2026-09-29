# How to use the greenhouse dashboard

## Finding your way around

The menu on the left has five pages. The bigger ones are split into tabs along the top.

| Page | What it's for |
|---|---|
| **Home** | Everything at a glance: is the controller online, are the readings fresh, what's switched on, any problems. |
| **Reports** | **Greenhouse**: what it's like inside now and over time. **Outdoor weather**: today's weather outside. |
| **Remote Control** | Switch the fan, heater, grow light and watering on or off yourself. |
| **Settings** | **Display**: how things look. **Location**: where the greenhouse is, for the weather. **Greenhouse rules**: when the equipment runs. **Controllers**: connect a controller to Wi-Fi and update it. |
| **Help** | This guide, and **About** the system. |

Pages update by themselves when new readings arrive (you can turn this off in Settings › Display).

If you have more than one greenhouse controller, choose which one to look at in the **Controller**
box at the top of the menu.

## Logging in

Enter the dashboard password. With **Keep me logged in on this device** ticked, it remembers you
for 30 days. Use **Log out** at the bottom of the menu on a shared computer.

## Home

*   **Controller:** *Online* or *Offline*, how long it has been running, and its Wi-Fi signal.
    A note appears here when a software update is available for it.
*   **Greenhouse readings:** *Fresh*, or *Stale* when nothing has arrived for 15 minutes.
*   **Relays:** what's on and off, and who switched it last (*web* = you, *auto* = the rules,
    *device* = a button on the controller).
*   **Services:** the background jobs on the server. *OK* is good; one that stops is restarted
    automatically.
*   **Alerts** show in red at the top while something is wrong.

## Reports

The date and time are at the top of the page, and each tab says when its data was last updated.

## Reports › Greenhouse

*   **Gauges** for temperature, humidity and light. The needle shows the current value and the
    coloured zones come from your rules: **heater zone** (too cold), **OK**, and **fan zone** (too
    warm or too humid). Underneath is how much it changed in the last hour.
*   **Light** is shown in lux, estimated from the sensor, with a word for it: dark, dim,
    overcast, daylight or full sun. (The number becomes accurate once the light sensor is
    calibrated with a phone light-meter app; see the setup guide.)
*   **Charts** for the last 24 hours, 7 days or 30 days. Hover over a line for the exact time and
    value; the highest and lowest are listed underneath.
*   **Show readings as a table** lists the readings, one row per time.

## Reports › Outdoor weather

Today's conditions, sunrise, sunset and hours of daylight, then gauges for the temperature,
humidity, rain and wind outside, each with a chart of the day. The rain gauge shows how hard it is
raining right now (per hour), with today's total underneath; the wind card says which way it is
blowing from. It comes from the free Open-Meteo forecast for your location and updates every 15
minutes.

## Remote Control

*   Flip a switch to turn the fan, heater, grow light or water on or off.
*   What you switch here stays that way for 60 minutes; after that the greenhouse rules take
    over again.
*   The switches are greyed out while the controller is offline. It keeps following your rules by
    itself in the meantime (its screen shows **LOCAL**).

## Settings › Location

Where the greenhouse is. It decides which outdoor weather you see and the sunrise and sunset times
(the grow light only runs between them).

*   Type your town and press **Find**, pick the right one from the list and press
    **Use this location**. The weather for the new place appears straight away.
*   If the new place is in another time zone, you can have the dashboard show its times there too.
*   No match, or somewhere remote? Open **Enter the latitude and longitude instead** (your phone's
    map app shows them).

## Settings › Display

*   **Units** (°C or °F), **date** and **time** formats, and the **time zone**.
*   **Colour scheme:** light, dark, or the same as your phone or computer.
*   **Page width:** *Automatic* uses the full width for reports and a narrower column elsewhere.
*   **Refresh pages automatically** when new data arrives.

These choices apply to everyone who uses the dashboard.

## Settings › Greenhouse rules

*   **Fan:** turns on above the temperature or humidity you set. The **buffer** is how far it must
    drop again before the fan stops, so it doesn't flick on and off.
*   **Heater:** turns on below the temperature you set, with its own buffer.
*   **Grow light:** in daytime only, turns on when it's darker than the level you set (the lux it
    matches is shown underneath) and off again once it's brighter by the buffer. Always off at
    night.
*   **Watering:** up to four start times a day, each with how many minutes to water. 0 minutes
    turns that time off.
*   **Save** keeps your changes, **Revert** undoes unsaved changes, **Restore Defaults** goes back
    to the factory rules.

## Settings › Controllers

*   **Software:** which version the controller runs. When a newer one is available, press
    **Update controller** while it's online. It takes about a minute, and if the new version
    doesn't start properly the controller goes back to the old one by itself.
*   **Connect it to Wi-Fi** (a new controller, or a new Wi-Fi network or password):
    1.  Hold the controller's screen button (the one on its own) while switching it on. A new
        controller does this by itself.
    2.  On your phone, join the Wi-Fi network shown on the controller's screen
        (`GreenhouseSetup-…`) with the password shown there.
    3.  Scan the QR code on this page with the phone's camera.
    4.  Pick your Wi-Fi, type its password and tap **Save and connect**.
*   The setup code contains the controller's password, so only share it with people you trust.
*   **Using a cloud MQTT service?** Each controller needs its own login, made in the service's
    website. If this page asks for it, type the login name and password there; the setup code then
    tells the controller to connect to the service, encrypted.

## The controller in the greenhouse

*   **Screen:** the time, temperature, humidity, how long it has been running, and the
    connection: **OK**, **NoWiFi**, **NoMQTT** (can't reach the server) or **LOCAL** (running
    your rules by itself).
*   **Buttons 1–4** switch the water, fan, heater and light. A quick double press switches the
    spare relays 5–8.
*   **Screen button:** steps through each relay's status. Hold button 1 and press it to show the
    controller's IP address. Hold it while switching on to start the Wi-Fi setup.
*   After a power cut everything starts **off**, then the rules switch things back on as needed.

## Common questions

**The controller shows Offline.** Check it has power and that its screen doesn't say *NoWiFi*.
If it does, its Wi-Fi details may have changed: see *Connect it to Wi-Fi* above. It keeps running
your rules in the meantime.

**The readings say Stale.** Nothing has arrived for 15 minutes. Usually the controller is offline
(see above). If the controller is online, check the Home page's *Services*.

**A switch didn't do anything.** Make sure the controller is online (the switches are greyed out
otherwise), and check its screen for a message.

**The weather hasn't updated.** The server needs internet access. The Home page shows whether the
*weather* service is OK.

**The light reading looks wrong.** It's an estimate until the sensor is calibrated; the setup
guide explains how, with a free phone light-meter app.

**How do I change what a relay controls?** That's a wiring change in the greenhouse. Relays 1–4
are the water, fan, heater and light, and the dashboard expects them in that order.
