"""Account rules that need MariaDB: unique email, system accounts, API key cap, admin."""

import uuid

import bcrypt
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

import bootstrap
import db
import members
from accounts import UNUSABLE_PASSWORD
from app import create_app
from demo_seed import DEMO_PASSWORD, _demo_email, seed_demo_investors
from market_bots import _bot_email, ensure_bot_accounts
from settings import Settings

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", autouse=True)
def tables():
    bootstrap.create_tables()


def _client(profile):
    settings = Settings(
        profile=profile, secret_key="k" * 40, session_cookie_secure=False, admin_email="owner@example.com"
    )
    application = create_app(settings)
    application.config.update(TESTING=True)
    return application.test_client()


def _delete_member(email):
    with db.engine.begin() as conn:
        member_id = conn.execute(text("SELECT member_id FROM member WHERE email = :e"), {"e": email}).scalar()
        if member_id is None:
            return
        for table in ("api_key", "system_error_log", "member_session", "member"):
            conn.execute(text(f"DELETE FROM {table} WHERE member_id = :id"), {"id": member_id})


def test_member_email_has_a_unique_index():
    with db.engine.connect() as conn:
        unique = conn.execute(
            text(
                "SELECT NON_UNIQUE FROM information_schema.statistics "
                "WHERE table_schema = DATABASE() AND table_name = 'member' AND index_name = :name"
            ),
            {"name": members.MEMBER_EMAIL_INDEX},
        ).scalar()
    assert unique == 0


def test_the_index_rejects_the_same_email_in_another_case():
    email = f"dup-{uuid.uuid4().hex[:10]}@example.test"
    insert = text("INSERT INTO member (username, email, password, asset) VALUES ('d', :e, 'x', 0)")
    try:
        with db.engine.begin() as conn:
            conn.execute(insert, {"e": email})
        with pytest.raises(IntegrityError), db.engine.begin() as conn:
            conn.execute(insert, {"e": email.upper()})
    finally:
        _delete_member(email)


def test_ensure_unique_member_email_is_idempotent():
    members.ensure_unique_member_email()
    members.ensure_unique_member_email()


def test_bots_created_with_the_old_known_password_cannot_sign_in():
    email = _bot_email(1)
    ensure_bot_accounts()
    old_hash = bcrypt.hashpw(b"system-bot-account", bcrypt.gensalt()).decode()
    with db.engine.begin() as conn:
        conn.execute(text("UPDATE member SET password = :p WHERE email = :e"), {"p": old_hash, "e": email})

    ensure_bot_accounts()

    with db.engine.connect() as conn:
        stored = conn.execute(text("SELECT password FROM member WHERE email = :e"), {"e": email}).scalar()
    assert stored == UNUSABLE_PASSWORD
    response = _client("local").post("/api/member/login", json={"email": email, "password": "system-bot-account"})
    assert response.status_code == 401


def test_sample_investors_sign_in_locally_but_not_in_public(monkeypatch):
    monkeypatch.setenv("DEMO_SEED_ENABLED", "true")
    seed_demo_investors()
    body = {"email": _demo_email(1), "password": DEMO_PASSWORD}
    assert _client("local").post("/api/member/login", json=body).status_code == 200
    assert _client("public").post("/api/member/login", json=body).status_code == 401


def test_api_keys_are_capped_per_member():
    email = f"keys-{uuid.uuid4().hex[:10]}@example.test"
    client = _client("local")
    try:
        client.post(
            "/api/member/register",
            json={
                "username": "k",
                "email": email,
                "password": "pw-long-passphrase-for-tests",
                "password2": "pw-long-passphrase-for-tests",
            },
        )
        codes = [client.post("/api/member/api-keys", json={"label": f"k{i}"}).status_code for i in range(6)]
        assert codes == [200] * 5 + [400]
        keys = client.get("/api/member/api-keys").get_json()["keys"]
        client.delete(f"/api/member/api-keys/{keys[0]['id']}")
        assert client.post("/api/member/api-keys", json={"label": "after-revoke"}).status_code == 200
    finally:
        _delete_member(email)


def test_create_admin_makes_an_account_that_can_sign_in_and_is_admin():
    email = f"owner-{uuid.uuid4().hex[:10]}@example.test"
    password = "correct-horse-battery"
    try:
        assert bootstrap.create_admin(email, password) == "created"
        assert bootstrap.create_admin(email, password + "!") == "updated"
        settings = Settings(profile="public", secret_key="k" * 40, session_cookie_secure=False, admin_email=email)
        application = create_app(settings)
        client = application.test_client()
        assert client.post("/api/member/login", json={"email": email, "password": password}).status_code == 401
        assert client.post("/api/member/login", json={"email": email, "password": password + "!"}).status_code == 200
        assert client.get("/api/member/me").get_json()["isAdmin"] is True
        assert client.get("/api/admin/me").status_code == 200
    finally:
        _delete_member(email)
