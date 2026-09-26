"""
20x4 character LCD for the greenhouse controller.

Thin layer over the vendored ``I2cLcd`` driver (HD44780 behind a PCF8574 I2C
backpack). Create one ``Display`` in ``main.py`` and pass it to whatever needs
it; only the main loop should write to it.
"""
import machine

ROWS = 4
COLS = 20


def fit(text):
    """
    Pad or cut text to exactly one LCD line.

    Args:
        text (str): Text to show.

    Returns:
        str: ``COLS`` characters.
    """
    return "{:<20}".format(text)[:COLS]


def wrap(message):
    """
    Split a message into up to four LCD lines.

    Args:
        message (str): Text; anything past 80 characters is cut off.

    Returns:
        list[str]: Four lines of 20 characters.
    """
    return [fit(message[i * COLS:(i + 1) * COLS]) for i in range(ROWS)]


class Display:
    """
    Writes whole lines to the LCD, skipping lines that have not changed.

    Attributes:
        lcd (I2cLcd): Underlying LCD driver.
    """

    def __init__(self, config, lcd=None):
        """
        Open the I2C bus and turn on the backlight.

        Args:
            config (dict): Uses ``lcd_sda_pin``, ``lcd_scl_pin`` and
                ``lcd_address``.
            lcd (object | None): Ready-made driver (injected in tests).
        """
        if lcd is None:
            from i2c_lcd import I2cLcd

            i2c = machine.I2C(0, sda=machine.Pin(config["lcd_sda_pin"]),
                              scl=machine.Pin(config["lcd_scl_pin"]), freq=400000)
            lcd = I2cLcd(i2c, config["lcd_address"], ROWS, COLS)
        self.lcd = lcd
        self.lcd.backlight_on()
        self._shown = [None] * ROWS

    def clear(self):
        """Blank the screen."""
        self.lcd.clear()
        self._shown = [fit("")] * ROWS

    def show_lines(self, lines):
        """
        Show up to four lines, rewriting only those that changed.

        Args:
            lines (list[str]): Text per row; missing rows are blanked.
        """
        for row in range(ROWS):
            text = fit(lines[row] if row < len(lines) else "")
            if text != self._shown[row]:
                self.lcd.move_to(0, row)
                self.lcd.putstr(text)
                self._shown[row] = text

    def show_message(self, message):
        """
        Show a message wrapped over the whole screen (boot and error messages).

        Args:
            message (str): Up to 80 characters.
        """
        print(message)
        self.show_lines(wrap(message))
