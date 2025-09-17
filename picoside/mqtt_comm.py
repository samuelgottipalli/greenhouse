# mqtt_comm.py
import umqtt.simple as mqtt
import network
import time
import json
from utils import load_config
from display import Display

# "wifi_ssid": "Verizon-SM-S928U-1F86",
#   "wifi_password": "mwfg239@",
config = load_config()
display = Display(config)

class MQTTComm:
    def __init__(self, config):
        self.config = config
        self.client = mqtt.MQTTClient(
            client_id=config["mqtt_client_id"],
            server=config["mqtt_broker"],
            port=config["mqtt_port"]
        )
        self.connect_wifi()
        self.connect_mqtt()

    def connect_wifi(self):
        self.wlan = network.WLAN(network.STA_IF)
        self.wlan.active(True)
        if not self.wlan.isconnected():
            print("Connecting to WiFi...")
            display.clear()
            display.show_multiline("Connecting to WiFi...")
            self.wlan.connect(self.config["wifi_ssid"], self.config["wifi_password"])
            while not self.wlan.isconnected():
                time.sleep(2)
        print("WiFi connected:", self.wlan.ifconfig())
        display.clear()
        display.show_multiline("WiFi connected.")

    def connect_mqtt(self):
        try:
            self.client.connect()
            print("MQTT connected")
            display.clear()
            display.show_multiline("MQTT connected")
            self.client.subscribe(self.config["mqtt_topic_subscribe"])
        except OSError as e:
            print(f"MQTT connection failed: {e}")
            display.clear()
            display.show_multiline(f"MQTT connection failed: {e}")

    def publish(self, data):
        try:
            self.client.publish(self.config["mqtt_topic_publish"], json.dumps(data))
        except OSError as e:
            print(f"MQTT publish failed: {e}")
            display.clear()
            display.show_multiline(f"MQTT publish failed: {e}")
            self.connect_mqtt()

    def publish_gps(self, data):
        try:
            self.client.publish("greenhouse/gps", json.dumps(data))
        except OSError as e:
            print(f"MQTT gps publish failed: {e}")
            display.clear()
            display.show_multiline(f"MQTT gps publish failed: {e}")
            self.connect_mqtt()

    def subscribe_callback(self, callback):
        def _callback(topic, msg):
            try:
                message = json.loads(msg)
                relay_num = message.get("relay")
                if relay_num:
                    callback(relay_num)
            except (ValueError, KeyError) as e:
                print(f"MQTT message error: {e}")
                display.clear()
                display.show_multiline(f"MQTT message error: {e}")

        self.client.set_callback(_callback)