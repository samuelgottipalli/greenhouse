"""
Minimal MQTT 3.1.1 client for MicroPython.

Vendored copy of ``umqtt.simple`` from micropython-lib, with two local changes:
sockets use a timeout (``SOCKET_TIMEOUT_S``) so an unreachable or silent broker
cannot block the main loop past the watchdog, and ``last_rx`` records when the
broker last sent anything (including ping replies) so a silently dead link can
be detected. Supports QoS 0 and 1
(QoS 2 is not implemented). Only the methods used by ``net.py`` are
documented here in detail; see the upstream project for protocol notes.
"""
import time

import usocket as socket
import ustruct as struct
from ubinascii import hexlify

SOCKET_TIMEOUT_S = 5


class MQTTException(Exception):
    """Raised when the broker rejects a CONNECT or SUBSCRIBE."""
    pass

class MQTTClient:
    """
    Blocking MQTT client over a raw (optionally TLS) socket.

    Call :meth:`set_callback` before :meth:`subscribe`, then poll with
    :meth:`check_msg` (non-blocking) or :meth:`wait_msg` (blocking).
    """

    def __init__(self, client_id, server, port=0, user=None, password=None, keepalive=0,
                 ssl=False, ssl_params={}):
        """
        Store connection settings; no network I/O happens until connect().

        Args:
            client_id (str | bytes): Unique client identifier.
            server (str): Broker hostname or IP address.
            port (int): Broker port; 0 selects 1883 (or 8883 with ssl).
            user (str | None): Username, if the broker requires auth.
            password (str | None): Password, if the broker requires auth.
            keepalive (int): Keepalive interval in seconds (0 disables it).
            ssl (bool | ssl.SSLContext): Wrap the socket in TLS. A context
                (the greenhouse uses one that checks the broker's certificate,
                see net.py) wraps it with the broker's name for SNI and the
                name check; ``True`` uses ``ussl.wrap_socket`` (no checks).
            ssl_params (dict): Extra arguments for ``ussl.wrap_socket``.
        """
        if port == 0:
            port = 8883 if ssl else 1883
        self.client_id = client_id
        self.sock = None
        self.raw_sock = None
        self.server = server
        self.port = port
        self.ssl = ssl
        self.ssl_params = ssl_params
        self.pid = 0
        self.cb = None
        self.user = user
        self.pswd = password
        self.keepalive = keepalive
        self.lw_topic = None
        self.lw_msg = None
        self.lw_qos = 0
        self.lw_retain = False
        self.last_rx = None

    def _send_str(self, s):
        """Write a length-prefixed MQTT string."""
        self.sock.write(struct.pack("!H", len(s)))
        self.sock.write(s)

    def _recv_len(self):
        """Read an MQTT variable-length "remaining length" field."""
        n = 0
        sh = 0
        while 1:
            b = self.sock.read(1)[0]
            n |= (b & 0x7f) << sh
            if not b & 0x80:
                return n
            sh += 7

    def set_callback(self, f):
        """
        Set the handler for incoming PUBLISH messages.

        Args:
            f (callable): Called as ``f(topic: bytes, msg: bytes)``.
        """
        self.cb = f

    def set_last_will(self, topic, msg, retain=False, qos=0):
        """
        Configure a last-will message sent by the broker if we drop off.

        Must be called before connect().
        """
        assert 0 <= qos <= 2
        assert topic
        self.lw_topic = topic
        self.lw_msg = msg
        self.lw_qos = qos
        self.lw_retain = retain

    def connect(self, clean_session=True):
        """
        Open the socket and perform the MQTT CONNECT handshake.

        Args:
            clean_session (bool): Ask the broker to discard prior session state.

        Returns:
            int: Session-present flag from CONNACK.

        Raises:
            OSError: On network errors.
            MQTTException: If the broker refuses the connection.
        """
        # The TCP socket keeps the timeout: MicroPython's TLS sockets have no
        # settimeout(), and reads through them wait as long as the TCP socket does.
        self.raw_sock = socket.socket()
        self.raw_sock.settimeout(SOCKET_TIMEOUT_S)
        addr = socket.getaddrinfo(self.server, self.port)[0][-1]
        self.raw_sock.connect(addr)
        self.sock = self.raw_sock
        if hasattr(self.ssl, "wrap_socket"):
            self.sock = self.ssl.wrap_socket(self.sock, server_hostname=self.server)
        elif self.ssl:
            import ussl
            self.sock = ussl.wrap_socket(self.sock, **self.ssl_params)
        premsg = bytearray(b"\x10\0\0\0\0\0")
        msg = bytearray(b"\x04MQTT\x04\x02\0\0")

        sz = 10 + 2 + len(self.client_id)
        msg[6] = clean_session << 1
        if self.user is not None:
            sz += 2 + len(self.user) + 2 + len(self.pswd)
            msg[6] |= 0xC0
        if self.keepalive:
            assert self.keepalive < 65536
            msg[7] |= self.keepalive >> 8
            msg[8] |= self.keepalive & 0x00FF
        if self.lw_topic:
            sz += 2 + len(self.lw_topic) + 2 + len(self.lw_msg)
            msg[6] |= 0x4 | (self.lw_qos & 0x1) << 3 | (self.lw_qos & 0x2) << 3
            msg[6] |= self.lw_retain << 5

        i = 1
        while sz > 0x7f:
            premsg[i] = (sz & 0x7f) | 0x80
            sz >>= 7
            i += 1
        premsg[i] = sz

        self.sock.write(premsg, i + 2)
        self.sock.write(msg)
        #print(hex(len(msg)), hexlify(msg, ":"))
        self._send_str(self.client_id)
        if self.lw_topic:
            self._send_str(self.lw_topic)
            self._send_str(self.lw_msg)
        if self.user is not None:
            self._send_str(self.user)
            self._send_str(self.pswd)
        resp = self.sock.read(4)
        self.last_rx = time.ticks_ms()
        assert resp[0] == 0x20 and resp[1] == 0x02
        if resp[3] != 0:
            print(MQTTException(resp[3]))
            print(resp[3])
            raise MQTTException(resp[3])
        return resp[2] & 1

    def disconnect(self):
        """Send DISCONNECT and close the socket."""
        self.sock.write(b"\xe0\0")
        self.sock.close()

    def ping(self):
        """Send PINGREQ; the response is consumed by wait_msg()."""
        self.sock.write(b"\xc0\0")

    def publish(self, topic, msg, retain=False, qos=0):
        """
        Publish a message.

        Args:
            topic (str | bytes): Topic name.
            msg (str | bytes): Payload.
            retain (bool): Ask the broker to retain the message.
            qos (int): 0 or 1. With QoS 1 this blocks until PUBACK arrives.
        """
        pkt = bytearray(b"\x30\0\0\0")
        pkt[0] |= qos << 1 | retain
        sz = 2 + len(topic) + len(msg)
        if qos > 0:
            sz += 2
        assert sz < 2097152
        i = 1
        while sz > 0x7f:
            pkt[i] = (sz & 0x7f) | 0x80
            sz >>= 7
            i += 1
        pkt[i] = sz
        #print(hex(len(pkt)), hexlify(pkt, ":"))
        self.sock.write(pkt, i + 1)
        self._send_str(topic)
        if qos > 0:
            self.pid += 1
            pid = self.pid
            struct.pack_into("!H", pkt, 0, pid)
            self.sock.write(pkt, 2)
        self.sock.write(msg)
        if qos == 1:
            while 1:
                op = self.wait_msg()
                if op == 0x40:
                    sz = self.sock.read(1)
                    assert sz == b"\x02"
                    rcv_pid = self.sock.read(2)
                    rcv_pid = rcv_pid[0] << 8 | rcv_pid[1]
                    if pid == rcv_pid:
                        return
        elif qos == 2:
            assert 0

    def subscribe(self, topic, qos=0):
        """
        Subscribe to a topic and wait for SUBACK.

        Args:
            topic (str | bytes): Topic filter.
            qos (int): Requested QoS.

        Raises:
            AssertionError: If set_callback() has not been called.
            MQTTException: If the broker rejects the subscription.
        """
        assert self.cb is not None, "Subscribe callback is not set"
        pkt = bytearray(b"\x82\0\0\0")
        self.pid += 1
        struct.pack_into("!BH", pkt, 1, 2 + 2 + len(topic) + 1, self.pid)
        #print(hex(len(pkt)), hexlify(pkt, ":"))
        self.sock.write(pkt)
        self._send_str(topic)
        self.sock.write(qos.to_bytes(1, "little"))
        while 1:
            op = self.wait_msg()
            if op == 0x90:
                resp = self.sock.read(4)
                #print(resp)
                assert resp[1] == pkt[2] and resp[2] == pkt[3]
                if resp[3] == 0x80:
                    raise MQTTException(resp[3])
                return

    # Wait for a single incoming MQTT message and process it.
    # Subscribed messages are delivered to a callback previously
    # set by .set_callback() method. Other (internal) MQTT
    # messages processed internally.
    def wait_msg(self):
        """
        Block until one packet arrives and process it.

        PUBLISH packets are passed to the callback; other packet types are
        returned to the caller.

        Returns:
            int | None: The packet type byte for non-PUBLISH packets, else None.
        """
        res = self.sock.read(1)
        self.raw_sock.settimeout(SOCKET_TIMEOUT_S)
        if res is None:
            return None
        if res == b"":
            raise OSError(-1)
        self.last_rx = time.ticks_ms()
        if res == b"\xd0":  # PINGRESP
            sz = self.sock.read(1)[0]
            assert sz == 0
            return None
        op = res[0]
        if op & 0xf0 != 0x30:
            return op
        sz = self._recv_len()
        topic_len = self.sock.read(2)
        topic_len = (topic_len[0] << 8) | topic_len[1]
        topic = self.sock.read(topic_len)
        sz -= topic_len + 2
        if op & 6:
            pid = self.sock.read(2)
            pid = pid[0] << 8 | pid[1]
            sz -= 2
        msg = self.sock.read(sz)
        self.cb(topic, msg)
        if op & 6 == 2:
            pkt = bytearray(b"\x40\x02\0\0")
            struct.pack_into("!H", pkt, 2, pid)
            self.sock.write(pkt)
        elif op & 6 == 4:
            assert 0

    # Checks whether a pending message from server is available.
    # If not, returns immediately with None. Otherwise, does
    # the same processing as wait_msg.
    def check_msg(self):
        """
        Process one pending packet if available, otherwise return immediately.

        Returns:
            int | None: See wait_msg().
        """
        self.sock.setblocking(False)
        return self.wait_msg()
