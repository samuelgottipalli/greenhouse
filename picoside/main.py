# main.py
import time
import machine
import network
from utils import load_config
from sensors import Sensors
from display import Display
from buttons import Buttons
from relays import Relays
from gps_module import GPSModule
from mqtt_comm import MQTTComm
from time_utils import sync_time, get_formatted_time, get_time_alive, reset_time_alive, adjust_time_zone

config = load_config()

display = Display(config)
display.show_multiline("Initializing.. This may take a moment to get all the devices ready!")

sensors = Sensors(config)
relays = Relays(config)
gps = GPSModule(config)
mqtt = MQTTComm(config)

screen_mode = 0  # 0: main, 1-4: relay status

relay_display_time = 0
time_alive_start = time.ticks_ms()
last_relay_display_update = 0 #add this line.

TIME_ZONE_OFFSET = config.get("timezone_offset", 0) # get the timezone offset. Default to 0 if not found.

def toggle_screen(pin):
    global screen_mode
    screen_mode = (screen_mode + 1) % 9

def relay_control(relay_num):
    global screen_mode, relay_display_time
    relays.toggle_relay(relay_num)
    screen_mode = relay_num
    relay_display_time = time.ticks_ms()
    last_relay_display_update = 0 #reset the update timer.

def log_data(temperature, humidity, ldr_value):
    relay_status = [relays.get_relay_status(i + 1) for i in range(8)]
    data = {
        "timestamp": get_formatted_time(),
        "temperature": temperature,
        "humidity": humidity,
        "ldr": ldr_value,
        "relays": relay_status
    }
    mqtt.publish(data)

def log_gps_data():
    gps_data = gps.get_data()
    if gps_data:
        mqtt.publish_gps(gps_data)

def compare_and_sync_time():
    gps_time = gps.get_gps_time()
    if gps_time:
        gps_hours, gps_minutes, gps_seconds = gps_time
        gps_seconds_since_midnight = gps_hours * 3600 + gps_minutes * 60 + gps_seconds
        gps_seconds_since_midnight += TIME_ZONE_OFFSET * 3600

        system_time = time.localtime()
        system_seconds_since_midnight = system_time[3] * 3600 + system_time[4] * 60 + system_time[5]

        diff_seconds = gps_seconds_since_midnight - system_seconds_since_midnight

        if abs(diff_seconds) > 60: #Compare if the time is off by more than 1 minute.
            print("Time difference detected. Syncing with GPS time.")
            display.clear()
            display.show_multiline("Time difference detected. Syncing with GPS time.")
            adjust_time_zone()

def show_ip(pin):
    wlan = network.WLAN(network.STA_IF)
    if wlan.isconnected():
        ip_address = wlan.ifconfig()[0]
        display.show_message(f"IP: {ip_address}", 1)
        time.sleep(10) #show ip for 10 seconds.
    else:
        display.show_message("WiFi not connected", 1)
        time.sleep(2)
        
button_callbacks = {
    "toggle_screen": toggle_screen,
    "relay_control": relay_control,
    "show_ip": show_ip
}

buttons = Buttons(config, button_callbacks)

sync_time()
compare_and_sync_time()
log_gps_data()

last_mqtt_time = 0
last_gps_time = 0
last_sensor_read_time = 0
last_display_update_time = 0

last_time_str = ""
last_temp = None
last_humidity = None
last_ldr = None
display.clear()
while True:
    current_time = time.ticks_ms()

    # Sensor data every 5 minutes
    if time.ticks_diff(current_time, last_sensor_read_time) > 300000:
        temperature, humidity = sensors.read_dht()
        ldr_value = sensors.read_ldr()
        last_temp = temperature
        last_humidity = humidity
        last_ldr = ldr_value
        last_sensor_read_time = current_time

    # MQTT data every 5 minutes
    if time.ticks_diff(current_time, last_mqtt_time) > 300000:
        if last_temp is not None and last_humidity is not None and last_ldr is not None:
            log_data(last_temp, last_humidity, last_ldr)
        last_mqtt_time = current_time

    # GPS data at midnight
    t = time.localtime()
    if t[3] == 0 and t[4] == 0 and time.ticks_diff(current_time, last_gps_time) > 60000: #check every minute, if time is midnight.
      log_gps_data()
      last_gps_time = current_time
      compare_and_sync_time()

    # Display logic
    if time.ticks_diff(current_time, last_display_update_time) > 100: # Update screen 10 times a second
        last_display_update_time = current_time
        if screen_mode == 0:
            time_str = get_formatted_time()
            
            if time_str != last_time_str:
                display.show_message(time_str+" ", 0)
                last_time_str = time_str

            if last_temp is not None:
                display.show_message(f"Temp: {last_temp:4.1f}C         ", 1)

            if last_humidity is not None:
                display.show_message(f"Hum: {last_humidity:4.1f}%      ", 2)

            time_alive = get_time_alive()
            time_alive_str = f"{int(time_alive):3d}s"
            if time_alive > 15*60:
                time_alive_str = f"{int(time_alive/60):3d}m"
            if time_alive > 6*60*60:
                time_alive_str = f"{int(time_alive/60/60):3d}h"
            if time_alive > 3*24*60*60:
                time_alive_str = f"{int(time_alive/24/60/60):3d}d"
            
            display.show_message(f"Time Alive: {time_alive_str}    ", 3)

        elif 1 <= screen_mode <= 8:
            if time.ticks_diff(current_time, last_relay_display_update) > 1000: #only update 1 times a second.
                last_relay_display_update = current_time
                relay_state, relay_mode = relays.get_relay_status(screen_mode)
                display.show_message("                    ", 0)
                display.show_message(f"Relay {screen_mode}: {('On' if relay_state else 'Off')}", 1)
                display.show_message(f"Mode: {relay_mode}", 2)
                display.show_message("                    ", 3)
            if time.ticks_diff(current_time, relay_display_time) > 10000:
                screen_mode = 0
                display.clear()

    # Check for MQTT messages (non-blocking)
#     print("Before error.")
#     mqtt.client.check_msg()
#     print("After error.")

    time.sleep(0.1) #To prevent too much cpu usage.
