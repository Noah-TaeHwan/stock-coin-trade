"""Client-safe error responses.

Exception text can carry hostnames, SQL, file paths or upstream URLs, so it
goes to the server log with a request id; the client gets a fixed message and
the same id to quote when reporting a problem.
"""

import logging
import uuid

from flask import g, has_request_context, jsonify

LOGGER = logging.getLogger("app.errors")


def request_id() -> str:
    if not has_request_context():
        return "-"
    if not getattr(g, "request_id", None):
        g.request_id = uuid.uuid4().hex[:16]
    return g.request_id


def log_exception(where: str, exc: BaseException) -> str:
    rid = request_id()
    LOGGER.error("%s failed (request %s)", where, rid, exc_info=exc)
    return rid


def error_response(message: str, exc: BaseException, status: int = 500, key: str = "error", **extra):
    """Log `exc` and return `{key: message, "requestId": ...}` without the exception text."""
    rid = log_exception(message, exc)
    return jsonify({key: message, "requestId": rid, **extra}), status
