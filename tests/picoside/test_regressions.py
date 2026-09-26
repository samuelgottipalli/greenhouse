"""
Regression tests for firmware bugs fixed in the main-loop rewrite, run through
the real ``Buttons`` interrupt handlers (not the fake used in
test_controller.py) so debounce and double-press timing interact as on the
device.

* P-11a: the screen button and the IP combo did each other's job (the old code
  treated a pull-up pin reading 1 as "pressed").
* P-11b: a 500 ms debounce swallowed the second press of a double press, so
  relays 5-8 were unreachable.
* P-12: the first sensor reading waited 5 minutes after boot.
"""
import pytest

from pico_fakes import FakeLcd
from test_controller import FakeClock, FakeNet, FakeSensors


@pytest.fixture
def device(pico, config, ticks):
    buttons = pico.buttons.Buttons(config)
    controller = pico.controller.Controller(
        config, pico.display.Display(config, lcd=FakeLcd()), FakeSensors(),
        pico.relays.Relays(config), buttons, FakeNet(), FakeClock(),
    )
    controller.start()
    return controller


def press(device, button, ticks, gap_ms=0, hold=False):
    """Simulate a physical press: pin goes low, IRQ fires, pin released unless held."""
    ticks.advance(gap_ms)
    pin = device.buttons.pins[button]
    pin.value(0)
    pin.handler(pin)
    if not hold:
        pin.value(1)


def release(device, button):
    device.buttons.pins[button].value(1)


def run_for(device, ticks, ms, step=50):
    for _ in range(ms // step):
        ticks.advance(step)
        device.tick()


def test_p11a_screen_button_alone_cycles_screens(device, ticks):
    press(device, 0, ticks)
    device.tick()
    assert device.screen == 1
    assert not device.display.lcd.screen[0].startswith("IP address")


def test_p11a_combo_shows_ip_and_does_not_toggle_relay_1(device, ticks, pico):
    press(device, 1, ticks, hold=True)
    run_for(device, ticks, 300)
    press(device, 0, ticks)
    device.tick()
    release(device, 1)
    run_for(device, ticks, 1000)
    assert device.screen == pico.controller.SCREEN_IP
    assert device.display.lcd.screen[0].startswith("IP address")
    assert device.relays.state(1) == 0


@pytest.mark.parametrize("button, paired", [(1, 5), (2, 6), (3, 7), (4, 8)])
def test_p11b_double_press_reaches_spare_relays(device, ticks, button, paired):
    press(device, button, ticks)
    device.tick()
    press(device, button, ticks, gap_ms=250)  # well inside the window, well past debounce
    run_for(device, ticks, 1000)
    assert device.relays.state(paired) == 1
    assert device.relays.state(button) == 0
    assert device.relays.pins[paired - 1].value() == 1


def test_p11b_contact_bounce_is_not_a_double_press(device, ticks):
    press(device, 2, ticks)
    press(device, 2, ticks, gap_ms=10)  # bounce inside the 50 ms debounce
    run_for(device, ticks, 1000)
    assert device.relays.state(2) == 1
    assert device.relays.state(6) == 0


def test_p12_values_on_screen_immediately_after_boot(device):
    device.tick()
    assert device.sensors.reads == 1
    assert device.display.lcd.screen[1].startswith("Temp: 21.5C")
    assert device.net.of("telemetry")
