"""정기 정리: 7일 미인증 가입, 90일 지난 로그(설계: S1 스펙 ③·④). worker가 매일 실행한다.

시각 비교는 DB의 NOW()로 한다(열 기본값이 DB 시각이라 파이썬 시각과 섞지 않는다).
"""

from __future__ import annotations

from sqlalchemy import text

from db import engine
from member_delete import delete_member

UNVERIFIED_DAYS = 7
LOG_DAYS = 90


def purge_unverified_members() -> int:
    """새 가입 흐름(동의 기록 있음)으로 만든 뒤 7일 안에 인증하지 않은 계정을 지운다.

    @returns 지운 계정 수
    """
    with engine.connect() as conn:
        ids = conn.execute(text(
            "SELECT member_id FROM member WHERE email_verified_at IS NULL AND consent_version IS NOT NULL "
            f"AND created_at < NOW() - INTERVAL {UNVERIFIED_DAYS} DAY")).scalars().all()
    for member_id in ids:
        delete_member(member_id)
    return len(ids)


def purge_old_logs() -> int:
    """90일 지난 오류·외부 API 사용 로그를 지운다.

    @returns 지운 행 수
    """
    with engine.begin() as conn:
        errors = conn.execute(text(f"DELETE FROM system_error_log WHERE occurred_at < NOW() - INTERVAL {LOG_DAYS} DAY")).rowcount
        usage = conn.execute(text(f"DELETE FROM api_usage_log WHERE called_at < NOW() - INTERVAL {LOG_DAYS} DAY")).rowcount
    return errors + usage
