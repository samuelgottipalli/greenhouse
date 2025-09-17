import json
import time
from display import Display

error_list = []
def load_config(filename="config.json"):
    try:
        with open(filename, "r") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        print(f"Error loading config: {e}")
        return {}
    
config = load_config()
display = Display(config)

def debounce(func, delay=500):
    last_call = 0
    def debounced(*args, **kwargs):
        nonlocal last_call
        current_time = time.ticks_ms()
        if time.ticks_diff(current_time, last_call) > delay:
            last_call = current_time
            func(*args, **kwargs)

    return debounced

def capture_error(err_str):
    print(err_str)
    display.clear()
    display.show_multiline(err_str)
    error_list.append([err_str])
    return
