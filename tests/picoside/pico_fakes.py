"""
Fake MicroPython hardware and services for the firmware tests.

``FakeTicks`` wraps at 2**30 exactly like the RP2040 port, so wrap-around bugs
show up in tests. Imported by ``conftest.py`` and by tests that build objects
directly.
"""
TICKS_PERIOD = 2 ** 30


class FakeTicks:
    """MicroPython-style millisecond ticks that wrap at 2**30."""

    def __init__(self, start=100_000):
        self.now = start

    def advance(self, ms):
        self.now = (self.now + ms) % TICKS_PERIOD

    def ticks_ms(self):
        return self.now

    @staticmethod
    def ticks_add(ticks, delta):
        return (ticks + delta) % TICKS_PERIOD

    @staticmethod
    def ticks_diff(a, b):
        half = TICKS_PERIOD // 2
        return ((a - b + half) % TICKS_PERIOD) - half

    def sleep_ms(self, ms):
        self.advance(ms)


class FakePin:
    OUT, IN, PULL_UP, IRQ_FALLING = 1, 0, 2, 4

    def __init__(self, pin_id, mode=None, pull=None):
        self.id = pin_id
        self._value = 1 if pull == FakePin.PULL_UP else 0
        self.handler = None

    def value(self, v=None):
        if v is None:
            return self._value
        self._value = int(bool(v))

    def irq(self, trigger=None, handler=None):
        self.handler = handler


class FakeADC:
    def __init__(self, pin):
        self.reading = 12345

    def read_u16(self):
        return self.reading


class FakeWDT:
    instances = []

    def __init__(self, timeout):
        self.timeout = timeout
        self.feeds = 0
        FakeWDT.instances.append(self)

    def feed(self):
        self.feeds += 1


class FakeDHT22:
    def __init__(self, pin):
        self.fail = False
        self.values = (21.5, 45.0)

    def measure(self):
        if self.fail:
            raise OSError("ETIMEDOUT")

    def temperature(self):
        return self.values[0]

    def humidity(self):
        return self.values[1]


class FakeLcd:
    """Records what a 20x4 LCD would show and counts writes."""

    def __init__(self, i2c=None, addr=None, rows=4, cols=20):
        self.rows, self.cols = rows, cols
        self.screen = [" " * cols for _ in range(rows)]
        self.cursor = (0, 0)
        self.writes = 0

    def backlight_on(self):
        pass

    def clear(self):
        self.screen = [" " * self.cols for _ in range(self.rows)]

    def move_to(self, col, row):
        self.cursor = (col, row)

    def putstr(self, text):
        col, row = self.cursor
        line = self.screen[row]
        self.screen[row] = (line[:col] + text + line[col + len(text):])[: self.cols]
        self.writes += 1


class FakeWLAN:
    def __init__(self, mode=None):
        self.connected = False
        self.connect_calls = []
        self.connect_succeeds = True
        self.is_active = False

    def active(self, flag):
        self.is_active = flag

    def isconnected(self):
        return self.connected

    def connect(self, ssid, password):
        self.connect_calls.append(ssid)
        if self.connect_succeeds:
            self.connected = True

    def ifconfig(self):
        return ("192.168.1.50", "255.255.255.0", "192.168.1.1", "8.8.8.8")


class FakeNtp:
    def __init__(self):
        self.host = None
        self.ok = True
        self.calls = 0

    def settime(self):
        self.calls += 1
        if not self.ok:
            raise OSError("ETIMEDOUT")
