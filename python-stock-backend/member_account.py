"""메일 인증·재설정·비밀번호 변경·탈퇴 API(설계: S1 스펙 ③·④). 가입·로그인은 members.py."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request, session
from sqlalchemy import text

import mailer
import member_delete
import member_sessions
import member_tokens
import passwords
from accounts import is_reserved_email
from authz import admin_email
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


def _member_key() -> str:
    """회원 단위 제한 키(세션은 before_request 훅이 이미 검증했다).

    @returns "member:<id>"
    """
    return f"member:{session.get('member_id')}"


@account_bp.post("/password/reset-request")
@limiter.limit("10 per hour")
def request_password_reset():
    """재설정 메일을 보낸다. 항상 202. 공개 배포의 관리자 주소는 메일로 재설정하지 않는다(CLI만)."""
    email = _email_from_body()
    public_admin = current_app.config["APP_PROFILE"] == "public" and email.lower() == admin_email()
    row = None if public_admin else _find_member(email)
    if row:
        mailer.queue("reset", row["email"], member_tokens.issue(row["member_id"], "reset"))
    return jsonify(ACCEPTED), 202


@account_bp.post("/password/reset")
@limiter.limit("20 per hour")
def reset_password():
    """토큰으로 새 비밀번호를 정한다. 모든 세션을 끝내고 API 키를 끄며, 자동 로그인하지 않는다."""
    body = request.get_json(silent=True) or {}
    token, password, password2 = str(body.get("token") or ""), body.get("password") or "", body.get("password2") or ""
    if not password or password != password2:
        return jsonify({"field": "password2", "error": "비밀번호가 일치하지 않습니다."}), 400
    with engine.connect() as conn:
        member_id = member_tokens.consume(conn, token, "reset")
        if member_id is None:
            conn.rollback()
            return jsonify(INVALID_TOKEN), 400
        row = conn.execute(text("SELECT email, username FROM member WHERE member_id = :m"), {"m": member_id}).mappings().first()
        weak = passwords.problem(password, email=row["email"], nickname=row["username"] or "")
        if weak:
            conn.rollback()  # 토큰을 되살려 같은 링크로 다시 시도하게 한다
            return jsonify({"field": "password", "error": weak}), 400
        conn.execute(text("UPDATE member SET password = :p, email_verified_at = COALESCE(email_verified_at, NOW()) "
                          "WHERE member_id = :m"), {"p": passwords.hash_password(password), "m": member_id})
        conn.execute(text("DELETE FROM member_session WHERE member_id = :m"), {"m": member_id})
        conn.execute(text("UPDATE api_key SET is_active = 0 WHERE member_id = :m"), {"m": member_id})
        conn.commit()
    session.clear()
    return jsonify({"success": True})


@account_bp.post("/password/change")
@limiter.limit("10 per hour", key_func=_member_key)
def change_password():
    """현재 비밀번호를 확인하고 바꾼다. 다른 기기 세션은 끝내고 이 기기는 새 세션을 받는다."""
    member_id = session.get("member_id")
    if not member_id:
        return jsonify({"error": "UNAUTHORIZED", "message": "로그인이 필요합니다."}), 401
    body = request.get_json(silent=True) or {}
    current, password, password2 = body.get("current") or "", body.get("password") or "", body.get("password2") or ""
    if not password or password != password2:
        return jsonify({"field": "password2", "error": "비밀번호가 일치하지 않습니다."}), 400
    with engine.connect() as conn:
        row = conn.execute(text("SELECT email, username, password FROM member WHERE member_id = :m"),
                           {"m": member_id}).mappings().first()
        if not row or not passwords.verify(current, row["password"]):
            return jsonify({"field": "current", "error": "현재 비밀번호가 맞지 않습니다."}), 400
        weak = passwords.problem(password, email=row["email"], nickname=row["username"] or "")
        if weak:
            return jsonify({"field": "password", "error": weak}), 400
        conn.execute(text("UPDATE member SET password = :p WHERE member_id = :m"),
                     {"p": passwords.hash_password(password), "m": member_id})
        conn.execute(text("DELETE FROM member_session WHERE member_id = :m"), {"m": member_id})
        conn.commit()
    member_sessions.start(member_id)
    return jsonify({"success": True})


@account_bp.post("/delete")
@limiter.limit("10 per hour", key_func=_member_key)
def delete_account():
    """현재 비밀번호를 확인하고 회원과 소유 데이터를 즉시 지운다."""
    member_id = session.get("member_id")
    if not member_id:
        return jsonify({"error": "UNAUTHORIZED", "message": "로그인이 필요합니다."}), 401
    password = (request.get_json(silent=True) or {}).get("password") or ""
    with engine.connect() as conn:
        stored = conn.execute(text("SELECT password FROM member WHERE member_id = :m"), {"m": member_id}).scalar()
    if not passwords.verify(password, stored):
        return jsonify({"field": "password", "error": "비밀번호가 맞지 않습니다."}), 400
    member_delete.delete_member(member_id)
    session.clear()
    return jsonify({"success": True})
