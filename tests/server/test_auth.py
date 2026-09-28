"""Tests for the dashboard login (SEC-03): hashing, the password script and the gate."""
import pytest
from streamlit.testing.v1 import AppTest

from core import auth, settings
from scripts import set_password
from support import SERVER_DIR

HASH = auth.hash_password("correct horse", iterations=1000)


def test_hash_round_trip():
    assert auth.verify_password("correct horse", HASH)
    assert not auth.verify_password("wrong horse", HASH)


def test_hash_is_salted_and_has_no_dollar_signs():
    other = auth.hash_password("correct horse", iterations=1000)
    assert other != HASH
    assert "$" not in HASH and HASH.startswith("pbkdf2_sha256:1000:")


@pytest.mark.parametrize("stored", ["", "garbage", "md5:1:00:00", "pbkdf2_sha256:x:00:00", "pbkdf2_sha256:10:zz:00"])
def test_malformed_hash_never_matches(stored):
    assert auth.verify_password("anything", stored) is False


def test_set_password_writes_env(tmp_path):
    env = tmp_path / ".env"
    env.write_text("MQTT_HOST=broker\nAPP_PASSWORD_HASH=old\n", encoding="utf-8")
    answers = iter(["s3cret-pass", "s3cret-pass"])
    assert set_password.main(env, ask=lambda _: next(answers)) == 0
    lines = env.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "MQTT_HOST=broker"
    (stored,) = [l.split("=", 1)[1] for l in lines if l.startswith("APP_PASSWORD_HASH=")]
    assert auth.verify_password("s3cret-pass", stored)


@pytest.mark.parametrize("answers", [["short", "short"], ["long-enough-1", "different-2"]])
def test_set_password_rejects_bad_input(tmp_path, answers):
    env = tmp_path / ".env"
    it = iter(answers)
    assert set_password.main(env, ask=lambda _: next(it)) == 1
    assert not env.exists()


def test_env_value_survives_dotenv(tmp_path):
    from dotenv import dotenv_values

    env = tmp_path / ".env"
    set_password.write_hash(env, HASH)
    assert dotenv_values(env)["APP_PASSWORD_HASH"] == HASH


@pytest.fixture
def protected(monkeypatch, seeded_db):
    monkeypatch.setattr(settings, "APP_PASSWORD_HASH", HASH)
    import ui

    monkeypatch.setattr(ui, "sleep", lambda seconds: None)
    return AppTest.from_file(str(SERVER_DIR / "app.py"), default_timeout=30)


def test_login_required(protected):
    at = protected.run()
    assert at.text_input[0].label == "Password"
    assert not at.metric  # no page content before login


def test_wrong_password(protected):
    at = protected.run()
    at.text_input[0].input("nope")
    at.button[0].click().run()
    assert at.error[0].value == "Wrong password."
    assert "authenticated" not in at.session_state


def test_right_password_then_logout(protected):
    at = protected.run()
    at.text_input[0].input("correct horse")
    at.button[0].click().run()
    assert at.session_state["authenticated"] is True
    assert not at.text_input
    at.sidebar.button[0].click().run()
    assert "authenticated" not in at.session_state
    assert at.text_input[0].label == "Password"


def test_open_dashboard_warns_without_password(monkeypatch, seeded_db):
    monkeypatch.setattr(settings, "APP_PASSWORD_HASH", None)
    at = AppTest.from_file(str(SERVER_DIR / "app.py"), default_timeout=30).run()
    assert "No dashboard password is set" in at.sidebar.warning[0].value


# --- keep me logged in (browser cookie) ---------------------------------------


def test_login_token_round_trip():
    from core.auth import login_token_valid, make_login_token

    token = make_login_token(HASH, days=30, now=1_000_000)
    assert login_token_valid(token, HASH, now=1_000_000 + 29 * 86400)
    assert not login_token_valid(token, HASH, now=1_000_000 + 31 * 86400)  # expired


@pytest.mark.parametrize("token", [None, "", "garbage", "123.abc", "x.y", "1.2.3"])
def test_login_token_rejects_junk(token):
    from core.auth import login_token_valid

    assert not login_token_valid(token, HASH, now=0)


def test_changing_the_password_signs_everyone_out():
    from core.auth import hash_password, login_token_valid, make_login_token

    token = make_login_token(HASH, now=0)
    assert not login_token_valid(token, hash_password("a new password"), now=1)


def test_tampered_expiry_is_rejected():
    from core.auth import login_token_valid, make_login_token

    expiry, signature = make_login_token(HASH, days=1, now=0).split(".")
    forged = f"{int(expiry) + 10 ** 9}.{signature}"
    assert not login_token_valid(forged, HASH, now=10)


def test_cookie_script():
    import ui

    script = ui.cookie_script("greenhouse_auth", "123.abc", 86400)
    assert "greenhouse_auth=123.abc; Path=/; SameSite=Strict; Max-Age=86400" in script
    assert "window.parent.document.cookie" in script
    assert "Max-Age" not in ui.cookie_script("greenhouse_auth", "x", None)  # until the browser closes


def test_login_sets_a_cookie_and_a_valid_cookie_skips_login(protected, monkeypatch):
    import ui
    from core.auth import login_token_valid

    written = []
    monkeypatch.setattr(ui, "write_cookie", lambda name, value, max_age: written.append((name, value, max_age)))
    at = protected.run()
    at.text_input[0].input("correct horse")
    at.button[0].click().run()
    ((name, token, max_age),) = written
    assert name == "greenhouse_auth" and max_age == 30 * 86400
    assert login_token_valid(token, HASH)

    # A reload is a new session: the cookie alone lets the visitor in.
    monkeypatch.setattr(ui, "request_cookie", lambda name: token)
    fresh = AppTest.from_file(str(SERVER_DIR / "app.py"), default_timeout=30).run()
    assert fresh.session_state["authenticated"] is True and not fresh.text_input


def test_session_only_cookie_without_keep_me_logged_in(protected, monkeypatch):
    import ui

    written = []
    monkeypatch.setattr(ui, "write_cookie", lambda name, value, max_age: written.append(max_age))
    at = protected.run()
    at.text_input[0].input("correct horse")
    at.checkbox[0].uncheck()
    at.button[0].click().run()
    assert written == [None]


def test_bad_cookie_still_asks_for_the_password(protected, monkeypatch):
    import ui

    monkeypatch.setattr(ui, "request_cookie", lambda name: "123.forged")
    at = protected.run()
    assert at.text_input[0].label == "Password"


def test_logout_deletes_the_cookie(protected, monkeypatch):
    import ui
    from core.auth import make_login_token

    written = []
    monkeypatch.setattr(ui, "request_cookie", lambda name: make_login_token(HASH))
    monkeypatch.setattr(ui, "write_cookie", lambda name, value, max_age: written.append((value, max_age)))
    at = protected.run()
    assert at.session_state["authenticated"] is True
    at.sidebar.button[0].click().run()
    assert at.text_input[0].label == "Password"  # the still-present cookie is ignored after logging out
    assert written[-1] == ("", 0)
