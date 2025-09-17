from lcd_api import LcdApi
from i2c_lcd import I2cLcd
import machine
import time

class Display:
    def __init__(self, config):
        i2c = machine.I2C(0, sda=machine.Pin(config["lcd_sda_pin"]), scl=machine.Pin(config["lcd_scl_pin"]), freq=400000)
        self.lcd = I2cLcd(i2c, config["lcd_address"], 4, 20)
        self.lcd.backlight_on()

    def clear(self):
        self.lcd.clear()

    def show_message(self, message, line=0):
        self.lcd.move_to(0, line)
        self.lcd.putstr(message)
        
    def show_multiline(self, message):
        msg_len=len(message)
        if msg_len > 80:
            print("Message too long to display")
        else:
            start=0
            for line in range(4):
                end=start+20
                self.show_message(message[start:end], line)
                start+=20
