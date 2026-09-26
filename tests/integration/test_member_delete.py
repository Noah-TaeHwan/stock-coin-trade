"""탈퇴: 한 트랜잭션 삭제, member_id를 가진 모든 표 0행(information_schema 스캔), AI 비용 합계 보존."""

import uuid

import pytest
from sqlalchemy import text

import bootstrap
import db
import member_delete
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


def _member_tables(conn):
    return (
        conn.execute(
            text(
                "SELECT TABLE_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() "
                "AND COLUMN_NAME = 'member_id' AND TABLE_NAME <> 'member'"
            )
        )
        .scalars()
        .all()
    )


def test_deleting_an_account_leaves_no_row_with_its_id_anywhere():
    email = f"bye-{uuid.uuid4().hex[:10]}@example.test"
    client = _client()
    assert (
        client.post(
            "/api/member/register",
            json={"username": "탈퇴", "email": email, "password": PASSWORD, "password2": PASSWORD},
        ).status_code
        == 200
    )
    assert client.post("/api/member/api-keys", json={"label": "k"}).status_code == 200
    with db.engine.begin() as conn:
        member_id = conn.execute(text("SELECT member_id FROM member WHERE email = :e"), {"e": email}).scalar()
        conn.execute(
            text("INSERT INTO hts_watch_memo (member_id, symbol, memo) VALUES (:m, '005930', 'memo')"), {"m": member_id}
        )
        conn.execute(
            text("INSERT INTO system_error_log (source, message, member_id) VALUES ('SERVER', 'x', :m)"),
            {"m": member_id},
        )
        invite = conn.execute(
            text(
                "INSERT INTO ai_invite (code_hash, label, member_id, expires_at, max_requests, max_tokens) "
                "VALUES (:h, 'bye', :m, NOW() + INTERVAL 1 DAY, 1, 1) RETURNING invite_id"
            ),
            {"h": uuid.uuid4().hex * 2, "m": member_id},
        ).scalar()
        conn.execute(
            text(
                "INSERT INTO ai_usage (member_id, invite_id, model, status, cost_usd, question_chars) "
                "VALUES (:m, :i, 'claude-opus-5-5', 'ok', 1.25, 10)"
            ),
            {"m": member_id, "i": invite},
        )
    assert client.post("/api/member/delete", json={"password": "not-the-password"}).status_code == 400
    assert client.post("/api/member/delete", json={"password": PASSWORD}).status_code == 200
    assert client.get("/api/member/me").get_json()["loggedIn"] is False
    with db.engine.connect() as conn:
        leftovers = {
            table: conn.execute(text(f"SELECT COUNT(*) FROM {table} WHERE member_id = :m"), {"m": member_id}).scalar()
            for table in _member_tables(conn)
        }
        gone = conn.execute(text("SELECT COUNT(*) FROM member WHERE member_id = :m"), {"m": member_id}).scalar()
        kept = conn.execute(text("SELECT SUM(cost_usd) FROM ai_usage WHERE invite_id = :i"), {"i": invite}).scalar()
        revoked, label = conn.execute(
            text("SELECT revoked_at IS NOT NULL, label FROM ai_invite WHERE invite_id = :i"), {"i": invite}
        ).one()
        conn.execute(text("DELETE FROM ai_usage WHERE invite_id = :i"), {"i": invite})
        conn.execute(text("DELETE FROM ai_invite WHERE invite_id = :i"), {"i": invite})
        conn.commit()
    assert leftovers == {table: 0 for table in leftovers} and gone == 0
    # 초대 코드 이름표(관리자가 적은 받는 사람 이름)도 지워 비용 행이 누구의 것인지 알 수 없게 한다.
    assert float(kept) == 1.25 and revoked == 1 and label == member_delete.DELETED_LABEL


def test_every_member_id_table_is_handled_by_the_delete_path():
    with db.engine.connect() as conn:
        found = set(_member_tables(conn))
    handled = set(member_delete.DELETE_TABLES) | set(member_delete.NULLIFY_TABLES) | {"ai_invite"}
    assert found - handled == set(), f"탈퇴 경로에 없는 member_id 표: {sorted(found - handled)}"
