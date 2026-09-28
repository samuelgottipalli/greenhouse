# About this greenhouse

This dashboard looks after a home greenhouse. It keeps an eye on the temperature, humidity and
light inside, and runs the fan, heater, grow light and watering for you, following the rules you
set. You can check on things and switch equipment from any phone or computer on your home Wi-Fi.

## What it does for you

*   **Keeps it comfortable.** The fan comes on when it gets too hot or humid, the heater when it
    gets too cold, and the grow light on dull days.
*   **Waters on a schedule.** Up to four times a day, for as long as you choose.
*   **Keeps going on its own.** If the Wi-Fi or this server stops, the controller in the
    greenhouse carries on running your rules by itself, and it always switches the heater off if
    its temperature sensor stops answering.
*   **Tells you when something is wrong.** Too hot, too cold, no readings, or the controller
    offline: it shows on the Home page and, if set up, on your phone or by email.
*   **Keeps a record.** Charts of the last day, week or month, next to the weather outside.

## How it fits together

1.  **The controller** is a small board in the greenhouse (a Raspberry Pi Pico W) with a
    temperature and humidity sensor, a light sensor, a little screen, five buttons and eight
    switches (relays) for the equipment. It measures every minute and reports every five.
2.  **The server** is a small always-on computer in the house (here a Raspberry Pi). It stores
    the readings, fetches the local weather, runs the automation and shows you this dashboard.
3.  They talk over your home Wi-Fi, and only there: nothing is sent to the internet except the
    request for your local weather forecast (from Open-Meteo).

Setting up a new controller needs no cables or typing on a keyboard: switch it on, join its
setup Wi-Fi with your phone and scan the code from **Settings › Controllers**. New versions of
the controller's software install over Wi-Fi from the same page, and undo themselves if anything
goes wrong.

## Credits

**Designed and built by Samuel Gottipalli**: the idea, the greenhouse, the hardware and wiring,
and the decisions about how it should all work.

**Programmed with Claude**, an AI assistant made by [Anthropic](https://www.anthropic.com).
Working with Samuel, Claude wrote most of the software and all of its automated tests: the
controller's program, including its offline mode, the phone setup page and the safe
over-the-air updates; this dashboard, with its gauges and charts; the background services and
alerts; and the installer that sets everything up. Claude also checked the pieces working
together on the real hardware.

Built with MicroPython, Python and Streamlit, and weather data from
[Open-Meteo](https://open-meteo.com).

<details>
<summary>For whoever looks after the server</summary>

The full setup and maintenance guide is `docs/RUNBOOK.md` in the project folder; the messages
between the controller and the server are described in `docs/MQTT.md`. The software runs as
background services on the server: the dashboard, *ingest* (stores what the controller sends),
*automation*, *weather* (fetches the forecast) and *firmware* (serves controller updates), plus
an alert check every two minutes and a nightly clean-up of old readings.

</details>
