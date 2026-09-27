"""
Check deploy/mosquitto against the topics the code really uses (SEC-02): the
device account can publish and subscribe to exactly what the firmware needs,
the server account covers ingest and commands, and nobody is anonymous.
"""
import pytest

from support import REPO_ROOT

ACL = (REPO_ROOT / "deploy" / "mosquitto" / "greenhouse.acl").read_text(encoding="utf-8")
CONF = (REPO_ROOT / "deploy" / "mosquitto" / "greenhouse.conf").read_text(encoding="utf-8")


def parse_acl(text):
    rules, user = {}, None
    for line in text.splitlines():
        parts = line.split()
        if not parts or parts[0].startswith("#"):
            continue
        if parts[0] == "user":
            user = parts[1]
            rules[user] = []
        elif parts[0] == "topic":
            # "topic [read|write|readwrite] <pattern>"; no mode means readwrite.
            mode, pattern = (parts[1], parts[2]) if len(parts) == 3 else ("readwrite", parts[1])
            rules[user].append((pattern, mode))
    return rules


def matches(pattern, topic):
    """MQTT topic filter matching (+ one level, # the rest)."""
    p, t = pattern.split("/"), topic.split("/")
    for i, part in enumerate(p):
        if part == "#":
            return True
        if i >= len(t) or (part != "+" and part != t[i]):
            return False
    return len(p) == len(t)


def allowed(user, access, topic):
    return any(mode in (access, "readwrite") and matches(pattern, topic) for pattern, mode in RULES[user])


RULES = parse_acl(ACL)


def test_no_anonymous_access():
    assert "allow_anonymous false" in CONF.splitlines()
    assert "password_file /etc/mosquitto/greenhouse.passwd" in CONF
    assert "acl_file /etc/mosquitto/greenhouse.acl" in CONF


@pytest.mark.parametrize("topic", ["greenhouse/1/telemetry", "greenhouse/1/status", "greenhouse/1/relay/3/state"])
def test_device_can_publish_its_topics(topic):
    assert allowed("greenhouse-device-1", "write", topic)


def test_device_can_read_its_commands():
    assert allowed("greenhouse-device-1", "read", "greenhouse/1/relay/set")


@pytest.mark.parametrize(
    "access, topic",
    [
        ("write", "greenhouse/1/relay/set"),     # cannot command itself
        ("write", "greenhouse/2/telemetry"),     # cannot speak for another device
        ("read", "greenhouse/2/relay/set"),
        ("write", "other/topic"),
    ],
)
def test_device_is_confined(access, topic):
    assert not allowed("greenhouse-device-1", access, topic)


def test_server_covers_ingest_and_commands():
    from services import ingest

    for subscription in ingest.subscriptions("greenhouse"):
        concrete = subscription.replace("+", "1")
        assert allowed("greenhouse-server", "read", concrete)
    assert allowed("greenhouse-server", "write", "greenhouse/1/relay/set")


def test_topic_matcher():
    assert matches("greenhouse/+/relay/+/state", "greenhouse/1/relay/8/state")
    assert not matches("greenhouse/1/telemetry", "greenhouse/1/telemetry/x")
    assert matches("greenhouse/#", "greenhouse/1/relay/set")


def test_device_can_read_its_settings():
    assert allowed("greenhouse-device-1", "read", "greenhouse/1/settings")
    assert not allowed("greenhouse-device-1", "write", "greenhouse/1/settings")
    assert not allowed("greenhouse-device-1", "read", "greenhouse/2/settings")
