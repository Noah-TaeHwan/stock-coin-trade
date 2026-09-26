"""서버 세션이 로그아웃·모든 기기 로그아웃·만료·조작 쿠키를 서버에서 끊는다."""

import uuid

import pytest
from sqlalchemy import text

import bootstrap
import db
import member_sessions
from app import create_app
from settings import Settings

pytestmark = pytest.mark.integration
PASSWORD = "long-enough-passphrase-for-tests"


@pytest.fixture(scope="module", autouse=True)
def tables():
    bootstrap.create_tables()


def _client():
    application = create_app(Settings(profile="local", secret_key="k" * 40, session_cookie_secure=False))
    application.config.update(TESTING=True)
    return application.test_client()


@pytest.fixture
def email():
    address = f"sess-{uuid.uuid4().hex[:10]}@example.test"
    signup = _client().post(
        "/api/member/register",
        json={"username": "세션", "email": address, "password": PASSWORD, "password2": PASSWORD},
    )
    assert signup.status_code == 200
    yield address
    with db.engine.begin() as conn:
        member_id = conn.execute(text("SELECT member_id FROM member WHERE email = :e"), {"e": address}).scalar()
        for table in ("member_session", "member"):
            conn.execute(text(f"DELETE FROM {table} WHERE member_id = :id"), {"id": member_id})


def _login(address):
    client = _client()
    assert client.post("/api/member/login", json={"email": address, "password": PASSWORD}).status_code == 200
    return client


def test_signup_starts_a_session_after_the_member_row_is_committed():
    address = f"sess-{uuid.uuid4().hex[:10]}@example.test"
    client = _client()
    signup = client.post(
        "/api/member/register",
        json={"username": "세션", "email": address, "password": PASSWORD, "password2": PASSWORD},
    )
    try:
        assert signup.status_code == 200
        assert client.get("/api/member/me").get_json()["loggedIn"] is True
    finally:
        with db.engine.begin() as conn:
            member_id = conn.execute(text("SELECT member_id FROM member WHERE email = :e"), {"e": address}).scalar()
            for table in ("member_session", "member"):
                conn.execute(text(f"DELETE FROM {table} WHERE member_id = :id"), {"id": member_id})


def test_the_server_keeps_only_a_hash_of_the_session_token(email):
    client = _login(email)
    with client.session_transaction() as s:
        raw = s["sid"]
    with db.engine.connect() as conn:
        hashed = conn.execute(
            text("SELECT COUNT(*) FROM member_session WHERE token_hash = :h"), {"h": member_sessions.token_hash(raw)}
        ).scalar()
        plain = conn.execute(text("SELECT COUNT(*) FROM member_session WHERE token_hash = :t"), {"t": raw}).scalar()
    assert (hashed, plain) == (1, 0)


def test_a_copied_cookie_stops_working_after_logout(email):
    client = _login(email)
    copied = client.get_cookie("session").value
    assert client.post("/api/member/logout").status_code == 200
    thief = _client()
    thief.set_cookie("session", copied)
    assert thief.get("/api/member/me").get_json()["loggedIn"] is False


def test_logout_all_ends_every_device(email):
    phone, laptop = _login(email), _login(email)
    assert laptop.post("/api/member/logout-all").status_code == 200
    assert phone.get("/api/member/me").get_json()["loggedIn"] is False
    assert laptop.get("/api/member/me").get_json()["loggedIn"] is False


def test_a_cookie_pointing_at_another_member_is_rejected(email):
    client = _login(email)
    with client.session_transaction() as s:
        s["member_id"] = s["member_id"] + 1
    assert client.get("/api/member/me").get_json()["loggedIn"] is False


def test_idle_sessions_expire_and_their_rows_are_removed(email):
    client = _login(email)
    with client.session_transaction() as s:
        digest = member_sessions.token_hash(s["sid"])
    with db.engine.begin() as conn:
        conn.execute(
            text("UPDATE member_session SET last_seen_at = last_seen_at - INTERVAL 8 DAY WHERE token_hash = :h"),
            {"h": digest},
        )
    assert client.get("/api/member/me").get_json()["loggedIn"] is False
    with db.engine.connect() as conn:
        left = conn.execute(text("SELECT COUNT(*) FROM member_session WHERE token_hash = :h"), {"h": digest}).scalar()
    assert left == 0


def test_purge_removes_expired_rows_and_keeps_live_ones(email):
    live = _login(email)
    old = _login(email)
    with old.session_transaction() as s:
        old_digest = member_sessions.token_hash(s["sid"])
    with db.engine.begin() as conn:
        conn.execute(
            text("UPDATE member_session SET created_at = created_at - INTERVAL 31 DAY WHERE token_hash = :h"),
            {"h": old_digest},
        )
    assert member_sessions.purge_expired() >= 1
    assert live.get("/api/member/me").get_json()["loggedIn"] is True
