"""
Runs before ``main.py`` at every start: undo an over-the-air update that fails.

While an update is on trial (``firmware.json`` says ``pending``), each start
is counted. If the new code hasn't reached the broker after ``MAX_BOOTS``
starts, or the file swap never finished (power cut), the old files are put
back from ``ota_old/`` (see ``ota.py``).

Keep this file small and self-contained: updates never replace it, so it
must not import anything an update could break.
"""
import json
import os

STATE_FILE = "firmware.json"
BACKUP_DIR = "ota_old"
MAX_BOOTS = 3  # must match ota.py


def _exists(path):
    """Tell whether a file exists."""
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def _save(state):
    """Replace the state file in one step (a power cut leaves the old or new one)."""
    temporary = STATE_FILE + ".tmp"
    with open(temporary, "w") as f:
        json.dump(state, f)
    try:
        os.rename(temporary, STATE_FILE)
    except OSError:  # Windows won't rename over a file (tests only)
        os.remove(STATE_FILE)
        os.rename(temporary, STATE_FILE)


def roll_back(state):
    """
    Put the files of the previous version back.

    Args:
        state (dict): The pending update's state.

    Returns:
        dict: The new state (previous version, with the result recorded).
    """
    for path in state.get("changed", []):
        backup = BACKUP_DIR + "/" + path
        if _exists(backup):
            if _exists(path):
                os.remove(path)
            os.rename(backup, path)
        elif path in state.get("new_files", []) and _exists(path):
            os.remove(path)
    detail = "Version {} did not start properly; went back to {}".format(state.get("version"), state.get("previous"))
    print(detail)
    return {"version": state.get("previous"), "pending": False, "result": "rolled_back", "detail": detail}


def check():
    """Count this start of a pending update, and roll back when it has failed."""
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
    except (OSError, ValueError):
        return
    if not isinstance(state, dict) or not state.get("pending"):
        return
    state["boots"] = state.get("boots", 0) + 1
    if state.get("installed") and state["boots"] <= MAX_BOOTS:
        _save(state)
    else:
        _save(roll_back(state))


try:
    check()
except Exception as err:  # never stop the controller from starting
    print("boot.py:", err)
