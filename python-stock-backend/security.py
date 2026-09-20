"""Small session-bound CSRF helpers for stateful JSON APIs."""

import hmac
import secrets

from flask import request, session


_CSRF_SESSION_KEY = "csrf_token"


def csrf_token() -> str:
    token = session.get(_CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[_CSRF_SESSION_KEY] = token
    return token


def csrf_is_valid() -> bool:
    expected = session.get(_CSRF_SESSION_KEY)
    supplied = request.headers.get("X-CSRF-Token", "")
    return bool(expected and supplied and hmac.compare_digest(expected, supplied))
