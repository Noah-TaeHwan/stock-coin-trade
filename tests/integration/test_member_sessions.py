"""서버 세션이 로그아웃·모든 기기 로그아웃·만료·조작 쿠키를 서버에서 끊는다."""

import uuid

import pytest
from sqlalchemy import text

import bootstrap
import db
import member_delete
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
        member_delete.delete_member(member_id)


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
            member_delete.delete_member(member_id)


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


def test_short_passwords_are_refused_at_signup():
    response = _client().post(
        "/api/member/register",
        json={
            "username": "짧음",
            "email": f"short-{uuid.uuid4().hex[:8]}@example.test",
            "password": "fourteen-chars",
            "password2": "fourteen-chars",
        },
    )
    assert response.status_code == 400 and response.get_json()["field"] == "password"


def test_new_signups_are_stored_in_the_untruncated_format(email):
    with db.engine.connect() as conn:
        stored = conn.execute(text("SELECT password FROM member WHERE email = :e"), {"e": email}).scalar()
    assert stored.startswith("s2$")


def test_legacy_hashes_are_upgraded_on_login(email):
    import bcrypt

    with db.engine.begin() as conn:
        conn.execute(
            text("UPDATE member SET password = :p WHERE email = :e"),
            {"p": bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt()).decode(), "e": email},
        )
    _login(email)
    with db.engine.connect() as conn:
        stored = conn.execute(text("SELECT password FROM member WHERE email = :e"), {"e": email}).scalar()
    assert stored.startswith("s2$")
    _login(email)


def test_email_limit_counts_only_failures(email):
    application = create_app(
        Settings(profile="local", secret_key="k" * 40, session_cookie_secure=False, ratelimit_enabled=True)
    )
    application.config.update(TESTING=True)
    client = application.test_client()

    def attempt(password, i):
        # 요청마다 IP를 바꿔 IP 제한(분당 10회)보다 이메일 제한이 먼저 드러나게 한다.
        return client.post(
            "/api/member/login",
            json={"email": email, "password": password},
            environ_base={"REMOTE_ADDR": f"198.51.100.{i}"},
        ).status_code

    assert [attempt(PASSWORD, i) for i in range(3)] == [200] * 3
    statuses = [attempt("wrong-password-xyz", 10 + i) for i in range(31)]
    assert statuses[:30] == [401] * 30 and statuses[30] == 429


def test_accent_and_case_variants_share_one_email_limit(email):
    # 회원 이메일 열은 악센트·대소문자를 구별하지 않는다(jose = JOSÉ). 변형 주소로 한도를 늘리지 못해야 한다.
    local, domain = email.split("@")
    variants = [email, local.replace("e", "é").upper() + "@" + domain, local.upper() + "@" + domain.upper()]
    application = create_app(
        Settings(profile="local", secret_key="k" * 40, session_cookie_secure=False, ratelimit_enabled=True)
    )
    application.config.update(TESTING=True)
    client = application.test_client()
    statuses = [
        client.post(
            "/api/member/login",
            json={"email": variants[i % 3], "password": "wrong-password-xyz"},
            environ_base={"REMOTE_ADDR": f"198.51.100.{i + 1}"},
        ).status_code
        for i in range(31)
    ]
    assert statuses[:30] == [401] * 30 and statuses[30] == 429
