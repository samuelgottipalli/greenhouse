import ntptime
import time
import machine
from utils import load_config
from display import Display

config = load_config()
display = Display(config)

TIME_ZONE_OFFSET = config.get("timezone_offset", 0) # get the timezone offset. Default to 0 if not found.

def sync_time():
    try:
        ntptime.settime()
        print("Time synchronized (UTC)")
        display.clear()
        display.show_multiline("Time synchronized (UTC)")
#         adjust_time_zone()
    except OSError as e:
        print(f"Time sync failed: {e}")
        display.clear()
        display.show_multiline(f"Time sync failed: {e}")


def adjust_time_zone():
    # Adjust for time zone offset
    offset_seconds = TIME_ZONE_OFFSET * 3600
    current_time = time.time()
    adjusted_time = current_time + offset_seconds
    time_tuple = time.localtime(adjusted_time)
    machine.RTC().datetime((time_tuple[0], time_tuple[1], time_tuple[2], time_tuple[6] + 1, time_tuple[3], time_tuple[4], time_tuple[5], 0))
    print(f"Time adjusted for time zone (UTC{TIME_ZONE_OFFSET})")
    display.clear()
    display.show_multiline(f"Time adjusted for time zone (UTC{TIME_ZONE_OFFSET})")


def get_formatted_time():
    t = time.localtime()
    return "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(t[0], t[1], t[2], t[3], t[4], t[5])

def get_time_alive():
    return time.ticks_ms() / 1000  # Return time in seconds

def reset_time_alive():
    machine.reset() # Reset the pico.