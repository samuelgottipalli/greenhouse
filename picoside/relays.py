import machine

class Relays:
    def __init__(self, config):
        self.relay_pins = [
            machine.Pin(config["relay1_pin"], machine.Pin.OUT),
            machine.Pin(config["relay2_pin"], machine.Pin.OUT),
            machine.Pin(config["relay3_pin"], machine.Pin.OUT),
            machine.Pin(config["relay4_pin"], machine.Pin.OUT),
            machine.Pin(config["relay5_pin"], machine.Pin.OUT),
            machine.Pin(config["relay6_pin"], machine.Pin.OUT),
            machine.Pin(config["relay7_pin"], machine.Pin.OUT),
            machine.Pin(config["relay8_pin"], machine.Pin.OUT)
        ]
        self.relay_states = [False] * 8
        self.relay_modes = ["auto"] * 8

    def toggle_relay(self, relay_num):
        relay_num -= 1
        self.relay_states[relay_num] = not self.relay_states[relay_num]
        self.relay_pins[relay_num].value(self.relay_states[relay_num])

    def get_relay_status(self, relay_num):
        return self.relay_states[relay_num - 1], self.relay_modes[relay_num - 1]

    def set_relay_mode(self, relay_num, mode):
        self.relay_modes[relay_num - 1] = mode