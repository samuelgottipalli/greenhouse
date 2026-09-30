"""
Settings › System tab: restart the controller, the dashboard and background
services, or the server computer (``core/system.py``).

Each button asks for confirmation first. Restarting the controller needs it
online and on 1.3.0 or later (older controllers don't understand the
command); the others depend on how the server runs, which the tab explains.
"""
import streamlit as st

from core import db, firmware, mqtt, system
from ui import current_device

CONFIRM_KEY = "system_confirm"
NOTICE_KEY = "system_notice"
CONTROLLER_RESTART_FROM = (1, 3, 0)

ACTIONS = {
    "controller": ("Restart the controller",
                   "The controller restarts: its switches turn off for about half a minute and the rules then "
                   "switch them back as needed."),
    "services": ("Restart the dashboard and background services",
                 "The background services and this dashboard restart. The page is gone for about 15 seconds "
                 "and then reconnects by itself. The controller keeps running your rules meanwhile."),
    "computer": ("Restart the server computer",
                 "The whole server computer restarts. The dashboard is gone for a minute or two; the controller "
                 "keeps running your rules meanwhile."),
}


def version_tuple(name: str | None) -> tuple[int, ...]:
    """``"1.3.0-dev"`` -> ``(1, 3, 0)``; ``()`` for None or anything unreadable."""
    try:
        return tuple(int(part) for part in (name or "").split("-")[0].split("."))
    except ValueError:
        return ()


def controller_state(device_id: int) -> tuple[bool, str | None]:
    """Whether the controller can be restarted now, and why not."""
    status = db.device_status(device_id=device_id) or {}
    if status.get("status") != "online":
        return False, "The controller is offline, so it can't be told to restart."
    installed = firmware.installed_name(status)
    if version_tuple(installed) < CONTROLLER_RESTART_FROM:
        return False, (f"The controller runs {installed or 'an older version'}; restarting it from here needs "
                       "1.3.0 or later. Update it first (Settings › Controllers).")
    return True, None


def run(action: str, device_id: int) -> tuple[bool, str]:
    """Carry out a confirmed action."""
    if action == "controller":
        if mqtt.publish_controller_restart(device_id):
            return True, "Restart sent. The controller is back online in about half a minute."
        return False, "The restart couldn't be sent: the broker didn't answer."
    if action == "services":
        return system.restart_services()
    return system.reboot()


def ask(action: str, allowed: bool = True, why: str | None = None) -> None:
    """One button, with its explanation; pressing it asks for confirmation."""
    label, explanation = ACTIONS[action]
    with st.container(border=True):
        st.markdown(f"**{label}**")
        st.caption(explanation)
        if why:
            st.caption(f":material/info: {why}")
        if st.button(label, key=f"system_{action}", icon=":material/restart_alt:", disabled=not allowed):
            st.session_state[CONFIRM_KEY] = action
            st.rerun()


def render() -> None:
    """Draw this section (called by its tabbed page)."""
    device_id = current_device()
    notice = st.session_state.pop(NOTICE_KEY, None)
    if notice:
        ok, message = notice
        (st.success if ok else st.error)(message, icon=":material/check_circle:" if ok else ":material/error:")

    pending = st.session_state.get(CONFIRM_KEY)
    if pending in ACTIONS:
        label, explanation = ACTIONS[pending]
        st.warning(f"**{label}?** {explanation}", icon=":material/warning:")
        yes, no = st.columns(2)
        if yes.button("Yes, restart", type="primary", icon=":material/restart_alt:", key="system_yes"):
            st.session_state.pop(CONFIRM_KEY, None)
            st.session_state[NOTICE_KEY] = run(pending, device_id)
            st.rerun()
        if no.button("Cancel", key="system_no"):
            st.session_state.pop(CONFIRM_KEY, None)
            st.rerun()
        return

    allowed, why = controller_state(device_id)
    ask("controller", allowed, why)
    kind = system.manager()
    ask("services", kind != "none",
        None if kind != "none" else "The dashboard was started by hand, so nothing is there to restart it.")
    ask("computer")
