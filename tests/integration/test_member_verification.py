"""메일 인증 모드: 열거 없는 가입, 인증 전 로그인 거부, 1회용 토큰, 재전송."""

import threading
import uuid

import pytest
from sqlalchemy import text

import bootstrap
import db
import mailer
import member_tokens
import passwords
from app import create_app
from settings import Settings

pytestmark = pytest.mark.integration
PASSWORD = "long-enough-passphrase-for-tests"
MAIL_SETTINGS = dict(
    profile="local",
    secret_key="k" * 40,
    session_cookie_secure=False,
    smtp_host="mailpit",
    smtp_port=1025,
    smtp_starttls=False,
    smtp_from="no-reply@stockdesk.local",
    public_base_url="http://127.0.0.1:3334",
)


@pytest.fixture(scope="module", autouse=True)
def tables():
    bootstrap.create_tables()


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "queue", lambda kind, to, token=None: sent.append((kind, to, token)))
    return sent


def _client(**overrides):
    application = create_app(Settings(**{**MAIL_SETTINGS, **overrides}))
    application.config.update(TESTING=True)
    return application.test_client()


def _signup(client, email, **extra):
    return client.post(
        "/api/member/register",
        json={
            "username": "인증",
            "email": email,
            "password": PASSWORD,
            "password2": PASSWORD,
            "agreeAge": True,
            "agreePrivacy": True,
            **extra,
        },
    )


def _cleanup(email):
    with db.engine.begin() as conn:
        member_id = conn.execute(text("SELECT member_id FROM member WHERE email = :e"), {"e": email}).scalar()
        if member_id:
            for table in ("member_token", "member_session", "api_key", "system_error_log", "member"):
                conn.execute(text(f"DELETE FROM {table} WHERE member_id = :id"), {"id": member_id})


@pytest.fixture
def email():
    address = f"verify-{uuid.uuid4().hex[:10]}@example.test"
    yield address
    _cleanup(address)


def test_signup_needs_both_consents(email, outbox):
    response = _signup(_client(), email, agreePrivacy=False)
    assert response.status_code == 400 and response.get_json()["field"] == "consent"


def test_every_signup_path_answers_the_same_and_hashes_once(email, outbox, monkeypatch):
    calls = []
    real = passwords.hash_password
    monkeypatch.setattr(passwords, "hash_password", lambda pw: calls.append(1) or real(pw))
    client = _client()
    fresh = _signup(client, email)
    again = _signup(client, email)
    reserved = _signup(client, f"x-{uuid.uuid4().hex[:6]}@system-bot.local")
    trap = _signup(client, f"trap-{uuid.uuid4().hex[:6]}@example.test", website="http://spam.test")
    answers = {(r.status_code, r.get_data(as_text=True)) for r in (fresh, again, reserved, trap)}
    assert answers == {(202, fresh.get_data(as_text=True))} and fresh.get_json() == {"status": "check_email"}
    assert len(calls) == 4
    assert [kind for kind, _, _ in outbox] == ["verify", "exists"] and {to for _, to, _ in outbox} == {email}


def test_login_is_refused_until_the_email_is_verified(email, outbox):
    client = _client()
    _signup(client, email)
    refused = client.post("/api/member/login", json={"email": email, "password": PASSWORD})
    wrong = client.post("/api/member/login", json={"email": email, "password": PASSWORD + "x"})
    assert refused.status_code == wrong.status_code == 401 and refused.get_json() == wrong.get_json()
    assert client.post("/api/member/verify", json={"token": outbox[0][2]}).status_code == 200
    assert client.post("/api/member/login", json={"email": email, "password": PASSWORD}).status_code == 200


def test_a_token_can_be_used_once_even_concurrently(email, outbox):
    _signup(_client(), email)
    token = outbox[0][2]
    results = []

    def use():
        with db.engine.connect() as conn:
            results.append(member_tokens.consume(conn, token, "verify"))
            conn.commit()

    threads = [threading.Thread(target=use) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(result is not None for result in results) == 1
    assert _client().post("/api/member/verify", json={"token": token}).status_code == 400


def test_a_new_token_replaces_the_old_one_and_only_hashes_are_stored(email, outbox):
    client = _client()
    _signup(client, email)
    first = outbox[0][2]
    assert client.post("/api/member/verify/resend", json={"email": email}).status_code == 202
    second = outbox[1][2]
    with db.engine.connect() as conn:
        stored = (
            conn.execute(
                text("SELECT token_hash FROM member_token t JOIN member m USING (member_id) WHERE m.email = :e"),
                {"e": email},
            )
            .scalars()
            .all()
        )
    assert stored == [member_tokens.token_hash(second)]
    assert client.post("/api/member/verify", json={"token": first}).status_code == 400
    assert client.post("/api/member/verify", json={"token": second}).status_code == 200


def test_resend_answers_the_same_for_unknown_addresses(outbox):
    response = _client().post(
        "/api/member/verify/resend", json={"email": f"nobody-{uuid.uuid4().hex[:6]}@example.test"}
    )
    assert response.status_code == 202 and outbox == []


def test_expired_verification_tokens_are_refused(email, outbox):
    _signup(_client(), email)
    token = outbox[0][2]
    with db.engine.begin() as conn:
        conn.execute(
            text("UPDATE member_token SET expires_at = expires_at - INTERVAL 25 HOUR WHERE token_hash = :h"),
            {"h": member_tokens.token_hash(token)},
        )
    assert _client().post("/api/member/verify", json={"token": token}).status_code == 400


NEW_PASSWORD = "another long passphrase here"


def _verified_client(email, outbox):
    client = _client()
    _signup(client, email)
    client.post("/api/member/verify", json={"token": outbox[-1][2]})
    assert client.post("/api/member/login", json={"email": email, "password": PASSWORD}).status_code == 200
    return client


def test_reset_ends_sessions_disables_api_keys_and_does_not_log_in(email, outbox):
    phone = _verified_client(email, outbox)
    assert phone.post("/api/member/api-keys", json={"label": "k1"}).status_code == 200
    assert _client().post("/api/member/password/reset-request", json={"email": email}).status_code == 202
    kind, to, token = outbox[-1]
    assert (kind, to) == ("reset", email)
    browser = _client()
    done = browser.post(
        "/api/member/password/reset", json={"token": token, "password": NEW_PASSWORD, "password2": NEW_PASSWORD}
    )
    assert done.status_code == 200
    assert browser.get("/api/member/me").get_json()["loggedIn"] is False
    assert phone.get("/api/member/me").get_json()["loggedIn"] is False
    with db.engine.connect() as conn:
        active = conn.execute(
            text(
                "SELECT COUNT(*) FROM api_key k JOIN member m USING (member_id) WHERE m.email = :e AND k.is_active = 1"
            ),
            {"e": email},
        ).scalar()
    assert active == 0
    assert _client().post("/api/member/login", json={"email": email, "password": PASSWORD}).status_code == 401
    assert _client().post("/api/member/login", json={"email": email, "password": NEW_PASSWORD}).status_code == 200


def test_weak_password_does_not_burn_the_reset_token(email, outbox):
    _verified_client(email, outbox)
    _client().post("/api/member/password/reset-request", json={"email": email})
    token = outbox[-1][2]
    weak = _client().post(
        "/api/member/password/reset", json={"token": token, "password": "short", "password2": "short"}
    )
    assert weak.status_code == 400 and weak.get_json()["field"] == "password"
    ok = _client().post(
        "/api/member/password/reset", json={"token": token, "password": NEW_PASSWORD, "password2": NEW_PASSWORD}
    )
    assert ok.status_code == 200


def test_reset_request_answers_the_same_for_unknown_addresses(outbox):
    response = _client().post(
        "/api/member/password/reset-request", json={"email": f"nobody-{uuid.uuid4().hex[:6]}@example.test"}
    )
    assert response.status_code == 202 and outbox == []


def test_reset_also_verifies_the_email(email, outbox):
    client = _client()
    _signup(client, email)
    client.post("/api/member/password/reset-request", json={"email": email})
    token = outbox[-1][2]
    client.post(
        "/api/member/password/reset", json={"token": token, "password": NEW_PASSWORD, "password2": NEW_PASSWORD}
    )
    assert client.post("/api/member/login", json={"email": email, "password": NEW_PASSWORD}).status_code == 200


def test_change_keeps_this_session_and_ends_the_others(email, outbox):
    laptop = _verified_client(email, outbox)
    phone = _client()
    phone.post("/api/member/login", json={"email": email, "password": PASSWORD})
    wrong = laptop.post(
        "/api/member/password/change",
        json={"current": "nope-nope-nope", "password": NEW_PASSWORD, "password2": NEW_PASSWORD},
    )
    assert wrong.status_code == 400 and wrong.get_json()["field"] == "current"
    ok = laptop.post(
        "/api/member/password/change", json={"current": PASSWORD, "password": NEW_PASSWORD, "password2": NEW_PASSWORD}
    )
    assert ok.status_code == 200
    assert laptop.get("/api/member/me").get_json()["loggedIn"] is True
    assert phone.get("/api/member/me").get_json()["loggedIn"] is False
