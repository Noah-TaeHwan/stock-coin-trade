"""서버 세션 확인 훅: 옛 쿠키, 저장소 장애, 토큰 해시."""

from sqlalchemy.exc import SQLAlchemyError

import member_sessions


def test_old_cookie_without_a_server_session_is_dropped(client):
    with client.session_transaction() as s:
        s["member_id"] = 7
    assert client.get("/api/member/me").get_json()["loggedIn"] is False


def test_session_store_failure_logs_the_visitor_out(client, monkeypatch):
    class Broken:
        def begin(self):
            raise SQLAlchemyError("session store down")

    monkeypatch.setattr(member_sessions, "engine", Broken())
    with client.session_transaction() as s:
        s["member_id"], s["sid"] = 7, "token"
    assert client.get("/api/member/me").get_json()["loggedIn"] is False


def test_only_a_hash_of_the_token_is_kept():
    digest = member_sessions.token_hash("abc")
    assert digest != "abc" and len(digest) == 64
