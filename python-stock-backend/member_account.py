"""메일 인증·재설정·비밀번호 변경·탈퇴 API(설계: S1 스펙 ③·④). 가입·로그인은 members.py."""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from sqlalchemy import text

import mailer
import member_tokens
from accounts import is_reserved_email
from db import engine
from extensions import limiter

account_bp = Blueprint("member_account", __name__, url_prefix="/api/member")
ACCEPTED = {"status": "accepted"}
INVALID_TOKEN = {"error": "INVALID_TOKEN", "message": "링크가 만료되었거나 이미 사용되었습니다. 다시 요청해 주세요."}


def _email_from_body() -> str:
    """요청 본문의 이메일(앞뒤 공백 제거).

    @returns 이메일 문자열
    """
    return str((request.get_json(silent=True) or {}).get("email") or "").strip()


def _find_member(email: str):
    """이메일로 회원을 찾는다. 형식이 틀리거나 예약 주소면 찾지 않는다.

    @param email 이메일
    @returns member_id·email·email_verified_at 매핑 또는 None
    """
    if not mailer.valid_address(email) or is_reserved_email(email):
        return None
    with engine.connect() as conn:
        return conn.execute(text("SELECT member_id, email, email_verified_at FROM member WHERE email = :e"),
                            {"e": email}).mappings().first()


@account_bp.post("/verify")
@limiter.limit("20 per hour")
def verify_email():
    """메일 링크의 토큰으로 이메일 인증을 마친다."""
    token = str((request.get_json(silent=True) or {}).get("token") or "")
    with engine.connect() as conn:
        member_id = member_tokens.consume(conn, token, "verify")
        if member_id is None:
            conn.rollback()
            return jsonify(INVALID_TOKEN), 400
        conn.execute(text("UPDATE member SET email_verified_at = COALESCE(email_verified_at, NOW()) WHERE member_id = :m"),
                     {"m": member_id})
        conn.commit()
    return jsonify({"verified": True})


@account_bp.post("/verify/resend")
@limiter.limit("10 per hour")
def resend_verification():
    """인증 메일을 다시 보낸다. 주소가 있든 없든, 이미 인증했든 같은 202로 답한다."""
    row = _find_member(_email_from_body())
    if row and row["email_verified_at"] is None:
        mailer.queue("verify", row["email"], member_tokens.issue(row["member_id"], "verify"))
    return jsonify(ACCEPTED), 202
