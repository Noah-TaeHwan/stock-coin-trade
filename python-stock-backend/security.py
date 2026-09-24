"""CSRF defences for the cookie-authenticated JSON APIs.

Two layers:
- cross_site_request_rejected(): a global check on every state-changing
  request, following the OWASP CSRF Cheat Sheet: trust Fetch Metadata
  (Sec-Fetch-Site) when the browser sends it, fall back to the Origin header,
  and let requests with neither through (they do not come from a browser).
- csrf_token()/csrf_is_valid(): the existing per-session token that the KIS
  lab routes additionally require.
"""

import hmac
import re
import secrets
from urllib.parse import urlparse

from flask import request, session

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
# Bearer-token API for external modules; it does not use the session cookie.
CSRF_EXEMPT_PREFIXES = ("/openapi/",)
# The local profile also serves a dev frontend on another localhost port.
_LOCAL_DEV_ORIGIN = re.compile(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$")


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


def cross_site_request_rejected(profile: str) -> bool:
    """True when a state-changing request comes from another site."""
    if request.method in SAFE_METHODS or request.path.startswith(CSRF_EXEMPT_PREFIXES):
        return False
    local = profile != "public"
    site = request.headers.get("Sec-Fetch-Site")
    if site:
        allowed = {"same-origin", "none"} | ({"same-site"} if local else set())
        return site not in allowed
    origin = request.headers.get("Origin")
    if origin:
        if urlparse(origin).netloc == request.host:
            return False
        return not (local and _LOCAL_DEV_ORIGIN.match(origin))
    return False
