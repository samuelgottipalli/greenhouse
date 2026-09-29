"""
Tests for the controller's setup hotspot (picoside/device/provision.py) and
its time-zone table (zones.py).
"""
import base64
import importlib
import json
import socket
import struct
import sys
import types

import pytest

from pico_fakes import FakeWLAN
from support import PICO_TOOLS_DIR


def make_code(data):
    """Build a setup code the way the dashboard does."""
    return "GH1-" + base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")


CODE_DATA = {"h": "192.168.1.20", "p": 1883, "u": "greenhouse-device-2", "w": "s3cret-pass", "d": 2,
             "z": "Europe/Paris"}


@pytest.fixture
def blank(pico):
    """A new controller's configuration (defaults only)."""
    return pico.config.load_config("no_such_file.json")


def form(**fields):
    """A setup form with sensible values, overridden by ``fields``."""
    values = {"ssid": "greenhouse-net", "password": "wifi-password", "code": make_code(CODE_DATA), "tz": ""}
    values.update(fields)
    return values


# --- time zones ------------------------------------------------------------


def test_every_zone_matches_zoneinfo(pico, monkeypatch):
    monkeypatch.syspath_prepend(str(PICO_TOOLS_DIR))
    sys.modules.pop("setup_config", None)
    setup_config = importlib.import_module("setup_config")
    try:
        for name, offset, rule in pico.zones.ZONES:
            expected, warning = setup_config.timezone_settings(name, 2026)
            assert warning is None, name
            assert (offset, rule) == (expected["utc_offset_minutes"], expected["dst_rule"]), name
    finally:
        sys.modules.pop("setup_config", None)


def test_zone_names_are_unique_and_common_ones_present(pico):
    names = [zone[0] for zone in pico.zones.ZONES]
    assert len(names) == len(set(names))
    for name in ("America/Los_Angeles", "America/New_York", "Europe/London", "Asia/Kolkata", "UTC"):
        assert name in names


def test_fixed_offsets(pico):
    assert pico.zones.find("UTC+05:30") == ("UTC+05:30", 330, "none")
    assert pico.zones.find("UTC-12:00") == ("UTC-12:00", -720, "none")
    assert pico.zones.find("UTC+14:00") == ("UTC+14:00", 840, "none")
    assert pico.zones.find("Mars/Olympus") is None


# --- when setup runs -----------------------------------------------------


def test_setup_reason(pico, blank, config):
    p = pico.provision
    assert p.setup_reason(blank, False) == p.REASON_NEW
    assert p.setup_reason(dict(config, mqtt_broker="YOUR_MQTT_BROKER"), False) == p.REASON_NEW
    assert p.setup_reason(dict(config, wifi_ssid=""), True) == p.REASON_NEW
    assert p.setup_reason(config, True) == p.REASON_BUTTON
    assert p.setup_reason(config, False) is None


def test_setup_timeout(pico):
    p = pico.provision
    assert p.setup_timeout_ms(p.REASON_NEW) is None
    assert p.setup_timeout_ms(p.REASON_BUTTON) == p.SETUP_TIMEOUT_MS
    assert p.setup_timeout_ms(p.REASON_WIFI_FAILED) == p.SETUP_TIMEOUT_MS


class HeldPin:
    """A button that reads pressed (0) for the first ``pressed_reads`` reads."""

    def __init__(self, pressed_reads):
        self.reads = 0
        self.pressed_reads = pressed_reads

    def value(self):
        self.reads += 1
        return 0 if self.reads <= self.pressed_reads else 1


class RecordingDisplay:
    def __init__(self):
        self.messages = []
        self.lines = None

    def show_message(self, text):
        self.messages.append(text)

    def show_lines(self, lines):
        self.lines = lines


def test_button_not_held_starts_at_once(pico, ticks):
    display = RecordingDisplay()
    start = ticks.now
    assert pico.provision.button_held(HeldPin(0), display) is False
    assert ticks.now == start and display.messages == []


def test_button_held_long_enough(pico, ticks):
    display = RecordingDisplay()
    assert pico.provision.button_held(HeldPin(10**6), display) is True
    assert "Keep holding" in display.messages[0]


def test_button_released_early(pico):
    assert pico.provision.button_held(HeldPin(5), RecordingDisplay()) is False


def test_unverified_marker(pico):
    p = pico.provision
    assert not p.is_unverified()
    p.mark_unverified()
    assert p.is_unverified()
    p.clear_unverified()
    p.clear_unverified()  # no error when already gone
    assert not p.is_unverified()


# --- parsing -----------------------------------------------------------------


def test_url_decode(pico):
    decode = pico.provision.url_decode
    assert decode("My+Net%21") == "My Net!"
    assert decode("caf%C3%A9") == "café"
    assert decode("100%") == "100%"  # a stray percent sign is kept
    assert decode("%zz") == "%zz"


def test_parse_request_with_form_and_query(pico):
    raw = (b"POST /save?x=1 HTTP/1.1\r\nHost: 192.168.4.1\r\nContent-Length: 27\r\n\r\n"
           b"ssid=My+Net&password=a%26b%3D")
    method, path, query, body = pico.provision.parse_request(raw)
    assert (method, path, query) == ("POST", "/save", {"x": "1"})
    assert body == {"ssid": "My Net", "password": "a&b="}


def test_parse_request_rejects_garbage(pico):
    assert pico.provision.parse_request(b"")[0] is None
    assert pico.provision.parse_request(b"nonsense\r\n\r\n")[0] is None
    assert pico.provision.parse_request(b"GET /\xff HTTP/1.1\r\n\r\n")[0] is None
    assert pico.provision.parse_request(b"POST /save HTTP/1.1\r\n\r\nssid=%ff")[0] is None


def test_content_length(pico):
    assert pico.provision.content_length(b"POST / HTTP/1.1\r\ncontent-length: 12") == 12
    assert pico.provision.content_length(b"GET / HTTP/1.1\r\nHost: x") == 0
    assert pico.provision.content_length(b"POST / HTTP/1.1\r\nContent-Length: nope") == 0


class ChunkedConn:
    def __init__(self, data, size=7):
        self.chunks = [data[i:i + size] for i in range(0, len(data), size)]

    def recv(self, _n):
        return self.chunks.pop(0) if self.chunks else b""


def test_request_complete(pico):
    done = pico.provision.request_complete
    assert not done(b"")
    assert not done(b"GET / HTTP/1.1\r\nHost: x\r\n")
    assert done(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
    assert not done(b"POST /save HTTP/1.1\r\nContent-Length: 10\r\n\r\nssid=")
    assert done(b"POST /save HTTP/1.1\r\nContent-Length: 10\r\n\r\nssid=abcde")
    assert done(b"x" * pico.provision.MAX_REQUEST)


def test_read_request_waits_for_the_whole_body(pico):
    raw = b"POST /save HTTP/1.1\r\nContent-Length: 20\r\n\r\nssid=abc&password=xy"
    assert pico.provision.read_request(ChunkedConn(raw)) == raw


def test_ap_credentials(pico):
    name, password = pico.provision.ap_credentials(b"\x01\x02\x3f\x2a", b"\x00\x00\x01\x00")
    assert name == "GreenhouseSetup-3F2A"
    assert password == "00000256" and len(password) == 8


def test_scan_networks_dedupes_and_sorts(pico):
    wlan = FakeWLAN()
    wlan.networks = [
        (b"weak", b"", 1, -85, 3, 0),
        (b"strong", b"", 6, -40, 3, 0),
        (b"weak", b"", 11, -60, 3, 0),  # same name, better signal
        (b"", b"", 1, -30, 3, 1),  # hidden
        (b"\xff\xfe", b"", 1, -70, 3, 0),  # not UTF-8
    ]
    assert pico.provision.scan_networks(wlan) == [("strong", -40), ("weak", -60)]


def test_scan_retries_an_empty_first_result(pico):
    """Seen on the real Pico W: the first scan after switching the radio on is empty."""
    wlan = FakeWLAN()
    results = [[], [(b"home", b"", 6, -40, 3, 0)]]
    wlan.scan = lambda: results.pop(0)
    assert pico.provision.scan_networks(wlan) == [("home", -40)]
    empty = FakeWLAN()
    empty.networks = []
    assert pico.provision.scan_networks(empty) == []


def test_scan_failure_gives_empty_list(pico):
    class Broken:
        def scan(self):
            raise OSError("busy")

    assert pico.provision.scan_networks(Broken()) == []


# --- setup code ------------------------------------------------------------


def test_decode_setup_code(pico):
    values = pico.provision.decode_setup_code(make_code(CODE_DATA))
    assert values == {"mqtt_broker": "192.168.1.20", "mqtt_port": 1883, "mqtt_user": "greenhouse-device-2",
                      "mqtt_password": "s3cret-pass", "mqtt_tls": False, "mqtt_ca": "", "device_id": 2,
                      "timezone": "Europe/Paris"}


@pytest.mark.parametrize("extra, tls, ca", [
    ({"t": 1, "c": "isrg_root_x1"}, True, "isrg_root_x1"),
    ({"t": 1}, True, ""),                             # no root named: try them all
    ({"t": 1, "c": "../../config"}, True, ""),        # not a plain name: ignored
    ({"t": 1, "c": 5}, True, ""),
    ({"c": "isrg_root_x1"}, False, ""),               # a root without t means nothing
])
def test_decode_setup_code_for_an_encrypted_broker(pico, extra, tls, ca):
    values = pico.provision.decode_setup_code(make_code(dict(CODE_DATA, p=8883, **extra)))
    assert (values["mqtt_tls"], values["mqtt_ca"], values["mqtt_port"]) == (tls, ca, 8883)


def test_decode_setup_code_tolerates_spaces_and_case(pico):
    code = make_code({"h": "10.0.0.5", "d": 1})
    spaced = "gh1-" + " ".join(code[4:][i:i + 5] for i in range(0, len(code) - 4, 5))
    values = pico.provision.decode_setup_code(spaced)
    assert values["mqtt_broker"] == "10.0.0.5" and values["mqtt_port"] == 1883
    assert values["mqtt_user"] is None and "timezone" not in values


@pytest.mark.parametrize("code", [
    "hello",
    "GH1-!!!!",
    "GH1-" + base64.urlsafe_b64encode(b"[1, 2]").decode(),
    make_code({"h": "", "d": 1}),
    make_code({"h": "host", "d": 0}),
    make_code({"h": "host", "d": 1, "p": 70000}),
    make_code({"h": "host", "d": True}),
])
def test_bad_setup_codes(pico, code):
    with pytest.raises(ValueError):
        pico.provision.decode_setup_code(code)


# --- form checks -------------------------------------------------------------


def test_form_with_setup_code(pico, blank):
    changes, errors = pico.provision.form_to_settings(form(), blank)
    assert errors == []
    assert changes["wifi_ssid"] == "greenhouse-net" and changes["wifi_password"] == "wifi-password"
    assert changes["mqtt_broker"] == "192.168.1.20" and changes["device_id"] == 2
    assert changes["mqtt_client_id"] == "greenhouse-device-2"
    # No zone picked on the page: the code's zone is used.
    assert (changes["timezone"], changes["utc_offset_minutes"], changes["dst_rule"]) == ("Europe/Paris", 60, "eu")


def test_form_zone_choice_beats_code(pico, blank):
    changes, errors = pico.provision.form_to_settings(form(tz="America/Chicago"), blank)
    assert not errors and (changes["utc_offset_minutes"], changes["dst_rule"]) == (-360, "us")


def test_form_with_manual_server_details(pico, blank):
    fields = form(code="", broker="192.168.1.9", port="1884", user="greenhouse-device-1", mqttpw="pw",
                  device="1", tz="UTC+05:30")
    changes, errors = pico.provision.form_to_settings(fields, blank)
    assert errors == []
    assert (changes["mqtt_broker"], changes["mqtt_port"], changes["mqtt_user"], changes["mqtt_password"]) == \
        ("192.168.1.9", 1884, "greenhouse-device-1", "pw")
    assert changes["utc_offset_minutes"] == 330


def test_form_keeps_current_passwords_when_left_blank(pico, config):
    config.update({"mqtt_user": "greenhouse-device-1", "mqtt_password": "old-mqtt"})
    fields = form(password="", code="", broker="10.0.0.2", user="greenhouse-device-1", mqttpw="", device="1")
    changes, errors = pico.provision.form_to_settings(fields, config)
    assert errors == []
    assert changes["wifi_password"] == "pw" and changes["mqtt_password"] == "old-mqtt"
    # A different network with no password is an open network.
    changes, _ = pico.provision.form_to_settings(form(ssid="cafe", password=""), config)
    assert changes["wifi_password"] == ""


def test_form_with_manual_encrypted_broker(pico, blank):
    fields = form(code="", broker="abc.s1.eu.hivemq.cloud", port="8883", tls="1", user="gh1", mqttpw="pw",
                  device="1")
    changes, errors = pico.provision.form_to_settings(fields, blank)
    assert errors == []
    assert (changes["mqtt_tls"], changes["mqtt_ca"], changes["mqtt_port"]) == (True, "", 8883)


def test_form_keeps_the_found_root_for_the_same_broker(pico, config):
    config.update({"mqtt_broker": "abc.s1.eu.hivemq.cloud", "mqtt_tls": True, "mqtt_ca": "isrg_root_x1"})
    fields = form(code="", broker="abc.s1.eu.hivemq.cloud", port="8883", tls="1", user="u", mqttpw="p", device="1")
    changes, _ = pico.provision.form_to_settings(fields, config)
    assert changes["mqtt_ca"] == "isrg_root_x1"
    changes, _ = pico.provision.form_to_settings(dict(fields, broker="other.example"), config)
    assert changes["mqtt_ca"] == ""  # a different broker: find its root again
    changes, _ = pico.provision.form_to_settings(dict(fields, tls=""), config)
    assert changes["mqtt_tls"] is False and changes["mqtt_ca"] == ""


def test_setup_page_has_the_encryption_box(pico, config):
    html = pico.provision.render_setup_page(config, [], "button")
    assert "name='tls'" in html and "name='tls' value='1' checked" not in html
    config["mqtt_tls"] = True
    assert "name='tls' value='1' checked" in pico.provision.render_setup_page(config, [], "button")
    # After a form error, the page shows what was posted (the box was left unticked).
    html = pico.provision.render_setup_page(config, [], "button", values={"ssid": "x"}, errors=["e"])
    assert "name='tls' value='1' checked" not in html


@pytest.mark.parametrize("fields, message", [
    ({"ssid": ""}, "Choose your Wi-Fi network"),
    ({"ssid": "x" * 33}, "too long"),
    ({"password": "short"}, "8 to 63"),
    ({"code": "GH1-garbage"}, "setup code wasn't recognised"),
    ({"code": "", "broker": ""}, "server's address"),
    ({"code": "", "broker": "h", "port": "0"}, "port"),
    ({"code": "", "broker": "h", "device": "zero"}, "controller number"),
    ({"tz": "Mars/Olympus"}, "time zone"),
])
def test_form_errors(pico, blank, fields, message):
    _changes, errors = pico.provision.form_to_settings(form(**fields), blank)
    assert any(message in error for error in errors), errors


# --- pages -------------------------------------------------------------------


def test_setup_page_lists_networks_and_escapes(pico, blank):
    html = pico.provision.render_setup_page(blank, [("<b>evil</b>", -40), ("home", -60)], "new")
    assert "&lt;b&gt;evil&lt;/b&gt;" in html and "<b>evil</b>" not in html
    assert "<option value='home'>" in html
    assert "Welcome" in html
    assert "Intl.DateTimeFormat" in html  # suggests the phone's time zone


def test_setup_page_never_shows_passwords(pico, config):
    config.update({"wifi_password": "wifi-secret", "mqtt_password": "mqtt-secret"})
    html = pico.provision.render_setup_page(config, [], "button")
    assert "wifi-secret" not in html and "mqtt-secret" not in html
    assert "keep the current one" in html
    assert "Intl.DateTimeFormat" not in html  # keeps the saved zone
    assert "<option value='UTC' selected>" in html


def test_setup_page_after_wifi_failure(pico, config):
    html = pico.provision.render_setup_page(config, [], "wifi_failed")
    assert "couldn't join <b>greenhouse-net</b>" in html and "2.4 GHz" in html


def test_saved_page(pico):
    html = pico.provision.render_saved_page("My <Net>")
    assert "My &lt;Net&gt;" in html and "restarting" in html


def test_http_response(pico):
    response = pico.provision.http_response("héllo")
    head, body = response.split(b"\r\n\r\n")
    assert head.startswith(b"HTTP/1.1 200 OK") and b"Content-Length: 6" in head
    assert body == "héllo".encode()


# --- portal ------------------------------------------------------------------


def get(path):
    return "GET {} HTTP/1.1\r\nHost: 192.168.4.1\r\n\r\n".format(path).encode()


def post(fields):
    body = "&".join("{}={}".format(k, v) for k, v in fields.items()).encode()
    return b"POST /save HTTP/1.1\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body


def test_portal_shows_form(pico, blank):
    portal = pico.provision.Portal(blank, [("home", -50)], "new")
    response = portal.respond(get("/"))
    assert response.startswith(b"HTTP/1.1 200") and b"Greenhouse controller setup" in response


def test_portal_redirects_everything_else(pico, blank):
    portal = pico.provision.Portal(blank, [], "new")
    for path in ("/generate_204", "/hotspot-detect.html", "/connecttest.txt"):
        response = portal.respond(get(path))
        assert response.startswith(b"HTTP/1.1 302") and b"Location: http://192.168.4.1/" in response
    assert portal.respond(b"\r\n\r\n").startswith(b"HTTP/1.1 400")


def test_portal_prefills_code_from_link(pico, blank):
    portal = pico.provision.Portal(blank, [], "new")
    assert b"value='GH1-abc'" in portal.respond(get("/?code=GH1-abc"))


def test_portal_rescan(pico, blank):
    portal = pico.provision.Portal(blank, [], "new", rescan=lambda: [("fresh-net", -30)])
    assert b"fresh-net" in portal.respond(get("/?rescan=1"))


def test_portal_save(pico, blank):
    portal = pico.provision.Portal(blank, [], "new")
    fields = {"ssid": "home", "password": "wifi-password", "code": make_code(CODE_DATA), "tz": "UTC"}
    response = portal.respond(post(fields))
    assert b"Saved!" in response
    assert portal.saved["wifi_ssid"] == "home" and portal.saved["timezone"] == "UTC"


def test_portal_save_with_errors_keeps_values(pico, blank):
    portal = pico.provision.Portal(blank, [], "new")
    response = portal.respond(post({"ssid": "home", "password": "x", "code": "", "broker": "10.1.1.1"}))
    assert portal.saved is None
    assert b"8 to 63" in response and b"value='10.1.1.1'" in response


# --- DNS ---------------------------------------------------------------------


def dns_query(name, qtype=1, flags=0x0100):
    labels = b"".join(bytes([len(part)]) + part.encode() for part in name.split("."))
    return struct.pack(">HHHHHH", 0x1234, flags, 1, 0, 0, 0) + labels + b"\x00" + struct.pack(">HH", qtype, 1)


def test_dns_answers_every_name_with_the_controller(pico):
    reply = pico.provision.dns_reply(dns_query("connectivitycheck.gstatic.com"))
    ident, flags, qd, an, _ns, _ar = struct.unpack(">HHHHHH", reply[:12])
    assert (ident, flags, qd, an) == (0x1234, 0x8180, 1, 1)
    assert reply.endswith(bytes([192, 168, 4, 1]))


def test_dns_no_answer_for_ipv6(pico):
    reply = pico.provision.dns_reply(dns_query("apple.com", qtype=28))
    assert struct.unpack(">HHHHHH", reply[:12])[3] == 0


@pytest.mark.parametrize("packet", [
    b"",
    b"\x00" * 11,
    dns_query("x.com", flags=0x8180),  # a reply, not a query
    dns_query("x.com", flags=0x2800),  # an update, not a standard query
    dns_query("x.com")[:14],  # cut short
])
def test_dns_ignores_bad_packets(pico, packet):
    assert pico.provision.dns_reply(packet) is None


def test_portal_poll_over_real_sockets(pico, blank):
    http = socket.socket()
    http.bind(("127.0.0.1", 0))
    http.listen(2)
    http.setblocking(False)
    dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dns.bind(("127.0.0.1", 0))
    dns.setblocking(False)
    portal = pico.provision.Portal(blank, [], "new", http, dns)
    try:
        portal.poll()  # nothing waiting: returns quietly

        client = socket.create_connection(http.getsockname(), timeout=5)
        client.sendall(get("/"))
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.settimeout(5)
        udp.sendto(dns_query("example.com"), dns.getsockname())
        import time

        time.sleep(0.1)
        portal.poll()
        response = b""
        while chunk := client.recv(4096):
            response += chunk
        assert response.startswith(b"HTTP/1.1 200") and b"Greenhouse" in response
        assert udp.recvfrom(512)[0].endswith(bytes([192, 168, 4, 1]))
        client.close()
        udp.close()
    finally:
        http.close()
        dns.close()


def test_page_is_sent_in_small_pieces(pico, blank):
    """The Pico often has no free 8 KB block, so no piece of the page may be that big."""
    portal = pico.provision.Portal(blank, [("home", -50)], "new")
    parts = portal.respond_parts(get("/"))
    assert b"".join(parts) == portal.respond(get("/"))
    assert len(b"".join(parts)) > 6000 and max(len(p) for p in parts) < 1500
    head, _, body = b"".join(parts).partition(b"\r\n\r\n")
    assert b"Content-Length: " + str(len(body)).encode() in head

    sent = []

    class Conn:
        def sendall(self, data):
            sent.append(data)

    pico.provision.send_in_pieces(Conn(), parts)
    assert b"".join(sent) == b"".join(parts)
    assert len(sent) < len(parts) and max(len(s) for s in sent) < 2600


def test_power_save_helper_copes_with_old_firmware(pico):
    class Old:
        pass

    class Refuses:
        PM_NONE = 1

        def config(self, **kw):
            raise ValueError("unknown config param")

    pico.provision.disable_power_save(Old())
    pico.provision.disable_power_save(Refuses())


def test_idle_connection_does_not_block_others(pico, blank, ticks):
    """Browsers open spare connections that send nothing; the page must still load at once."""
    http = socket.socket()
    http.bind(("127.0.0.1", 0))
    http.listen(4)
    http.setblocking(False)
    portal = pico.provision.Portal(blank, [], "new", http, None)
    address = http.getsockname()
    idle = socket.create_connection(address, timeout=5)
    real = socket.create_connection(address, timeout=5)
    import time

    try:
        time.sleep(0.05)
        portal.poll()  # accepts both; the idle one has nothing to read
        real.sendall(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
        time.sleep(0.05)
        portal.poll()
        response = b""
        while chunk := real.recv(4096):
            response += chunk
        assert response.startswith(b"HTTP/1.1 200")
        assert len(portal.pending) == 1  # the idle one is still waiting
        ticks.advance(pico.provision.IDLE_MS + 1)
        portal.poll()
        assert portal.pending == []
        assert idle.recv(10) == b""  # closed
    finally:
        idle.close()
        real.close()
        http.close()


def test_too_many_connections_close_the_oldest(pico, blank):
    class Conn:
        def __init__(self):
            self.closed = False

        def setblocking(self, flag):
            pass

        def recv(self, n):
            raise OSError(11)

        def close(self):
            self.closed = True

    conns = [Conn() for _ in range(pico.provision.MAX_PENDING + 1)]
    waiting = list(conns)

    class Listener:
        def accept(self):
            if not waiting:
                raise OSError(11)
            return waiting.pop(0), ("192.168.4.2", 1)

    portal = pico.provision.Portal(blank, [], "new", Listener(), None)
    portal.poll()
    assert conns[0].closed and len(portal.pending) == pico.provision.MAX_PENDING


# --- saving ------------------------------------------------------------------


def test_save_config_round_trip(pico, tmp_path, blank):
    blank["wifi_ssid"] = "home"
    pico.config.save_config(blank)
    pico.config.save_config(blank)  # replacing an existing file works too
    assert pico.config.load_config()["wifi_ssid"] == "home"
    assert not (tmp_path / "config.json.tmp").exists()


# --- run_setup on (fake) hardware ------------------------------------------


class FakeConn:
    def __init__(self, request):
        self.request = request
        self.sent = b""

    def settimeout(self, _t):
        pass

    def setblocking(self, _flag):
        pass

    def recv(self, _n):
        data, self.request = self.request, b""
        return data

    def sendall(self, data):
        self.sent += data

    def close(self):
        pass


class FakeSocketModule(types.ModuleType):
    SOL_SOCKET, SO_REUSEADDR, AF_INET, SOCK_DGRAM = 1, 2, 3, 4

    def __init__(self, requests):
        super().__init__("socket")
        self.requests = list(requests)
        self.conns = []
        self.bound = []
        module = self

        class Sock:
            def __init__(self, *args):
                self.closed = False

            def setsockopt(self, *a):
                pass

            def bind(self, addr):
                module.bound.append(addr)

            def listen(self, n):
                pass

            def setblocking(self, flag):
                pass

            def accept(self):
                if not module.requests:
                    raise OSError(11)
                conn = FakeConn(module.requests.pop(0))
                module.conns.append(conn)
                return conn, ("192.168.4.2", 5000)

            def recvfrom(self, n):
                raise OSError(11)

            def close(self):
                self.closed = True

        self.socket = Sock


@pytest.fixture
def hardware(fake_env, monkeypatch):
    resets = []
    fake_env.machine.reset = lambda: resets.append(True)
    wlans = {}

    def wlan(mode):
        wlans.setdefault(mode, FakeWLAN(mode))
        return wlans[mode]

    fake_env.network.WLAN = wlan

    def install(requests):
        module = FakeSocketModule(requests)
        monkeypatch.setitem(sys.modules, "socket", module)
        return module

    return types.SimpleNamespace(resets=resets, wlans=wlans, install=install)


def test_run_setup_saves_and_restarts(pico, blank, hardware, tmp_path):
    fields = {"ssid": "greenhouse-net", "password": "wifi-password", "code": make_code(CODE_DATA), "tz": ""}
    sockets = hardware.install([get("/"), post(fields)])
    display = RecordingDisplay()
    pico.provision.run_setup(blank, display, "new")

    ap = hardware.wlans[1]
    assert ap.settings["essid"] == "GreenhouseSetup-3F2A" and len(ap.settings["password"]) == 8
    assert ap.pm == FakeWLAN.PM_NONE  # power save off: it made phones drop off the hotspot
    assert display.lines[1] == "GreenhouseSetup-3F2A" and ap.settings["password"] in display.lines[2]
    assert ("0.0.0.0", 80) in sockets.bound and ("0.0.0.0", 53) in sockets.bound
    assert b"greenhouse-net" in sockets.conns[0].sent  # scanned network offered
    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved["wifi_ssid"] == "greenhouse-net" and saved["mqtt_broker"] == "192.168.1.20"
    assert saved["device_id"] == 2 and saved["dst_rule"] == "eu"
    assert pico.provision.is_unverified()
    assert hardware.resets == [True]


def test_run_setup_times_out_when_already_configured(pico, config, hardware, tmp_path):
    hardware.install([])
    pico.provision.run_setup(config, RecordingDisplay(), "button")
    assert hardware.resets == [True]
    assert not (tmp_path / "config.json").exists()  # nothing changed
    assert not pico.provision.is_unverified()


# --- main.py decides when to run setup --------------------------------------


class SetupCalled(BaseException):
    """Stops main.py where it would start setup mode."""


@pytest.fixture
def no_broker(monkeypatch):
    """MicroPython socket modules for umqtt, with a broker that can't be reached."""
    import binascii

    usocket = types.ModuleType("usocket")

    def unreachable(host, port):
        raise OSError(-2)

    usocket.getaddrinfo = unreachable
    usocket.socket = lambda: types.SimpleNamespace(settimeout=lambda t: None, close=lambda: None)
    monkeypatch.setitem(sys.modules, "usocket", usocket)
    monkeypatch.setitem(sys.modules, "ustruct", struct)
    monkeypatch.setitem(sys.modules, "ubinascii", binascii)


@pytest.fixture
def boot_main(fake_env, monkeypatch, tmp_path, no_broker):
    calls = []

    def _boot(config, wifi_works=True, hold_button=False):
        if config is not None:
            (tmp_path / "config.json").write_text(json.dumps(config))

        def wlan(mode):
            w = FakeWLAN(mode)
            w.connect_succeeds = wifi_works
            return w

        fake_env.network.WLAN = wlan
        if hold_button:
            class Held:
                PULL_UP, IN, OUT, IRQ_FALLING = 2, 0, 1, 4

                def __init__(self, *a, **k):
                    pass

                def value(self, v=None):
                    return 0

                def irq(self, **k):
                    pass

            fake_env.machine.Pin = Held
        provision = importlib.import_module("provision")

        def fake_setup(cfg, display, reason, save=None):
            calls.append(reason)
            raise SetupCalled

        monkeypatch.setattr(provision, "run_setup", fake_setup)
        with pytest.raises(SetupCalled):
            importlib.import_module("main")
        return calls

    return _boot


GOOD = {"wifi_ssid": "net", "wifi_password": "password1", "mqtt_broker": "broker.local", "watchdog": False}


def test_main_new_controller_starts_setup(boot_main):
    assert boot_main(None) == ["new"]


def test_main_button_held_starts_setup(boot_main):
    assert boot_main(GOOD, hold_button=True) == ["button"]


def test_main_first_boot_wifi_failure_returns_to_setup(boot_main, tmp_path):
    (tmp_path / "wifi_unverified").write_text("1")
    assert boot_main(GOOD, wifi_works=False) == ["wifi_failed"]


def test_main_router_outage_does_not_start_setup(fake_env, monkeypatch, tmp_path, no_broker):
    """With settings that have worked before, a Wi-Fi failure just keeps retrying."""
    (tmp_path / "config.json").write_text(json.dumps(GOOD))

    def wlan(mode):
        w = FakeWLAN(mode)
        w.connect_succeeds = False
        return w

    fake_env.network.WLAN = wlan
    controller = importlib.import_module("controller")

    class Looping(BaseException):
        pass

    def tick(self):
        raise Looping

    monkeypatch.setattr(controller.Controller, "tick", tick)
    with pytest.raises(Looping):
        importlib.import_module("main")


def test_main_first_successful_boot_clears_marker(fake_env, monkeypatch, tmp_path, no_broker):
    (tmp_path / "config.json").write_text(json.dumps(GOOD))
    (tmp_path / "wifi_unverified").write_text("1")
    fake_env.network.WLAN = FakeWLAN
    controller = importlib.import_module("controller")

    class Looping(BaseException):
        pass

    def tick(self):
        raise Looping

    monkeypatch.setattr(controller.Controller, "tick", tick)
    with pytest.raises(Looping):
        importlib.import_module("main")
    assert not (tmp_path / "wifi_unverified").exists()
