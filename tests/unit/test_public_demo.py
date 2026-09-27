"""공용 데모는 준비된 일반 회원만 노출하고 계정 인수 경로를 막는다."""

from contextlib import contextmanager
from datetime import datetime
from unittest import mock

import pytest

import accounts
import api_keys
import authz
import bootstrap
import kis_real
import member_account
import member_sessions
import members
import openapi
import passwords
from app import create_app
from models import ApiKey, Member
from settings import Settings


class FakeDb:
    def __init__(self, member=None):
        self.member = member

    def query(self, _model):
        return self

    def filter(self, *_criteria):
        return self

    def first(self):
        return self.member

    def add(self, member):
        self.member = member

    def get(self, _model, _id):
        return self.member


@contextmanager
def scope(db):
    yield db


def demo_member():
    return Member(
        member_id=7,
        username=accounts.PUBLIC_DEMO_USERNAME,
        email=accounts.PUBLIC_DEMO_EMAIL,
        password=passwords.hash_password(accounts.PUBLIC_DEMO_PASSWORD),
        is_demo=True,
        email_verified_at=datetime.now(),
    )


def test_create_demo_is_flagged_verified_and_idempotent(monkeypatch, app):
    db = FakeDb()
    monkeypatch.setattr(bootstrap, "session_scope", lambda: scope(db))
    with app.app_context():
        assert bootstrap.create_public_demo() == "created"
        assert db.member.is_demo is True
        assert db.member.email == accounts.PUBLIC_DEMO_EMAIL
        assert passwords.verify(accounts.PUBLIC_DEMO_PASSWORD, db.member.password)
        assert bootstrap.create_public_demo() == "unchanged"
    assert passwords.problem(accounts.PUBLIC_DEMO_PASSWORD) is not None  # 일반 가입 정책은 유지


def test_create_demo_refuses_existing_member_and_admin_identity(monkeypatch, app):
    existing = Member(
        username="기존 회원",
        email=accounts.PUBLIC_DEMO_EMAIL,
        password=passwords.hash_password("ordinary-long-password"),
        is_demo=False,
    )
    db = FakeDb(existing)
    monkeypatch.setattr(bootstrap, "session_scope", lambda: scope(db))
    with app.app_context():
        with pytest.raises(ValueError, match="이미 사용 중"):
            bootstrap.create_public_demo()
        assert db.member is existing
        app.config["ADMIN_EMAIL"] = accounts.PUBLIC_DEMO_EMAIL
        with pytest.raises(ValueError, match="관리자 주소"):
            bootstrap.create_public_demo()


def test_create_admin_cannot_reset_or_promote_demo(monkeypatch, app):
    db = FakeDb(demo_member())
    original_hash = db.member.password
    monkeypatch.setattr(bootstrap, "session_scope", lambda: scope(db))
    with app.app_context(), pytest.raises(ValueError, match="관리자로 전환"):
        bootstrap.create_admin(accounts.PUBLIC_DEMO_EMAIL, "another-valid-long-password")
    assert db.member.password == original_hash


def test_create_demo_cli_reports_only_outcome(app):
    with mock.patch.object(bootstrap, "create_public_demo", return_value="created") as create:
        result = app.test_cli_runner().invoke(args=["create-demo"])
    assert result.exit_code == 0
    assert result.output.strip() == "create-demo: created"
    create.assert_called_once_with()


def test_me_advertises_only_ready_non_admin_demo(monkeypatch, client, app):
    db = FakeDb(demo_member())
    monkeypatch.setattr(members, "session_scope", lambda: scope(db))
    assert client.get("/api/member/me?demo=1").get_json()["demoReady"] is True
    db.member.is_demo = False
    assert client.get("/api/member/me?demo=1").get_json()["demoReady"] is False
    db.member.is_demo = True
    db.member.email_verified_at = None
    assert client.get("/api/member/me?demo=1").get_json()["demoReady"] is False
    db.member.email_verified_at = datetime.now()
    app.config["ADMIN_EMAIL"] = accounts.PUBLIC_DEMO_EMAIL
    assert client.get("/api/member/me?demo=1").get_json()["demoReady"] is False


def test_short_demo_password_logs_in_without_weakening_signup(monkeypatch, client):
    db = FakeDb(demo_member())
    monkeypatch.setattr(members, "session_scope", lambda: scope(db))
    with mock.patch.object(member_sessions, "start") as start:
        response = client.post(
            "/api/member/login",
            json={
                "email": accounts.PUBLIC_DEMO_EMAIL,
                "password": accounts.PUBLIC_DEMO_PASSWORD,
            },
        )
    assert response.status_code == 200
    start.assert_called_once_with(7)
    assert passwords.problem(accounts.PUBLIC_DEMO_PASSWORD) is not None


def test_demo_address_cannot_be_claimed_through_signup_or_trigger_existing_mail(monkeypatch, client):
    body = {
        "username": "누군가",
        "email": accounts.PUBLIC_DEMO_EMAIL,
        "password": "ordinary-long-password",
        "password2": "ordinary-long-password",
        "agreeAge": True,
        "agreePrivacy": True,
    }
    with mock.patch.object(members, "session_scope") as db:
        assert client.post("/api/member/register", json=body).status_code == 400
    db.assert_not_called()

    public = create_app(
        Settings(
            profile="public",
            secret_key="p" * 40,
            session_cookie_secure=True,
            admin_email="owner@example.com",
            signup_enabled=True,
        )
    )
    public.config["TESTING"] = True
    with mock.patch.object(members, "session_scope") as db, mock.patch.object(members.mailer, "queue") as queue:
        response = public.test_client().post("/api/member/register", json=body)
    assert response.status_code == 202
    assert response.get_json() == {"status": "check_email"}
    db.assert_not_called()
    queue.assert_not_called()


def test_demo_cannot_become_admin_or_use_shared_broker_account(app):
    db = FakeDb(demo_member())
    with app.app_context():
        app.config["ADMIN_EMAIL"] = accounts.PUBLIC_DEMO_EMAIL
        assert authz.member_email(7, db) == accounts.PUBLIC_DEMO_EMAIL
        assert authz.is_demo_member(7, db) is True
        assert authz.is_admin_member(7, db) is False
        assert authz.can_use_kis_account(7, db) is False
        db.member.is_demo = False
        assert authz.is_admin_member(7, db) is True
        assert authz.can_use_kis_account(7, db) is True


def test_demo_account_and_api_key_routes_reject_takeover(monkeypatch, client, app):
    app.before_request_funcs[None].remove(member_sessions.validate)  # 단위 검사는 저장소 세션 대신 쿠키를 주입
    with client.session_transaction() as session:
        session["member_id"] = 7
    for module in (members, member_account, api_keys):
        monkeypatch.setattr(module, "is_demo_member", lambda _id: True)
    monkeypatch.setattr(kis_real, "is_demo_member", lambda _id: True)
    for path, body in (
        ("/api/member/password/change", {}),
        ("/api/member/delete", {}),
        ("/api/member/logout-all", {}),
        ("/api/member/api-keys", {}),
    ):
        assert client.post(path, json=body).status_code == 403
    assert client.get("/api/member/api-keys").status_code == 403
    assert client.delete("/api/member/api-keys/1").status_code == 403
    assert client.get("/api/kis-real/status").get_json()["error"] == "DEMO_ACCOUNT"
    assert client.post("/api/kis-real/balance", json={}).get_json()["error"] == "DEMO_ACCOUNT"
    assert client.post("/api/member/logout", json={}).status_code == 200


def test_demo_api_key_cannot_call_openapi(monkeypatch, client):
    key = ApiKey(api_key_id=1, member_id=7, is_active=True)
    member = demo_member()

    class OpenApiDb(FakeDb):
        def first(self):
            return key

        def get(self, _model, _id):
            return member

    monkeypatch.setattr(openapi, "session_scope", lambda: scope(OpenApiDb()))
    response = client.get("/openapi/v1/account", headers={"Authorization": "Bearer old-demo-key"})
    assert response.status_code == 401


def test_reset_request_for_demo_is_generic_without_mail(monkeypatch, client):
    class Connection:
        def execute(self, *_args, **_kwargs):
            return self

        def mappings(self):
            return self

        def first(self):
            return {
                "member_id": 7,
                "email": accounts.PUBLIC_DEMO_EMAIL,
                "email_verified_at": datetime.now(),
                "is_demo": True,
            }

    class Engine:
        def connect(self):
            return scope(Connection())

    monkeypatch.setattr(member_account, "engine", Engine())
    with mock.patch.object(member_account.mailer, "queue") as queue:
        response = client.post("/api/member/password/reset-request", json={"email": accounts.PUBLIC_DEMO_EMAIL})
    assert response.status_code == 202
    assert response.get_json() == {"status": "accepted"}
    queue.assert_not_called()


def test_preexisting_normal_member_at_demo_address_keeps_reset_path(monkeypatch, client):
    class Connection:
        def execute(self, *_args, **_kwargs):
            return self

        def mappings(self):
            return self

        def first(self):
            return {
                "member_id": 8,
                "email": accounts.PUBLIC_DEMO_EMAIL,
                "email_verified_at": datetime.now(),
                "is_demo": False,
            }

    class Engine:
        def connect(self):
            return scope(Connection())

    monkeypatch.setattr(member_account, "engine", Engine())
    with mock.patch.object(member_account.mailer, "queue") as queue:
        response = client.post("/api/member/password/reset-request", json={"email": accounts.PUBLIC_DEMO_EMAIL})
    assert response.status_code == 202
    queue.assert_called_once()


def test_old_reset_token_cannot_change_demo_password(monkeypatch, client):
    class Connection:
        rolled_back = False

        def execute(self, *_args, **_kwargs):
            return self

        def mappings(self):
            return self

        def first(self):
            return {"email": accounts.PUBLIC_DEMO_EMAIL, "username": accounts.PUBLIC_DEMO_USERNAME, "is_demo": True}

        def rollback(self):
            self.rolled_back = True

    conn = Connection()

    class Engine:
        def connect(self):
            return scope(conn)

    monkeypatch.setattr(member_account, "engine", Engine())
    monkeypatch.setattr(member_account.member_tokens, "consume", lambda *_args: 7)
    response = client.post(
        "/api/member/password/reset",
        json={
            "token": "old-token",
            "password": "a-new-long-demo-password",
            "password2": "a-new-long-demo-password",
        },
    )
    assert response.status_code == 403
    assert conn.rolled_back is True
