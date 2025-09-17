import machine
import time
from utils import debounce

class Buttons:
    def __init__(self, config, callbacks):
        self.config = config
        self.callbacks = callbacks
        self.last_click_time = [0] * 8
        self.toggle_pressed = False # Add this line
        self.setup_buttons()

    def setup_buttons(self):
        button_toggle = machine.Pin(self.config["button_toggle_pin"], machine.Pin.IN, machine.Pin.PULL_UP)
        button_relay1 = machine.Pin(self.config["button_relay1_pin"], machine.Pin.IN, machine.Pin.PULL_UP)
        button_relay2 = machine.Pin(self.config["button_relay2_pin"], machine.Pin.IN, machine.Pin.PULL_UP)
        button_relay3 = machine.Pin(self.config["button_relay3_pin"], machine.Pin.IN, machine.Pin.PULL_UP)
        button_relay4 = machine.Pin(self.config["button_relay4_pin"], machine.Pin.IN, machine.Pin.PULL_UP)

        button_toggle.irq(trigger=machine.Pin.IRQ_FALLING, handler=debounce(lambda pin: self.toggle_click()))
        button_relay1.irq(trigger=machine.Pin.IRQ_FALLING, handler=debounce(lambda pin: self.relay_click(1)))
        button_relay2.irq(trigger=machine.Pin.IRQ_FALLING, handler=debounce(lambda pin: self.relay_click(2)))
        button_relay3.irq(trigger=machine.Pin.IRQ_FALLING, handler=debounce(lambda pin: self.relay_click(3)))
        button_relay4.irq(trigger=machine.Pin.IRQ_FALLING, handler=debounce(lambda pin: self.relay_click(4)))
    
    def toggle_click(self):
        self.toggle_pressed = True
        time.sleep_ms(100) # Give time for other buttons to be pressed.
        if machine.Pin(self.config["button_relay1_pin"]).value() == 1:
            self.callbacks["show_ip"](None)
        else:
            self.callbacks["toggle_screen"](None)
        self.toggle_pressed = False

    def relay_click(self, relay_num):
        current_time = time.ticks_ms()
        if current_time - self.last_click_time[relay_num - 1] < 500:
            self.callbacks["relay_control"](self.get_alternate_relay(relay_num))
        else:
            self.callbacks["relay_control"](relay_num)
        self.last_click_time[relay_num - 1] = current_time

    def get_alternate_relay(self, relay_num):
        alternate_relays = {
            1: 5,
            2: 6,
            3: 7,
            4: 8
        }
        return alternate_relays.get(relay_num, relay_num)