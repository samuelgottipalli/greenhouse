"""
Help for the Greenhouse Control System
"""
import streamlit as st

st.set_page_config(
    page_title="Help",
    page_icon="🌦️",
    layout="centered",
)

help_text = """
# Greenhouse Control System Help

This guide provides instructions on how to use the Greenhouse Control System web dashboard.

## Navigation

The application is organized into several pages, which you can select from the sidebar on the left.

### 1. Main Dashboard (`greenhouse.py`)

*   **Purpose:** This is the main overview page.
*   **Features:**
    *   Displays the most recent sensor readings from your greenhouse (e.g., temperature, humidity, soil moisture).
    *   Shows the current status of all connected relays (ON/OFF).
    *   Provides a quick glance at the overall health and state of your greenhouse environment.

### 2. Greenhouse Control (`greenhousecontrol.py`)

*   **Purpose:** This page allows you to manually control the equipment in your greenhouse.
*   **Features:**
    *   You will see a list of available relays (e.g., Relay 1, Relay 2).
    *   Use the toggle switches or buttons next to each relay to manually turn them ON or OFF.
    *   **Example:** If Relay 1 is connected to a fan, toggling it ON will start the fan.

### 3. Settings (`greenhousesettings.py`)

*   **Purpose:** Configure the operational parameters of the greenhouse system.
*   **Features:**
    *   Adjust the thresholds for automated control. For example, you can set the maximum temperature at which the fans should automatically turn on.
    *   Modify MQTT broker settings or other system configurations as needed.

### 4. Weather App (`weatherapp.py`)

*   **Purpose:** Displays local weather information.
*   **Features:**
    *   Shows current weather conditions, temperature, and forecasts.
    *   This information can help you make informed decisions about your greenhouse management.

### 5. About (`about.py`)

*   **Purpose:** Provides detailed information about the project.
*   **Features:**
    *   Describes the system architecture, including the `picoside` hardware, the `serverside` backend, and this `server-streamlit` web application.
    *   Lists the technologies used in the project.

## Frequently Asked Questions (FAQ)

**Q: The sensor data is not updating. What should I do?**

1.  **Check the Pico:** Ensure the Raspberry Pi Pico is powered on and has a stable internet connection.
2.  **Check the Server:** Make sure the `subs_from_pico.py` script is running on the server to listen for incoming data.
3.  **Check MQTT:** Verify that the MQTT broker is running and that both the Pico and the server are configured with the correct broker address and credentials.

**Q: How do I change what a relay controls?**

This requires a physical wiring change in the greenhouse and a potential code change in the `picoside/relays.py` file to update its label or logic. The web application will simply show the relay number; the physical connection determines its function.

"""

st.markdown(help_text)
