"""Invite-only research agent API (src/deskagent) with per-invite limits and a monthly budget.

- An admin creates invite codes with `flask --app app create-invite`; only an
  HMAC-SHA256 of the code (keyed with AI_INVITE_PEPPER) is stored.
- A signed-in member redeems a code once; it is then bound to that member.
- Each question reserves one request on the invite under a row lock, checks
  the month's recorded spend against AI_MONTHLY_BUDGET_USD, runs the agent,
  and records tokens and cost (config/llm_pricing.toml) in ai_usage.

The budget check happens before a run, so concurrent requests can overshoot
the budget by at most the cost of the runs already in flight; each run is
bounded by the agent's turn and token limits.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta

import click
from flask import Blueprint, current_app, jsonify, request, session
from flask.cli import with_appcontext
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from db import engine
from errors import error_response, log_exception
from extensions import limiter

research_agent_bp = Blueprint("research_agent", __name__, url_prefix="/api/agent")

MAX_QUESTION_CHARS = 1000
INVITE_PREFIX = "inv_"

AI_TABLES = (
    """CREATE TABLE IF NOT EXISTS ai_invite (
      invite_id BIGINT AUTO_INCREMENT PRIMARY KEY,
      code_hash CHAR(64) NOT NULL,
      label VARCHAR(100) NOT NULL,
      member_id BIGINT NULL,
      created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      expires_at DATETIME NOT NULL,
      max_requests INT NOT NULL,
      max_tokens BIGINT NOT NULL,
      used_requests INT NOT NULL DEFAULT 0,
      used_tokens BIGINT NOT NULL DEFAULT 0,
      revoked_at DATETIME NULL,
      UNIQUE KEY uq_ai_invite_code (code_hash),
      KEY idx_ai_invite_member (member_id),
      CONSTRAINT fk_ai_invite_member FOREIGN KEY (member_id) REFERENCES member(member_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS ai_usage (
      ai_usage_id BIGINT AUTO_INCREMENT PRIMARY KEY,
      created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      member_id BIGINT NOT NULL,
      invite_id BIGINT NOT NULL,
      model VARCHAR(60) NOT NULL,
      status VARCHAR(20) NOT NULL,
      input_tokens INT NOT NULL DEFAULT 0,
      output_tokens INT NOT NULL DEFAULT 0,
      cache_write_tokens INT NOT NULL DEFAULT 0,
      cache_read_tokens INT NOT NULL DEFAULT 0,
      cost_usd DECIMAL(12, 6) NOT NULL DEFAULT 0,
      turns INT NOT NULL DEFAULT 0,
      question_chars INT NOT NULL,
      receipts TEXT NULL,
      KEY idx_ai_usage_created (created_at),
      KEY idx_ai_usage_member (member_id, created_at),
      CONSTRAINT fk_ai_usage_member FOREIGN KEY (member_id) REFERENCES member(member_id),
      CONSTRAINT fk_ai_usage_invite FOREIGN KEY (invite_id) REFERENCES ai_invite(invite_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
)


def ensure_ai_tables() -> None:
    with engine.begin() as conn:
        for statement in AI_TABLES:
            conn.execute(text(statement))


def code_hash(code: str, pepper: str) -> str:
    return hmac.new(pepper.encode(), code.strip().encode(), hashlib.sha256).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def month_spend(conn, now: datetime) -> float:
    spent = conn.execute(
        text("SELECT COALESCE(SUM(cost_usd), 0) FROM ai_usage WHERE created_at >= :start"),
        {"start": _month_start(now)},
    ).scalar_one()
    return float(spent)


def _invite_problem(invite, now: datetime) -> str | None:
    if invite is None:
        return "초대 코드를 먼저 등록하세요."
    if invite["revoked_at"] is not None:
        return "초대 코드가 폐기되었습니다."
    if invite["expires_at"] <= now:
        return "초대 코드가 만료되었습니다."
    if invite["used_requests"] >= invite["max_requests"]:
        return "초대 코드의 질문 횟수를 모두 사용했습니다."
    if invite["used_tokens"] >= invite["max_tokens"]:
        return "초대 코드의 토큰 한도를 모두 사용했습니다."
    return None


def _anthropic_client():
    """Official SDK client; reads ANTHROPIC_API_KEY. Tests replace this factory."""
    import anthropic

    return anthropic.Anthropic()


class DeskBackend:
    """deskagent tools executed in-process with the same code as /api/quant."""

    def sources(self) -> dict:
        import quant

        return quant.sources_payload()

    def run_backtest(self, payload: dict) -> dict:
        import quant
        from deskagent.tools import ToolFailed

        try:
            body, _ = quant.execute_backtest(payload)
        except (quant.NotEnoughBars, quant.SourceBlocked) as exc:
            raise ToolFailed(str(exc)) from None
        except (ValueError, TypeError, KeyError) as exc:
            raise ToolFailed(f"invalid backtest request: {exc}") from None
        except SQLAlchemyError:
            raise ToolFailed("the research database is unavailable") from None
        return body

    def get_backtest(self, receipt_id: str) -> dict | None:
        import quant
        from deskagent.tools import ToolFailed

        try:
            return quant.stored_backtest(receipt_id)
        except ValueError as exc:
            raise ToolFailed(str(exc)) from None
        except SQLAlchemyError:
            raise ToolFailed("the research database is unavailable") from None


def _require_member():
    member_id = session.get("member_id")
    if not member_id:
        return None, (jsonify({"error": "UNAUTHORIZED", "message": "로그인이 필요합니다."}), 401)
    return member_id, None


def _disabled():
    return jsonify({"error": "AI_DISABLED", "message": "AI 리서치 기능이 꺼져 있습니다."}), 503


@research_agent_bp.get("/status")
def status():
    member_id = session.get("member_id")
    body = {"enabled": bool(current_app.config.get("AI_ENABLED")), "model": current_app.config.get("AI_MODEL"),
            "invite": None}
    if not member_id or not body["enabled"]:
        return jsonify(body)
    try:
        with engine.connect() as conn:
            invite = conn.execute(text(
                "SELECT label, expires_at, max_requests, used_requests, max_tokens, used_tokens, revoked_at "
                "FROM ai_invite WHERE member_id = :m ORDER BY invite_id DESC LIMIT 1"
            ), {"m": member_id}).mappings().first()
    except SQLAlchemyError as exc:
        return error_response("AI 상태 조회 실패", exc, 503, key="message")
    if invite:
        body["invite"] = {
            "label": invite["label"], "expiresAt": invite["expires_at"].isoformat(),
            "requestsLeft": max(0, invite["max_requests"] - invite["used_requests"]),
            "tokensLeft": max(0, invite["max_tokens"] - invite["used_tokens"]),
            "usable": _invite_problem(invite, _now()) is None,
        }
    return jsonify(body)


@research_agent_bp.post("/redeem")
@limiter.limit("10 per hour")
def redeem():
    if not current_app.config.get("AI_ENABLED"):
        return _disabled()
    member_id, denied = _require_member()
    if denied:
        return denied
    code = str((request.get_json(silent=True) or {}).get("code", "")).strip()
    if not code.startswith(INVITE_PREFIX) or len(code) > 100:
        return jsonify({"error": "INVALID_INVITE", "message": "초대 코드를 확인하세요."}), 400
    digest = code_hash(code, current_app.config["AI_INVITE_PEPPER"])
    try:
        with engine.begin() as conn:
            invite = conn.execute(text(
                "SELECT invite_id, member_id, expires_at, revoked_at, max_requests, used_requests, max_tokens, "
                "used_tokens FROM ai_invite WHERE code_hash = :h FOR UPDATE"
            ), {"h": digest}).mappings().first()
            # Same message for unknown and taken codes, so codes cannot be probed.
            if invite is None or (invite["member_id"] not in (None, member_id)):
                return jsonify({"error": "INVALID_INVITE", "message": "초대 코드를 확인하세요."}), 400
            problem = _invite_problem(invite, _now())
            if problem:
                return jsonify({"error": "INVITE_UNUSABLE", "message": problem}), 403
            conn.execute(text("UPDATE ai_invite SET member_id = :m WHERE invite_id = :i"),
                         {"m": member_id, "i": invite["invite_id"]})
    except SQLAlchemyError as exc:
        return error_response("초대 코드 등록 실패", exc, 503, key="message")
    return jsonify({"message": "초대 코드를 등록했습니다."})


@research_agent_bp.post("/ask")
@limiter.limit("6 per minute")
def ask():
    if not current_app.config.get("AI_ENABLED"):
        return _disabled()
    member_id, denied = _require_member()
    if denied:
        return denied
    question = str((request.get_json(silent=True) or {}).get("question", "")).strip()
    if not question or len(question) > MAX_QUESTION_CHARS:
        return jsonify({"error": "INVALID_QUESTION", "message": f"질문은 1~{MAX_QUESTION_CHARS}자로 입력하세요."}), 400
    budget = float(current_app.config["AI_MONTHLY_BUDGET_USD"])
    model = current_app.config["AI_MODEL"]
    now = _now()
    try:
        with engine.begin() as conn:
            invite = conn.execute(text(
                "SELECT invite_id, expires_at, revoked_at, max_requests, used_requests, max_tokens, used_tokens "
                "FROM ai_invite WHERE member_id = :m ORDER BY invite_id DESC LIMIT 1 FOR UPDATE"
            ), {"m": member_id}).mappings().first()
            problem = _invite_problem(invite, now)
            if problem:
                return jsonify({"error": "INVITE_REQUIRED", "message": problem}), 403
            if month_spend(conn, now) >= budget:
                return jsonify({"error": "BUDGET_EXHAUSTED",
                                "message": "이번 달 AI 예산을 모두 사용했습니다. 다음 달에 다시 이용하세요."}), 503
            conn.execute(text("UPDATE ai_invite SET used_requests = used_requests + 1 WHERE invite_id = :i"),
                         {"i": invite["invite_id"]})
    except SQLAlchemyError as exc:
        return error_response("AI 요청 준비 실패", exc, 503, key="message")

    from deskagent.agent import ask as run_agent

    import anthropic

    try:
        result = run_agent(_anthropic_client(), DeskBackend(), question, model=model)
    except anthropic.RateLimitError as exc:
        log_exception("research agent rate limited", exc)
        return jsonify({"error": "AI_BUSY", "message": "AI 요청이 많습니다. 잠시 후 다시 시도하세요."}), 503
    except anthropic.APIStatusError as exc:
        log_exception("research agent API error", exc)
        return jsonify({"error": "AI_UPSTREAM", "message": "AI 응답을 받지 못했습니다."}), 502
    except anthropic.APIConnectionError as exc:
        log_exception("research agent connection error", exc)
        return jsonify({"error": "AI_UPSTREAM", "message": "AI 서버에 연결하지 못했습니다."}), 502

    usage = result.usage
    try:
        with engine.begin() as conn:
            conn.execute(text("UPDATE ai_invite SET used_tokens = used_tokens + :t WHERE invite_id = :i"),
                         {"t": usage.total, "i": invite["invite_id"]})
            conn.execute(text("""
                INSERT INTO ai_usage(member_id, invite_id, model, status, input_tokens, output_tokens,
                                     cache_write_tokens, cache_read_tokens, cost_usd, turns, question_chars, receipts)
                VALUES (:m, :i, :model, :status, :inp, :out, :cw, :cr, :cost, :turns, :chars, :receipts)
            """), {"m": member_id, "i": invite["invite_id"], "model": model, "status": result.status,
                   "inp": usage.input_tokens, "out": usage.output_tokens, "cw": usage.cache_creation_input_tokens,
                   "cr": usage.cache_read_input_tokens, "cost": round(result.cost_usd, 6), "turns": result.turns,
                   "chars": len(question),
                   "receipts": json.dumps((result.rendered or {}).get("receipts", []))})
    except SQLAlchemyError as exc:
        log_exception("research agent usage was not recorded", exc)
    return jsonify(result.as_dict())


def create_invite(label: str, days: int, max_requests: int, max_tokens: int, pepper: str) -> str:
    """Store a new invite and return the code; the code itself is never stored."""
    code = INVITE_PREFIX + secrets.token_urlsafe(18)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO ai_invite(code_hash, label, expires_at, max_requests, max_tokens)
            VALUES (:h, :label, :exp, :req, :tok)
        """), {"h": code_hash(code, pepper), "label": label[:100], "exp": _now() + timedelta(days=days),
               "req": max_requests, "tok": max_tokens})
    return code


@click.command("create-invite")
@click.option("--label", required=True, help="Who the code is for (stored).")
@click.option("--days", default=14, show_default=True, type=click.IntRange(1, 365))
@click.option("--max-requests", default=20, show_default=True, type=click.IntRange(1, 10_000))
@click.option("--max-tokens", default=400_000, show_default=True, type=click.IntRange(1_000, 100_000_000))
@with_appcontext
def create_invite_command(label: str, days: int, max_requests: int, max_tokens: int) -> None:
    """Create an AI research invite code and print it once."""
    ensure_ai_tables()
    code = create_invite(label, days, max_requests, max_tokens, current_app.config["AI_INVITE_PEPPER"])
    click.echo(code)
