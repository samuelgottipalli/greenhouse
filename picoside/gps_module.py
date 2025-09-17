import machine
import time
import micropyGPS
from utils import load_config
from display import Display

config = load_config()
display = Display(config)

class GPSModule:
    def __init__(self, config):
        tx_pin = config["gps_tx_pin"]
        rx_pin = config["gps_rx_pin"]
        timezone_offset = config["timezone_offset"]
        
        try:
            self.uart = machine.UART(1, baudrate=9600, tx=machine.Pin(tx_pin), rx=machine.Pin(rx_pin))
            self.gps = micropyGPS.MicropyGPS(timezone_offset)
            self.gps.local_offset
            print("GPS UART initialized")  # Debug line
            display.clear()
            display.show_multiline("GPS UART initialized")
        except ValueError as e:
            print(f"GPS UART error: {e}")
            display.clear()
            display.show_multiline(f"GPS UART error: {e}")
            raise  # Re-raise the error, so the program stops.

    def update(self):
        try:
            gpsstr = self.uart.read().decode('utf-8')
            for c in gpsstr:
                self.gps.update(c)
        except UnicodeError as e:
            print(f"Unable to parse GPS UART signal: {e}")
            display.clear()
            display.show_multiline(f"Unable to parse GPS UART signal: {e}")
#             raise
        except AttributeError as e:
            print("Nothing to parse. GPS UART signal not established")
            display.clear()
            display.show_multiline("Nothing to parse. GPS UART signal not established")    

    def get_data(self):
        self.update()
#         if self.gps.valid:
#             print("GPS data is valid") #debug line
        return {
            "latitude": self.gps.latitude,
            "longitude": self.gps.longitude,
            "timestamp": self.gps.timestamp
        }
#         else:
#             print("GPS data is not valid") #debug line
#             return None
        
    def get_gps_time(self):
        self.update()
#         if self.gps.valid:
        return self.gps.timestamp
#         else:
#             print("GPS data unable to provide timestamp")
#             return None
