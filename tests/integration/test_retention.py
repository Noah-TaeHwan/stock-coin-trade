"""활동일 하루 1행, 7일 미인증 계정 삭제(새 가입 흐름만), 90일 지난 로그 삭제."""

import uuid

import pytest
from sqlalchemy import text

import bootstrap
import db
import member_delete
import retention
from app import create_app
from settings import Settings

pytestmark = pytest.mark.integration
PASSWORD = "long-enough-passphrase-for-tests"


@pytest.fixture(scope="module", autouse=True)
def tables():
    bootstrap.create_tables()


def _insert_member(conn, email, verified, consent, age_days):
    conn.execute(
        text(
            "INSERT INTO member (username, email, password, asset, email_verified_at, consent_version, created_at) "
            "VALUES ('정리', :e, 'x', 0, IF(:v, NOW(), NULL), :c, NOW() - INTERVAL :d DAY)"
        ),
        {"e": email, "v": verified, "c": consent, "d": age_days},
    )
    return conn.execute(text("SELECT member_id FROM member WHERE email = :e"), {"e": email}).scalar()


def test_only_stale_unverified_signups_are_removed():
    tag = uuid.uuid4().hex[:8]
    with db.engine.begin() as conn:
        stale = _insert_member(conn, f"stale-{tag}@example.test", False, "2026-09-26", 8)
        fresh = _insert_member(conn, f"fresh-{tag}@example.test", False, "2026-09-26", 1)
        legacy = _insert_member(conn, f"legacy-{tag}@example.test", False, None, 30)
        verified = _insert_member(conn, f"ok-{tag}@example.test", True, "2026-09-26", 30)
    assert retention.purge_unverified_members() >= 1
    with db.engine.connect() as conn:
        left = set(
            conn.execute(
                text("SELECT member_id FROM member WHERE member_id IN (:a, :b, :c, :d)"),
                {"a": stale, "b": fresh, "c": legacy, "d": verified},
            ).scalars()
        )
    for member_id in left:
        member_delete.delete_member(member_id)
    assert left == {fresh, legacy, verified}


def test_logs_older_than_90_days_are_removed():
    marker = f"retention-{uuid.uuid4().hex[:8]}"
    with db.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO system_error_log (source, message, occurred_at) VALUES "
                "('SERVER', :m, NOW() - INTERVAL 91 DAY), ('SERVER', :m, NOW() - INTERVAL 89 DAY)"
            ),
            {"m": marker},
        )
    retention.purge_old_logs()
    with db.engine.begin() as conn:
        left = conn.execute(text("SELECT COUNT(*) FROM system_error_log WHERE message = :m"), {"m": marker}).scalar()
        conn.execute(text("DELETE FROM system_error_log WHERE message = :m"), {"m": marker})
    assert left == 1


def test_a_logged_in_day_is_recorded_once_without_device_data():
    email = f"active-{uuid.uuid4().hex[:8]}@example.test"
    application = create_app(Settings(profile="local", secret_key="k" * 40, session_cookie_secure=False))
    application.config.update(TESTING=True)
    client = application.test_client()
    client.post(
        "/api/member/register", json={"username": "활동", "email": email, "password": PASSWORD, "password2": PASSWORD}
    )
    client.post("/api/member/login", json={"email": email, "password": PASSWORD})
    with db.engine.connect() as conn:
        member_id = conn.execute(text("SELECT member_id FROM member WHERE email = :e"), {"e": email}).scalar()
        rows = conn.execute(
            text("SELECT COUNT(*) FROM member_activity_day WHERE member_id = :m"), {"m": member_id}
        ).scalar()
        columns = set(
            conn.execute(
                text(
                    "SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() "
                    "AND TABLE_NAME = 'member_activity_day'"
                )
            ).scalars()
        )
    member_delete.delete_member(member_id)
    assert rows == 1 and columns == {"member_id", "day"}
