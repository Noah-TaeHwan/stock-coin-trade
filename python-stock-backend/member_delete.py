"""회원 탈퇴: 회원과 소유 데이터를 한 트랜잭션으로 지운다(설계: S1 스펙 ④).

삭제 목록에 없는 member_id 표가 생기면 tests/integration/test_member_delete.py가 실패한다.
"""

from __future__ import annotations

from sqlalchemy import text

from db import engine

# 자식 표부터 지운다(모의 KIS 주문·포지션 → 계좌).
DELETE_TABLES = (
    "hold_crypto", "crypto_order", "stock_order", "stock_position",
    "kis_practice_order", "kis_practice_position", "kis_practice_account",
    "hts_watch_memo", "alternative_order", "alternative_position", "api_key",
    "member_session", "member_token", "member_activity_day",
)
# 기록은 남기되 누구의 것인지 끊는다. ai_usage는 월 AI 예산 합계를 지키려고 남긴다. 로그는 90일 뒤 지워진다.
NULLIFY_TABLES = ("system_error_log", "api_usage_log", "ai_usage")
# 초대 코드 이름표에는 관리자가 적은 받는 사람 이름이 들어가므로, 탈퇴하면 이 값으로 바꾼다.
DELETED_LABEL = "탈퇴한 회원"


def ensure_deletable() -> None:
    """ai_usage.member_id를 NULL 허용으로 바꾼다(멱등). 탈퇴해도 비용 행을 남기기 위해서다."""
    with engine.begin() as conn:
        nullable = conn.execute(text(
            "SELECT IS_NULLABLE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = 'ai_usage' AND COLUMN_NAME = 'member_id'")).scalar()
        if nullable == "NO":
            conn.execute(text("ALTER TABLE ai_usage MODIFY member_id BIGINT(20) NULL"))


def delete_member(member_id: int) -> None:
    """회원과 소유 데이터를 지운다. 초대 코드는 연결을 끊고 이름표를 지우고 폐기한다.

    @param member_id 탈퇴할 회원 ID
    """
    params = {"m": member_id}
    with engine.begin() as conn:
        for table in DELETE_TABLES:
            conn.execute(text(f"DELETE FROM {table} WHERE member_id = :m"), params)
        conn.execute(text("UPDATE ai_invite SET member_id = NULL, label = :label, revoked_at = COALESCE(revoked_at, NOW()) "
                          "WHERE member_id = :m"), {**params, "label": DELETED_LABEL})
        for table in NULLIFY_TABLES:
            conn.execute(text(f"UPDATE {table} SET member_id = NULL WHERE member_id = :m"), params)
        conn.execute(text("DELETE FROM member WHERE member_id = :m"), params)
