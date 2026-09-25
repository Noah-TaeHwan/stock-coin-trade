"""Central authorization helpers: who is the admin, who may use shared accounts."""

import os

from flask import current_app, has_app_context

from db import session_scope
from models import Member
from settings import DEFAULT_ADMIN_EMAIL


def admin_email() -> str:
    """The one admin address. Settings (ADMIN_EMAIL) is the single source."""
    if has_app_context():
        return current_app.config["ADMIN_EMAIL"]
    return os.environ.get("ADMIN_EMAIL", "").strip().lower() or DEFAULT_ADMIN_EMAIL


def _email_of(db, member_id: int) -> str | None:
    member = db.get(Member, member_id)
    return member.email.strip().lower() if member and member.email else None


def member_email(member_id: int | None, db=None) -> str | None:
    """Pass the caller's session as `db` when one is open: opening a nested
    session_scope here would commit and close the caller's transaction."""
    if not member_id:
        return None
    if db is not None:
        return _email_of(db, member_id)
    with session_scope() as own_db:
        return _email_of(own_db, member_id)


def is_admin_member(member_id: int | None, db=None) -> bool:
    email = member_email(member_id, db)
    return email is not None and email == admin_email()


def can_use_kis_account(member_id: int | None, db=None) -> bool:
    """All valid signed-in members may use the shared KIS Testbed account."""
    return member_email(member_id, db) is not None
