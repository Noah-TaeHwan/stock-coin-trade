"""서버 세션: 서명 쿠키의 (member_id, sid)를 MariaDB 표로 검증한다(설계: S1 스펙 ②).

로그아웃하면 행을 지워 복사된 쿠키도 즉시 무효가 된다. DB에는 토큰의 SHA-256만 둔다.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from flask import session
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from db import engine

# 마지막 사용 뒤 7일, 발급 뒤 30일이 지나면 만료. last_seen_at은 1시간에 한 번만 갱신한다(쓰기 줄이기).
IDLE = timedelta(days=7)
ABSOLUTE = timedelta(days=30)
TOUCH = timedelta(hours=1)

SESSION_TABLE = """CREATE TABLE IF NOT EXISTS member_session (
  token_hash CHAR(64) NOT NULL,
  member_id BIGINT(20) NOT NULL,
  created_at DATETIME NOT NULL COMMENT 'UTC',
  last_seen_at DATETIME NOT NULL COMMENT 'UTC',
  PRIMARY KEY (token_hash),
  KEY idx_member_session_member (member_id),
  CONSTRAINT fk_member_session_member FOREIGN KEY (member_id) REFERENCES member (member_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci"""

# 로그인한 회원이 활동한 날(KST)만 하루 1행. IP·기기·페이지는 남기지 않는다(스펙 ④ 측정).
ACTIVITY_TABLE = """CREATE TABLE IF NOT EXISTS member_activity_day (
  member_id BIGINT(20) NOT NULL,
  day DATE NOT NULL,
  PRIMARY KEY (member_id, day),
  CONSTRAINT fk_member_activity_member FOREIGN KEY (member_id) REFERENCES member (member_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci"""


def token_hash(token: str) -> str:
    """세션 토큰의 SHA-256 16진수.

    @param token 쿠키에 담긴 원본 토큰
    @returns 64자 해시
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    """DB에 쓰는 UTC 시각(시간대 정보 없음).

    @returns 현재 UTC 시각
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def ensure_session_table() -> None:
    """세션·활동일 표를 만든다(멱등)."""
    with engine.begin() as conn:
        conn.execute(text(SESSION_TABLE))
        conn.execute(text(ACTIVITY_TABLE))


def start(member_id: int) -> None:
    """세션 고정을 막고 새 서버 세션을 발급한다. 회원 행이 커밋된 뒤에 부른다.

    @param member_id 로그인한 회원 ID
    """
    session.clear()
    token, now = secrets.token_urlsafe(32), _now()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO member_session (token_hash, member_id, created_at, last_seen_at) "
                "VALUES (:h, :m, :now, :now)"
            ),
            {"h": token_hash(token), "m": member_id, "now": now},
        )
    session["member_id"], session["sid"], session.permanent = member_id, token, True


def validate() -> None:
    """요청마다 쿠키의 세션이 서버에 살아 있는지 본다. 아니면 쿠키 세션을 비운다(fail closed)."""
    member_id, token = session.get("member_id"), session.get("sid")
    if member_id is None:
        return
    if not token:
        session.clear()
        return
    digest, now = token_hash(token), _now()
    try:
        with engine.begin() as conn:
            row = (
                conn.execute(
                    text("SELECT member_id, created_at, last_seen_at FROM member_session WHERE token_hash = :h"),
                    {"h": digest},
                )
                .mappings()
                .first()
            )
            expired = row is None or now - row["last_seen_at"] > IDLE or now - row["created_at"] > ABSOLUTE
            if expired or row["member_id"] != member_id:
                if row is not None:
                    conn.execute(text("DELETE FROM member_session WHERE token_hash = :h"), {"h": digest})
                session.clear()
            elif now - row["last_seen_at"] > TOUCH:
                conn.execute(
                    text("UPDATE member_session SET last_seen_at = :now WHERE token_hash = :h"),
                    {"now": now, "h": digest},
                )
    except SQLAlchemyError:
        session.clear()


def end() -> None:
    """현재 세션만 끝낸다(로그아웃)."""
    token = session.get("sid")
    if token:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM member_session WHERE token_hash = :h"), {"h": token_hash(token)})
    session.clear()


def end_all(member_id: int) -> None:
    """회원의 모든 세션을 끝낸다(모든 기기 로그아웃, 비밀번호 변경·재설정, 탈퇴).

    @param member_id 회원 ID
    """
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM member_session WHERE member_id = :m"), {"m": member_id})


def purge_expired() -> int:
    """만료된 세션 행을 지운다(worker가 매일 실행).

    @returns 지운 행 수
    """
    now = _now()
    with engine.begin() as conn:
        return conn.execute(
            text("DELETE FROM member_session WHERE last_seen_at < :idle OR created_at < :absolute"),
            {"idle": now - IDLE, "absolute": now - ABSOLUTE},
        ).rowcount
