from flask import Blueprint, jsonify, session
from authz import is_admin_member

admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")

def _require_admin():
    """관리자 계정이면 username을, 아니면 None을 반환한다."""
    member_id = session.get("member_id")
    if not member_id:
        return None
    return "admin" if is_admin_member(member_id) else None


def _forbidden():
    return jsonify({"error": "관리자만 접근 가능합니다."}), 403


@admin_bp.get("/me")
def admin_me():
    username = _require_admin()
    if not username:
        return _forbidden()
    return jsonify({"admin": True, "username": username})
