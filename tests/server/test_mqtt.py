"""Tests for server/core/mqtt.py with the paho publish helper mocked."""
import json

import pytest

from core import mqtt, settings


@pytest.fixture
def sent(monkeypatch):
    messages = []
    monkeypatch.setattr(mqtt, "single", lambda **kw: messages.append(kw))
    return messages


def test_command_topic_and_payload(sent):
    assert mqtt.publish_relay_command(relay_id=2, state=1, source="web") is True
    (msg,) = sent
    assert msg["topic"] == "greenhouse/1/relay/set"
    assert json.loads(msg["payload"]) == {"relay": 2, "state": 1, "source": "web"}
    assert (msg["hostname"], msg["port"], msg["qos"]) == ("localhost", 1883, 1)
    assert msg["auth"] is None


def test_credentials_are_sent_when_configured(sent, monkeypatch):
    monkeypatch.setattr(settings, "MQTT_USERNAME", "greenhouse")
    monkeypatch.setattr(settings, "MQTT_PASSWORD", "secret")
    mqtt.publish_relay_command(relay_id=1, state=0, source="auto", device_id=2)
    assert sent[0]["auth"] == {"username": "greenhouse", "password": "secret"}
    assert sent[0]["topic"] == "greenhouse/2/relay/set"


def test_broker_down_returns_false(monkeypatch):
    def refuse(**kw):
        raise ConnectionRefusedError("no broker")

    monkeypatch.setattr(mqtt, "single", refuse)
    assert mqtt.publish_relay_command(relay_id=2, state=1, source="web") is False
