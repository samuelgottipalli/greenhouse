"""
Setup mode: the controller's own Wi-Fi hotspot and setup page.

Like most smart-home gadgets, the controller sets itself up from a phone:

1. With no Wi-Fi or server settings (and not set to run on its own), or
   when the screen button is held at power-on, the controller starts a hotspot called ``GreenhouseSetup-XXXX``.
   The LCD shows its name and a fresh password.
2. A phone that joins it is sent to the setup page (every web address and DNS
   name leads to ``192.168.4.1``, so phones show their "sign in to network"
   prompt). The page lists nearby Wi-Fi networks and asks for the Wi-Fi
   password, the *setup code* from the dashboard (server address and login;
   or those details typed in by hand) and the time zone, which the phone
   suggests. Or choose **On its own, without a server**: then Wi-Fi is
   optional (it only sets the clock) and the page takes the fan, heater and
   watering rules, which are saved to ``settings.json``.
3. Saving writes ``config.json`` and restarts. If the new network can't be
   joined on that boot, setup starts again with the error shown
   (``wifi_unverified`` marks settings that have never worked yet). A router
   outage later never starts setup: the controller keeps running on its own
   (local mode) and keeps retrying.

Setup mode ends by restarting the board: after saving, or after
``SETUP_TIMEOUT_MS`` when the controller already had working settings. Relays
stay off throughout, and the watchdog is not running yet.

Everything except :func:`run_setup` is plain logic, tested on CPython.
"""
import gc
import json
import os
import time

import local_rules
import zones

AP_IP = "192.168.4.1"
SETUP_TIMEOUT_MS = 15 * 60 * 1000
BUTTON_HOLD_MS = 1500
UNVERIFIED_FILE = "wifi_unverified"
CODE_PREFIX = "GH1-"
MAX_REQUEST = 4096
MAX_PENDING = 6
SEND_CHUNK = 1024
IDLE_MS = 3000
PLACEHOLDER_BROKERS = ("", "YOUR_MQTT_BROKER")

REASON_NEW = "new"
REASON_BUTTON = "button"
REASON_WIFI_FAILED = "wifi_failed"


# --- when to run setup -----------------------------------------------------


def setup_reason(config, button_held):
    """
    Decide whether the controller should start in setup mode.

    Args:
        config (dict): Loaded configuration.
        button_held (bool): The screen button was held at power-on.

    Returns:
        str | None: ``REASON_NEW`` (no Wi-Fi or server settings, and not set
        to run on its own), ``REASON_BUTTON``, or None for a normal start.
    """
    if not config["standalone"] and (not config["wifi_ssid"] or config["mqtt_broker"] in PLACEHOLDER_BROKERS):
        return REASON_NEW
    if button_held:
        return REASON_BUTTON
    return None


def button_held(pin, display, hold_ms=BUTTON_HOLD_MS):
    """
    Tell whether a button is held down at power-on for ``hold_ms``.

    Returns at once when the button is up, so a normal start is not delayed.

    Args:
        pin: ``machine.Pin`` with a pull-up (pressed reads 0).
        display (display.Display): Shows "keep holding" while waiting.
        hold_ms (int): How long the button must stay down.

    Returns:
        bool: True if it was held the whole time.
    """
    if pin.value():
        return False
    display.show_message("Keep holding the button for setup mode...")
    start = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), start) < hold_ms:
        if pin.value():
            return False
        time.sleep_ms(50)
    return True


def _exists(path):
    """Tell whether a file exists (works on MicroPython and CPython)."""
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def is_unverified():
    """bool: True if the saved Wi-Fi settings have never connected yet."""
    return _exists(UNVERIFIED_FILE)


def mark_unverified():
    """Record that the Wi-Fi settings were just saved and not yet tried."""
    with open(UNVERIFIED_FILE, "w") as f:
        f.write("1")


def clear_unverified():
    """Record that the Wi-Fi settings work (called after a connection)."""
    if _exists(UNVERIFIED_FILE):
        os.remove(UNVERIFIED_FILE)


def setup_timeout_ms(reason):
    """
    How long setup mode waits before restarting.

    Args:
        reason (str): Why setup started.

    Returns:
        int | None: Milliseconds, or None to wait until settings are saved
        (a new controller has nothing else to do).
    """
    return None if reason == REASON_NEW else SETUP_TIMEOUT_MS


# --- small helpers -----------------------------------------------------------


def html_escape(text):
    """
    Escape text for HTML content and attribute values.

    Args:
        text: Any value (converted with ``str``).

    Returns:
        str: Safe text.
    """
    text = str(text)
    for old, new in (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ('"', "&quot;"), ("'", "&#39;")):
        text = text.replace(old, new)
    return text


def url_decode(text):
    """
    Decode a form or query-string value (``+`` is a space, ``%XX`` a byte).

    Args:
        text (str): Encoded value.

    Returns:
        str: Decoded text (UTF-8).
    """
    text = text.replace("+", " ")
    out = bytearray()
    i = 0
    while i < len(text):
        char = text[i]
        if char == "%" and i + 2 < len(text) and _is_hex(text[i + 1:i + 3]):
            out.append(int(text[i + 1:i + 3], 16))
            i += 3
        else:
            out.extend(char.encode("utf-8"))
            i += 1
    return out.decode("utf-8")


def _is_hex(pair):
    """Tell whether a string is two hex digits."""
    return len(pair) == 2 and all(c in "0123456789abcdefABCDEF" for c in pair)


def parse_query(text):
    """
    Parse ``a=1&b=2`` into a dict (the last value wins for repeated names).

    Args:
        text (str): Query string or form body.

    Returns:
        dict[str, str]: Decoded names and values.
    """
    values = {}
    for part in text.split("&"):
        if not part:
            continue
        name, _, value = part.partition("=")
        values[url_decode(name)] = url_decode(value)
    return values


def parse_request(data):
    """
    Split a raw HTTP request.

    Args:
        data (bytes): Request line, headers and body.

    Returns:
        tuple: ``(method, path, query, body)``; query and body are dicts.
        ``(None, None, {}, {})`` if the request can't be read.
    """
    head, _, body = data.partition(b"\r\n\r\n")
    try:  # MicroPython raises on bad UTF-8 whatever "errors" says
        parts = head.split(b"\r\n")[0].decode("utf-8").split(" ")
        if len(parts) < 2:
            return None, None, {}, {}
        method, target = parts[0].upper(), parts[1]
        path, _, query = target.partition("?")
        form = parse_query(body.decode("utf-8")) if body else {}
        query = parse_query(query)
    except (UnicodeError, ValueError):
        return None, None, {}, {}
    return method, path, query, form


def content_length(head):
    """
    Read ``Content-Length`` from request headers.

    Args:
        head (bytes): Everything before the blank line.

    Returns:
        int: Declared body length (0 if absent or invalid).
    """
    for line in head.split(b"\r\n")[1:]:
        name, _, value = line.partition(b":")
        if name.strip().lower() == b"content-length":
            try:
                return max(0, int(value.strip()))
            except ValueError:
                return 0
    return 0


def ap_credentials(unique_id, random_bytes):
    """
    Name and password for the setup hotspot.

    Args:
        unique_id (bytes): ``machine.unique_id()``; the last two bytes name the hotspot.
        random_bytes (bytes): At least 4 random bytes for the password.

    Returns:
        tuple[str, str]: e.g. ``("GreenhouseSetup-3F2A", "40912873")``.
    """
    suffix = "".join("{:02X}".format(b) for b in unique_id[-2:])
    number = 0
    for b in random_bytes[:4]:
        number = number * 256 + b
    return "GreenhouseSetup-" + suffix, "{:08d}".format(number % 100000000)


def scan_networks(sta, attempts=3):
    """
    List nearby Wi-Fi networks, strongest first, one entry per name.

    The first scan after the radio is switched on often comes back empty on
    the Pico W, so an empty result is retried a couple of times.

    Args:
        sta: ``network.WLAN(STA_IF)``, active.
        attempts (int): Scans to try while nothing is found.

    Returns:
        list[tuple[str, int]]: ``(ssid, rssi_dbm)``; hidden networks left out.
    """
    found = []
    for attempt in range(attempts):
        try:
            found = sta.scan()
        except Exception as err:
            print("Wi-Fi scan failed:", err)
            found = []
        if found:
            break
        time.sleep_ms(500)
    best = {}
    for entry in found:
        try:
            ssid = entry[0].decode("utf-8") if isinstance(entry[0], bytes) else entry[0]
        except UnicodeError:
            continue
        if ssid and (ssid not in best or entry[3] > best[ssid]):
            best[ssid] = entry[3]
    return sorted(best.items(), key=lambda item: -item[1])


# --- setup code ------------------------------------------------------------


def decode_setup_code(code):
    """
    Read a setup code from the dashboard.

    The code is ``GH1-`` followed by URL-safe base64 of a small JSON object:
    ``h`` broker host, ``p`` port, ``u``/``w`` broker login, ``d`` device ID
    and ``z`` time zone (optional); ``t`` = 1 for an encrypted broker and
    ``c`` the root certificate to check it with (both optional). The server
    side is ``core/setup_code.py``.

    Args:
        code (str): The code as typed or pasted (spaces are ignored).

    Returns:
        dict: Config keys ``mqtt_broker``, ``mqtt_port``, ``mqtt_user``,
        ``mqtt_password``, ``mqtt_tls``, ``mqtt_ca``, ``device_id`` and, if
        present, ``timezone``.

    Raises:
        ValueError: If the code is not a valid setup code.
    """
    import binascii

    code = "".join(code.split())
    if not code.upper().startswith(CODE_PREFIX):
        raise ValueError("not a setup code")
    body = code[len(CODE_PREFIX):].replace("-", "+").replace("_", "/")
    body += "=" * (-len(body) % 4)
    try:
        data = json.loads(binascii.a2b_base64(body))
    except Exception:
        raise ValueError("damaged setup code")
    if not isinstance(data, dict):
        raise ValueError("damaged setup code")
    host, port, device = data.get("h"), data.get("p", 1883), data.get("d")
    if not isinstance(host, str) or not host or not _valid_port(port) or not _valid_device(device):
        raise ValueError("incomplete setup code")
    values = {
        "mqtt_broker": host,
        "mqtt_port": port,
        "mqtt_user": data.get("u") or None,
        "mqtt_password": data.get("w") or None,
        "mqtt_tls": data.get("t") == 1,
        "mqtt_ca": _root_name(data.get("c")) if data.get("t") == 1 else "",
        "device_id": device,
    }
    if isinstance(data.get("z"), str):
        values["timezone"] = data["z"]
    return values


def _root_name(value):
    """A root certificate name from a setup code, or "" (try them all) if it isn't a plain name."""
    if isinstance(value, str) and 0 < len(value) <= 40 and \
            all(c.isdigit() or c == "_" or "a" <= c <= "z" for c in value):
        return value
    return ""


def _valid_port(value):
    """Tell whether a value is a TCP port number."""
    return isinstance(value, int) and not isinstance(value, bool) and 0 < value < 65536


def _valid_device(value):
    """Tell whether a value is a device ID."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _to_int(text):
    """Convert form text to an int, or None."""
    try:
        return int(text.strip())
    except (ValueError, AttributeError):
        return None


# --- form -> settings --------------------------------------------------------


def form_to_settings(form, config):
    """
    Check the setup form and turn it into config changes.

    Blank password fields keep the current password when the network or
    login name is unchanged, so changing one setting doesn't mean retyping
    the others.

    With ``mode`` = ``standalone`` (no server) the server fields are ignored
    and Wi-Fi is optional: it only keeps the clock right.

    Args:
        form (dict[str, str]): Posted fields: ``ssid``, ``password``, ``mode``,
            ``code``, ``broker``, ``port``, ``tls``, ``user``, ``mqttpw``, ``device``, ``tz``.
        config (dict): Current configuration.

    Returns:
        tuple[dict, list[str]]: Config changes and error messages (changes
        are only complete when there are no errors).
    """
    errors = []
    standalone = form.get("mode") == "standalone"
    new = {"standalone": standalone}
    ssid = form.get("ssid", "").strip()
    password = form.get("password", "")
    if not ssid and not standalone:
        errors.append("Choose your Wi-Fi network.")
    elif len(ssid.encode("utf-8")) > 32:
        errors.append("That Wi-Fi name is too long (32 characters at most).")
    if password and not 8 <= len(password) <= 63:
        errors.append("Wi-Fi passwords are 8 to 63 characters long.")
    if not password and ssid == config["wifi_ssid"]:
        password = config["wifi_password"]
    new["wifi_ssid"], new["wifi_password"] = ssid, password if ssid else ""

    code = form.get("code", "").strip()
    if standalone:
        new["mqtt_broker"] = ""
    elif code:
        try:
            new.update(decode_setup_code(code))
        except ValueError:
            errors.append("The setup code wasn't recognised. Copy it again from the dashboard "
                          "(Settings, Controllers), or leave it empty and fill in the server details.")
    else:
        broker = form.get("broker", "").strip()
        port = _to_int(form.get("port", "1883"))
        device = _to_int(form.get("device", "1"))
        user = form.get("user", "").strip() or None
        mqtt_password = form.get("mqttpw", "") or None
        if mqtt_password is None and user == config["mqtt_user"]:
            mqtt_password = config["mqtt_password"]
        if broker in PLACEHOLDER_BROKERS:
            errors.append("Enter the setup code, or the server's address.")
        if not _valid_port(port):
            errors.append("The server port is a number from 1 to 65535 (usually 1883, or 8883 encrypted).")
        if not _valid_device(device):
            errors.append("The controller number is 1 or more.")
        tls = bool(form.get("tls"))
        same_broker = broker == config["mqtt_broker"] and tls == bool(config["mqtt_tls"])
        new.update({"mqtt_broker": broker, "mqtt_port": port, "mqtt_user": user,
                    "mqtt_password": mqtt_password, "device_id": device, "mqtt_tls": tls,
                    "mqtt_ca": config["mqtt_ca"] if same_broker else ""})

    zone = zones.find(form.get("tz") or new.get("timezone") or config["timezone"])
    if zone is None:
        errors.append("Choose a time zone.")
    else:
        new["timezone"], new["utc_offset_minutes"], new["dst_rule"] = zone
    if _valid_device(new.get("device_id")):
        new["mqtt_client_id"] = "greenhouse-device-{}".format(new["device_id"])
    return new, errors


RULE_FIELDS = (
    # form field, settings key, lowest, highest
    ("fan_t", "fan_on_temp_c", -20, 60),
    ("fan_h", "fan_on_humidity_pct", 0, 100),
    ("heat_t", "heater_on_temp_c", -20, 60),
)


def _to_float(text):
    """Convert form text to a float, or None."""
    try:
        return float(text.strip())
    except (ValueError, AttributeError):
        return None


def _valid_time(text):
    """Tell whether text is a 24-hour ``HH:MM`` time."""
    if not isinstance(text, str) or len(text) != 5 or text[2] != ":":
        return False
    hours, minutes = _to_int(text[:2]), _to_int(text[3:])
    return hours is not None and minutes is not None and 0 <= hours < 24 and 0 <= minutes < 60


def form_to_rules(form, current):
    """
    Check the rules section of the setup form (used without a server).

    Args:
        form (dict[str, str]): Posted fields ``fan_t``, ``fan_h``, ``heat_t``
            (trigger levels, °C and %) and ``w1``/``w1m``, ``w2``/``w2m``
            (watering start ``HH:MM`` and minutes; 0 minutes = off).
        current (dict): Current settings (buffers and slots 3-4 are kept).

    Returns:
        tuple[dict, list[str]]: New settings (valid for
        ``local_rules.valid_settings``) and error messages.
    """
    errors = []
    rules = {key: list(current[key]) for key in local_rules.THRESHOLD_KEYS}
    for field, key, low, high in RULE_FIELDS:
        value = _to_float(form.get(field, str(current[key][0])))
        if value is None or not low <= value <= high:
            errors.append("Rule levels must be numbers ({} to {} for this one).".format(low, high))
        else:
            rules[key][0] = value
    watering = [list(slot) for slot in current["watering"]]
    while len(watering) < local_rules.WATERING_SLOTS:
        watering.append(["00:00", 0])
    for index in (0, 1):
        start = form.get("w{}".format(index + 1), watering[index][0]).strip()
        minutes = _to_int(form.get("w{}m".format(index + 1), str(watering[index][1])))
        if not _valid_time(start):
            errors.append("Watering times look like 06:30 (24-hour clock).")
        elif minutes is None or not 0 <= minutes <= 240:
            errors.append("Watering lasts 0 to 240 minutes (0 = off).")
        else:
            watering[index] = [start, minutes]
    rules["watering"] = watering
    return rules, errors


# --- pages -----------------------------------------------------------------

STYLE = (
    "body{font-family:system-ui,sans-serif;max-width:30rem;margin:auto;padding:1rem;"
    "background:#f4f7f2;color:#1d2b1f}h1{font-size:1.4rem;color:#2e6b34}"
    "label{display:block;margin-top:.9rem;font-weight:600}"
    "input,select{width:100%;box-sizing:border-box;padding:.6rem;font-size:1rem;margin-top:.3rem;"
    "border:1px solid #9bb59e;border-radius:.4rem;background:#fff}"
    "button{margin-top:1.2rem;width:100%;padding:.8rem;font-size:1.1rem;border:0;border-radius:.4rem;"
    "background:#2e6b34;color:#fff}.err{background:#fde8e8;border:1px solid #d77;padding:.6rem;"
    "border-radius:.4rem}.hint{font-size:.85rem;color:#566;margin:.2rem 0}"
    "details{margin-top:1rem}summary{cursor:pointer;font-weight:600}"
)

INTROS = {
    REASON_NEW: "Welcome! Connect your greenhouse controller to your Wi-Fi and your greenhouse server.",
    REASON_BUTTON: "Change the controller's Wi-Fi or server settings.",
    REASON_WIFI_FAILED: "",
}


def _page_parts(title, parts):
    """Wrap page content (a list of pieces) in the shared HTML skeleton."""
    head = ("<!doctype html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>" + html_escape(title) + "</title><style>" + STYLE + "</style></head><body>")
    return [head] + parts + ["</body></html>"]


def _input(label, name, value="", kind="text", hint="", extra=""):
    """One labelled form field."""
    return ("<label>" + label + "<input type='" + kind + "' name='" + name + "' value='"
            + html_escape(value) + "' " + extra + "></label>"
            + ("<p class='hint'>" + hint + "</p>" if hint else ""))


def _zone_options(selected):
    """``<option>`` elements for every zone and fixed offset, one piece each."""
    parts = []
    for name, _offset, _rule in zones.ZONES + tuple(zones.fixed_offsets()):
        mark = " selected" if name == selected else ""
        parts.append("<option value='" + name + "'" + mark + ">" + name.replace("_", " ") + "</option>")
    return parts


def render_setup_page(config, networks, reason, values=None, errors=(), rules=None):
    """
    Build the setup form as one string (see :func:`setup_page_parts`).

    Returns:
        str: HTML.
    """
    return "".join(setup_page_parts(config, networks, reason, values, errors, rules))


def _number(value):
    """Show a number without a pointless ``.0``."""
    return "{:g}".format(value)


def _rules_parts(values, rules, open_):
    """The rules section (for running without a server)."""
    rules = rules or local_rules.default_settings()
    watering = rules["watering"]
    parts = ["<details" + (" open" if open_ else "") + "><summary>Rules for running on its own</summary>",
             "<p class='hint'>Only used without a server; with one, set them on the dashboard.</p>"]
    labels = {"fan_t": "Fan on above (°C)", "fan_h": "Fan on above humidity (%)",
              "heat_t": "Heater on below (°C)"}
    for field, key, _low, _high in RULE_FIELDS:
        parts.append(_input(labels[field], field, values.get(field, _number(rules[key][0])), "number",
                            extra="step='0.5'"))
    for index in (0, 1):
        name = "w{}".format(index + 1)
        parts.append(_input("Watering {} starts at".format(index + 1), name,
                            values.get(name, watering[index][0]), "time"))
        parts.append(_input("Watering {} minutes (0 = off)".format(index + 1), name + "m",
                            values.get(name + "m", watering[index][1]), "number"))
    parts.append("</details>")
    return parts


def setup_page_parts(config, networks, reason, values=None, errors=(), rules=None):
    """
    Build the setup form as a list of small pieces.

    The whole page is about 8 KB; the Pico often has no single free block
    that big once its code is loaded, so the page is kept and sent in pieces.

    Args:
        config (dict): Current configuration (passwords are never shown).
        networks (list[tuple[str, int]]): Nearby Wi-Fi networks.
        reason (str): Why setup is running (sets the intro or error text).
        values (dict | None): Form values to show again (after an error, or a
            ``code`` from the link on the dashboard).
        errors (list[str]): Problems to show at the top.
        rules (dict | None): Current local rules (default: the factory ones).

    Returns:
        list[str]: HTML pieces.
    """
    values = values or {}
    mode = values.get("mode") or ("standalone" if config["standalone"] else "server")
    ssid = values.get("ssid", config["wifi_ssid"])
    messages = list(errors)
    if reason == REASON_WIFI_FAILED and not errors:
        messages.append("The controller couldn't join <b>" + html_escape(config["wifi_ssid"]) +
                        "</b>. Check the network name and password. It must be a 2.4 GHz network.")
    parts = ["<h1>Greenhouse controller setup</h1>"]
    if INTROS.get(reason):
        parts.append("<p>" + INTROS[reason] + "</p>")
    if messages:
        parts.append("<div class='err'>" + "<br>".join(messages) + "</div>")
    options = "".join("<option value='" + html_escape(name) + "'>" for name, _rssi in networks)
    keep = " (leave empty to keep the current one)" if config["wifi_password"] else ""
    parts += [
        "<form method='post' action='/save'>",
        _input("Wi-Fi network", "ssid", ssid, extra="list='nets' autocomplete='off'",
               hint="Pick from the list or type the name. 2.4 GHz networks only. "
                    "<a href='/?rescan=1'>Look again</a>"),
        "<datalist id='nets'>" + options + "</datalist>",
        _input("Wi-Fi password", "password", "", "password", hint=("Case-sensitive" + keep + ".")),
        "<p><b>How will it run?</b></p>",
        "<label><input type='radio' name='mode' value='server'" + (" checked" if mode == "server" else "") +
        " style='width:auto'> With my greenhouse server (dashboard on a computer)</label>",
        "<label><input type='radio' name='mode' value='standalone'" + (" checked" if mode == "standalone" else "") +
        " style='width:auto'> On its own, without a server</label>",
        "<p class='hint'>On its own: it runs the rules below by itself. Wi-Fi is then optional; it only "
        "sets the clock, which the watering times need.</p>",
        _input("Setup code", "code", values.get("code", ""), extra="autocomplete='off'",
               hint="From the dashboard: Settings, Controllers. It tells the controller how to "
                    "reach your greenhouse server."),
        "<details" + (" open" if values.get("broker") else "") + "><summary>No setup code? "
        "Enter the server details</summary>",
        _input("Server address", "broker", values.get("broker", _shown_broker(config)),
               hint="The server computer's IP address, e.g. 192.168.1.20"),
        _input("Server port", "port", values.get("port", config["mqtt_port"]), "number",
               hint="1883, or 8883 for an encrypted (cloud) service."),
        "<label><input type='checkbox' name='tls' value='1'" +
        (" checked" if (values.get("tls") if values else config["mqtt_tls"]) else "") +
        " style='width:auto'> Encrypted connection (TLS), as cloud MQTT services need</label>",
        _input("Login name", "user", values.get("user", config["mqtt_user"] or "")),
        _input("Login password", "mqttpw", "", "password",
               hint="Leave empty to keep the current one." if config["mqtt_password"] else ""),
        _input("Controller number", "device", values.get("device", config["device_id"]), "number"),
        "</details>",
    ]
    parts += _rules_parts(values, rules, mode == "standalone")
    parts += [
        "<label>Time zone<select name='tz' id='tz'>",
    ]
    parts += _zone_options(values.get("tz", config["timezone"]))
    parts += [
        "</select></label>",
        "<button type='submit'>Save and connect</button></form>",
    ]
    if reason == REASON_NEW and not values.get("tz"):
        # Suggest the phone's own time zone when it's in the list.
        parts.append("<script>try{var z=Intl.DateTimeFormat().resolvedOptions().timeZone,"
                     "s=document.getElementById('tz');for(var i=0;i<s.options.length;i++)"
                     "if(s.options[i].value==z)s.selectedIndex=i;}catch(e){}</script>")
    return _page_parts("Greenhouse setup", parts)


def _shown_broker(config):
    """The broker address to pre-fill (placeholders shown as empty)."""
    return "" if config["mqtt_broker"] in PLACEHOLDER_BROKERS else config["mqtt_broker"]


def render_saved_page(ssid, standalone=False):
    """
    Build the page shown after saving.

    Args:
        ssid (str): Network the controller will join ("" for none).
        standalone (bool): It will run without a server.

    Returns:
        str: HTML.
    """
    return "".join(saved_page_parts(ssid, standalone))


def saved_page_parts(ssid, standalone=False):
    """The page shown after saving, as a list of pieces."""
    if not ssid:
        return _page_parts("Saved", [
            "<h1>Saved!</h1><p>The controller is restarting and will run on its own, without Wi-Fi. "
            "Its clock can't be set without Wi-Fi, so the watering times won't run; the fan and "
            "heater rules work.</p>",
            "<p>You can close this page and reconnect your phone to your usual Wi-Fi.</p>"])
    how = " and running on its own" if standalone else ""
    return _page_parts("Saved", [
        "<h1>Saved!</h1><p>The controller is restarting, joining <b>" + html_escape(ssid) + "</b>" + how +
        ". Its screen shows the time and temperature when it's ready.</p>",
        "<p>You can close this page and reconnect your phone to your usual Wi-Fi.</p>"
        "<p class='hint'>If the controller can't join the network, this setup hotspot comes "
        "back so you can fix it.</p>"])


def response_parts(parts, status="200 OK", headers=()):
    """
    Build an HTTP response as a list of small byte strings.

    Args:
        parts (list[str]): HTML pieces (may be empty).
        status (str): Status line text.
        headers (tuple[str, ...]): Extra header lines.

    Returns:
        list[bytes]: Headers first, then the encoded pieces.
    """
    body = [part.encode("utf-8") for part in parts]
    length = 0
    for chunk in body:
        length += len(chunk)
    lines = ["HTTP/1.1 " + status, "Content-Type: text/html; charset=utf-8",
             "Content-Length: " + str(length), "Cache-Control: no-store", "Connection: close"]
    lines.extend(headers)
    return [("\r\n".join(lines) + "\r\n\r\n").encode("utf-8")] + body


def http_response(body, status="200 OK", headers=()):
    """
    Build a complete HTTP response as one byte string (tests and small replies).

    Args:
        body (str): HTML (may be empty).
        status (str): Status line text.
        headers (tuple[str, ...]): Extra header lines.

    Returns:
        bytes: The response.
    """
    return b"".join(response_parts([body] if body else [], status, headers))


# --- DNS -------------------------------------------------------------------


def dns_reply(query, ip=AP_IP):
    """
    Answer a DNS query with this controller's address, whatever the name.

    This is what makes phones open the setup page on their own.

    Args:
        query (bytes): DNS request packet.
        ip (str): Address to answer with.

    Returns:
        bytes | None: Reply packet (with an answer for ``A`` queries only),
        or None for packets that are not a standard query.
    """
    if len(query) < 12 or query[2] & 0x80 or (query[2] >> 3) & 0x0F:
        return None  # a reply, or not a standard query
    if (query[4] << 8 | query[5]) < 1:
        return None
    end = 12
    while end < len(query) and query[end]:
        end += query[end] + 1
    end += 5  # zero byte, type, class
    if end > len(query):
        return None
    question = query[12:end]
    is_a = question[-4:-2] == b"\x00\x01"
    header = query[:2] + b"\x81\x80" + b"\x00\x01" + (b"\x00\x01" if is_a else b"\x00\x00") + b"\x00\x00\x00\x00"
    if not is_a:
        return header + question
    answer = b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04" + bytes([int(p) for p in ip.split(".")])
    return header + question + answer


# --- the portal ------------------------------------------------------------


class Portal:
    """
    The setup web page and DNS answers, polled without blocking.

    Attributes:
        saved (dict | None): Config changes once the form was saved.
    """

    def __init__(self, config, networks, reason, http=None, dns=None, rescan=None, ip=AP_IP):
        """
        Args:
            config (dict): Current configuration.
            networks (list[tuple[str, int]]): Nearby networks for the list.
            reason (str): Why setup is running.
            http: Listening, non-blocking TCP socket (port 80).
            dns: Bound, non-blocking UDP socket (port 53).
            rescan (callable | None): Returns a fresh network list.
            ip (str): This controller's address on the hotspot.
        """
        self.config = config
        self.networks = networks
        self.reason = reason
        self.http = http
        self.dns = dns
        self.rescan = rescan
        self.ip = ip
        self.saved = None
        self.rules = local_rules.load_settings() or local_rules.default_settings()
        self.saved_rules = None
        self.pending = []  # [connection, bytes so far, ticks when opened]

    def respond(self, raw):
        """
        Answer one HTTP request, as one byte string (see :meth:`respond_parts`).

        Args:
            raw (bytes): The request.

        Returns:
            bytes: The response.
        """
        return b"".join(self.respond_parts(raw))

    def respond_parts(self, raw):
        """
        Answer one HTTP request.

        ``/`` shows the form, ``POST /save`` checks and keeps it, and any
        other address is redirected to the form (captive portal).

        Args:
            raw (bytes): The request.

        Returns:
            list[bytes]: The response in small pieces.
        """
        method, path, query, form = parse_request(raw)
        if method is None:
            return response_parts([], "400 Bad Request")
        if path == "/save" and method == "POST":
            changes, errors = form_to_settings(form, self.config)
            rules = None
            if changes["standalone"]:
                rules, rule_errors = form_to_rules(form, self.rules)
                errors += rule_errors
            if errors:
                return response_parts(setup_page_parts(self.config, self.networks, self.reason, form, errors,
                                                       self.rules))
            self.saved, self.saved_rules = changes, rules
            return response_parts(saved_page_parts(changes["wifi_ssid"], changes["standalone"]))
        if path == "/":
            if query.get("rescan") and self.rescan:
                self.networks = self.rescan() or self.networks
            return response_parts(setup_page_parts(self.config, self.networks, self.reason, query, (), self.rules))
        return response_parts([], "302 Found", ("Location: http://" + self.ip + "/",))

    def poll(self):
        """
        Answer waiting DNS queries and serve web requests. Never raises or blocks.

        Phones and browsers open several connections at once, some of which
        stay idle, so connections are read without waiting: each one is
        answered as soon as its whole request has arrived, and one that stays
        idle for ``IDLE_MS`` (or is the oldest when ``MAX_PENDING`` are open)
        is closed.
        """
        self._poll_dns()
        if self.http is None:
            return
        while True:
            try:
                conn, _addr = self.http.accept()
            except OSError:
                break
            if len(self.pending) >= MAX_PENDING:
                self._close(self.pending.pop(0)[0])
            conn.setblocking(False)
            self.pending.append([conn, b"", time.ticks_ms()])
        for entry in list(self.pending):
            self._service(entry)

    def _poll_dns(self):
        """Answer up to a few waiting DNS queries."""
        if self.dns is None:
            return
        for _ in range(4):
            try:
                query, sender = self.dns.recvfrom(512)
            except OSError:
                return
            reply = dns_reply(query, self.ip)
            if reply:
                try:
                    self.dns.sendto(reply, sender)
                except OSError:
                    pass

    def _service(self, entry):
        """Read what has arrived on one connection; answer it once complete."""
        conn, data, opened = entry
        closed = False
        try:
            chunk = conn.recv(512)
            if chunk:
                data = entry[1] = data + chunk
            else:
                closed = True
        except OSError:
            pass  # nothing yet
        if request_complete(data):
            self.pending.remove(entry)
            try:
                gc.collect()
                conn.settimeout(5)
                send_in_pieces(conn, self.respond_parts(data))
            except Exception as err:
                print("Setup page error:", err)
            self._close(conn)
        elif closed or time.ticks_diff(time.ticks_ms(), opened) > IDLE_MS:
            self.pending.remove(entry)
            self._close(conn)

    @staticmethod
    def _close(conn):
        """Close a connection, ignoring errors."""
        try:
            conn.close()
        except OSError:
            pass


def send_in_pieces(conn, parts, size=SEND_CHUNK):
    """
    Send many small byte strings, grouped into packets of about ``size`` bytes.

    Args:
        conn: Connected socket.
        parts (list[bytes]): Response pieces.
        size (int): Target bytes per send.
    """
    batch = []
    batched = 0
    for part in parts:
        batch.append(part)
        batched += len(part)
        if batched >= size:
            conn.sendall(b"".join(batch))
            batch, batched = [], 0
    if batch:
        conn.sendall(b"".join(batch))


def request_complete(data):
    """
    Tell whether a whole HTTP request (headers and any body) has arrived.

    Args:
        data (bytes): What has been received so far.

    Returns:
        bool: True when it can be answered (also when it is too long to wait for).
    """
    if len(data) >= MAX_REQUEST:
        return True
    head, sep, body = data.partition(b"\r\n\r\n")
    return bool(sep) and len(body) >= min(content_length(head), MAX_REQUEST - len(head) - 4)


def read_request(conn):
    """
    Read one HTTP request (headers and body) from a connection.

    Args:
        conn: Connected socket.

    Returns:
        bytes: The request, cut off at ``MAX_REQUEST`` bytes.
    """
    data = b""
    while b"\r\n\r\n" not in data and len(data) < MAX_REQUEST:
        chunk = conn.recv(512)
        if not chunk:
            return data
        data += chunk
    head = data.partition(b"\r\n\r\n")[0]
    wanted = len(head) + 4 + min(content_length(head), MAX_REQUEST)
    while len(data) < wanted:
        chunk = conn.recv(512)
        if not chunk:
            break
        data += chunk
    return data


def disable_power_save(wlan):
    """
    Keep the Wi-Fi radio fully awake while the hotspot runs.

    In its default power-save mode the Pico W's radio misses packets from
    the phone, which drops off the hotspot or sees pages stall. Setup mode is
    short, so the extra power doesn't matter.

    Args:
        wlan: ``network.WLAN`` interface.
    """
    mode = getattr(wlan, "PM_NONE", None)
    if mode is None:
        return
    try:
        wlan.config(pm=mode)
    except Exception as err:  # not supported by this firmware
        print("Wi-Fi power save setting unavailable:", err)


def run_setup(config, display, reason, save=None):
    """
    Run setup mode on the hardware until saved (or timed out), then restart.

    Args:
        config (dict): Current configuration; updated and saved on success.
        display (display.Display): Shows the hotspot name and password.
        reason (str): Why setup is running.
        save (callable | None): Writes the config (default ``config.save_config``).
    """
    import machine
    import network
    import socket

    if save is None:
        from config import save_config as save
    display.show_message("Starting setup mode...")
    sta = network.WLAN(network.STA_IF)
    sta.active(True)
    try:
        sta.disconnect()  # stop a failed connection attempt so scanning works
    except Exception:
        pass
    networks = scan_networks(sta)
    name, password = ap_credentials(machine.unique_id(), os.urandom(4))
    ap = network.WLAN(network.AP_IF)
    ap.config(essid=name, password=password)
    ap.active(True)
    disable_power_save(ap)
    ip = ap.ifconfig()[0] or AP_IP

    http = socket.socket()
    http.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    http.bind(("0.0.0.0", 80))
    http.listen(MAX_PENDING + 2)  # phones open several connections at once
    http.setblocking(False)
    dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dns.bind(("0.0.0.0", 53))
    dns.setblocking(False)

    portal = Portal(config, networks, reason, http, dns, lambda: scan_networks(sta), ip)
    top = "WiFi failed: setup" if reason == REASON_WIFI_FAILED else "SETUP: join WiFi"
    display.show_lines([top, name[-20:], "Password " + password, "then open " + ip])
    print("Setup mode:", name, password, ip)
    timeout = setup_timeout_ms(reason)
    start = time.ticks_ms()
    while portal.saved is None:
        portal.poll()
        if timeout is not None and time.ticks_diff(time.ticks_ms(), start) > timeout:
            break
        time.sleep_ms(20)
    if portal.saved is not None:
        time.sleep_ms(1000)  # let the "Saved" page reach the phone
        config.update(portal.saved)
        save(config)
        if portal.saved_rules is not None:
            local_rules.save_settings(portal.saved_rules)
        if config["wifi_ssid"]:
            mark_unverified()
            display.show_message("Saved! Restarting and joining " + config["wifi_ssid"])
        else:
            display.show_message("Saved! Restarting to run on its own.")
        time.sleep_ms(2000)
    for sock in (http, dns):
        sock.close()
    ap.active(False)
    machine.reset()
