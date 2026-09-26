"""
Environmental sensor readers for the greenhouse controller.

Wraps the DHT22 temperature/humidity sensor and the light-dependent resistor
(LDR) wired to an ADC pin.
"""
import dht
import machine


class Sensors:
    """
    Reads the DHT22 and the LDR.

    Attributes:
        dht_sensor (dht.DHT22): Temperature/humidity sensor.
        ldr_pin (machine.ADC): ADC channel connected to the LDR voltage divider.
    """

    def __init__(self, config):
        """
        Set up the sensor pins.

        Args:
            config (dict): Uses ``dht_pin`` and ``ldr_pin``.
        """
        self.dht_sensor = dht.DHT22(machine.Pin(config["dht_pin"]))
        self.ldr_pin = machine.ADC(machine.Pin(config["ldr_pin"]))

    def read_dht(self):
        """
        Take a DHT22 measurement (the sensor allows one every 2 seconds).

        Returns:
            tuple[float | None, float | None]: ``(temperature_c, humidity_pct)``,
            or ``(None, None)`` if the sensor did not respond.
        """
        try:
            self.dht_sensor.measure()
            return self.dht_sensor.temperature(), self.dht_sensor.humidity()
        except OSError as err:
            print("DHT error:", err)
            return None, None

    def read_ldr(self):
        """
        Read the raw light level from the LDR.

        Returns:
            int: Raw 16-bit ADC reading (0-65535). Not calibrated to lux.
        """
        return self.ldr_pin.read_u16()
