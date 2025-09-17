import dht
import machine
import time

class Sensors:
    def __init__(self, config):
        self.dht_sensor = dht.DHT22(machine.Pin(config["dht_pin"]))
        self.ldr_pin = machine.ADC(machine.Pin(config["ldr_pin"]))

    def read_dht(self):
        try:
            self.dht_sensor.measure()
            temperature = self.dht_sensor.temperature()
            humidity = self.dht_sensor.humidity()
            return temperature, humidity
        except OSError as e:
            print(f"DHT error: {e}")
            return None, None

    def read_ldr(self):
        return self.ldr_pin.read_u16()