"""Central authorization helpers for server-owned broker accounts."""

import os

from db import session_scope
from models import Member


ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@admin.com").strip().lower()


def member_email(member_id: int | None) -> str | None:
    if not member_id:
        return None
    with session_scope() as db:
        member = db.get(Member, member_id)
        return member.email.strip().lower() if member and member.email else None


def is_admin_member(member_id: int | None) -> bool:
    return member_email(member_id) == ADMIN_EMAIL


def can_use_kis_account(member_id: int | None) -> bool:
    """All valid signed-in members may use the shared KIS Testbed account."""
    return member_email(member_id) is not None
