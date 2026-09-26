"""메일 인증·비밀번호 재설정용 1회용 토큰(설계: S1 스펙 ③). DB에는 SHA-256만 둔다."""

from __future__ import annotations

import secrets
from datetime import timedelta

from sqlalchemy import text

from db import engine
from member_sessions import _now, token_hash

LIFETIME = {"verify": timedelta(hours=24), "reset": timedelta(minutes=30)}

TOKEN_TABLE = """CREATE TABLE IF NOT EXISTS member_token (
  token_hash CHAR(64) NOT NULL,
  member_id BIGINT(20) NOT NULL,
  purpose ENUM('verify','reset') NOT NULL,
  expires_at DATETIME NOT NULL COMMENT 'UTC',
  used_at DATETIME NULL COMMENT 'UTC',
  PRIMARY KEY (token_hash),
  KEY idx_member_token_member (member_id, purpose),
  CONSTRAINT fk_member_token_member FOREIGN KEY (member_id) REFERENCES member (member_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci"""

__all__ = ["LIFETIME", "consume", "ensure_token_table", "issue", "token_hash"]


def ensure_token_table() -> None:
    """member_token 표를 만든다(멱등)."""
    with engine.begin() as conn:
        conn.execute(text(TOKEN_TABLE))


def issue(member_id: int, purpose: str) -> str:
    """새 토큰을 발급하고 같은 목적의 이전 토큰을 지운다.

    @param member_id 회원 ID
    @param purpose "verify" 또는 "reset"
    @returns 메일 링크에 넣을 원본 토큰(저장하지 않음)
    """
    token = secrets.token_urlsafe(32)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM member_token WHERE member_id = :m AND purpose = :p"), {"m": member_id, "p": purpose})
        conn.execute(
            text("INSERT INTO member_token (token_hash, member_id, purpose, expires_at) VALUES (:h, :m, :p, :exp)"),
            {"h": token_hash(token), "m": member_id, "p": purpose, "exp": _now() + LIFETIME[purpose]},
        )
    return token


def consume(conn, token: str, purpose: str) -> int | None:
    """토큰을 원자적으로 사용 처리한다. 커밋·롤백은 호출자가 한다(뒤이은 검사가 실패하면 롤백해 토큰을 되살린다).

    @param conn 트랜잭션 중인 연결
    @param token 원본 토큰
    @param purpose "verify" 또는 "reset"
    @returns 회원 ID, 없거나 만료·사용된 토큰이면 None
    """
    if not token:
        return None
    digest, now = token_hash(token), _now()
    used = conn.execute(
        text("UPDATE member_token SET used_at = :now WHERE token_hash = :h AND purpose = :p "
             "AND used_at IS NULL AND expires_at > :now"),
        {"now": now, "h": digest, "p": purpose},
    ).rowcount
    if used != 1:
        return None
    return conn.execute(text("SELECT member_id FROM member_token WHERE token_hash = :h"), {"h": digest}).scalar()
