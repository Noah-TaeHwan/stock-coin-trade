"""Runtime settings for the Flask app, read once from the environment.

APP_PROFILE selects how strict startup is:
- local: developer and classroom runs; the historical dev fallbacks still work.
- public: an internet-facing deployment; startup fails instead of silently
  falling back to a well-known secret.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

# Keep this module free of imports that read os.environ at import time:
# entrypoints call load_env_file() from here before importing the rest.

PROFILES = ("local", "public")
# Local-only fallbacks kept for the original classroom setup. The public
# profile refuses to start with either of them.
DEV_SECRET_KEY = "dev-secret-change-me"
DEV_DB_PASSWORD = "12345678!!"
MIN_PUBLIC_SECRET_KEY_LENGTH = 32
# Placeholders shipped in .env.example. Copying that file unchanged must not
# yield a public deployment signed with a key anyone can read in the repo.
EXAMPLE_PLACEHOLDERS = frozenset({"change-me", "change-me-to-a-long-random-value"})
# 원본 교실 설정의 관리자 주소. public에서는 명시적으로 다른 주소를 요구한다.
DEFAULT_ADMIN_EMAIL = "admin@admin.com"
MEMORY_RATELIMIT_STORAGE = "memory://"
# Research agent (src/deskagent). Off unless AI_ENABLED=true; then a monthly
# USD budget is required, and public also needs a real invite-code pepper.
DEFAULT_AI_MODEL = "claude-opus-5-5"
DEV_AI_INVITE_PEPPER = "dev-invite-pepper-change-me"
MIN_AI_INVITE_PEPPER_LENGTH = 32

REPO_ROOT = Path(__file__).resolve().parents[1]

# Portfolio packages live in <repo>/src (marketdata, ...). The Docker image sets
# PYTHONPATH=/app/src; direct runs (`python app.py`, `python worker.py`) from a
# checkout find them here. Every entrypoint imports this module first.
_SRC_DIR = REPO_ROOT / "src"
if _SRC_DIR.is_dir() and str(_SRC_DIR) not in sys.path:
    sys.path.append(str(_SRC_DIR))


def load_env_file() -> None:
    """Read the repository-root .env for runs outside Docker.

    Variables already set in the environment (for example by Compose) win,
    and a missing file is ignored. Call this before importing modules that
    read os.environ at import time.
    """
    load_dotenv(REPO_ROOT / ".env", override=False)


def profile_from_env(environ: Mapping[str, str] | None = None) -> str:
    """APP_PROFILE 값(소문자). 검증은 Settings.from_env가 한다."""
    env = os.environ if environ is None else environ
    return env.get("APP_PROFILE", "local").strip().lower()


class SettingsError(RuntimeError):
    """Raised when the environment cannot be used for the selected profile."""


@dataclass(frozen=True)
class Settings:
    profile: str
    secret_key: str
    session_cookie_secure: bool
    admin_email: str = DEFAULT_ADMIN_EMAIL
    # local은 교실 실습(한 IP 뒤의 여러 학생)을 막지 않도록 기본으로 끈다.
    ratelimit_enabled: bool = False
    ratelimit_storage_uri: str = MEMORY_RATELIMIT_STORAGE
    # 앞단 리버스 프록시 수. X-Forwarded-For를 이 수만큼만 믿는다(Werkzeug ProxyFix).
    trusted_proxy_count: int = 0
    ai_enabled: bool = False
    ai_monthly_budget_usd: float = 0.0
    ai_model: str = DEFAULT_AI_MODEL
    ai_invite_pepper: str = DEV_AI_INVITE_PEPPER
    # 자연어 명령 라우터(src/deskjev, TypeSafe Jev). 기본 꺼짐. 켜면 월 예산과 TYPESAFE_API_KEY가 필요하다.
    jev_enabled: bool = False
    jev_monthly_budget_usd: float = 0.0
    # OpenDART 인증키(공시 레이더 수집기, worker 전용). 비어 있으면 수집 작업을 걸지 않는다. Flask 설정에는 넣지 않는다.
    dart_api_key: str = ""
    # 가입을 받을지. public은 인증 메일이 필요하므로 SMTP_HOST와 https PUBLIC_BASE_URL이 있어야만 열린다.
    signup_enabled: bool = True
    smtp_host: str = ""
    # 메일 속 링크의 기준 주소. 요청의 Host 헤더로 링크를 만들지 않는다(재설정 링크 변조 방지).
    public_base_url: str = ""

    @property
    def is_public(self) -> bool:
        return self.profile == "public"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if environ is None else environ
        profile = profile_from_env(env)
        if profile not in PROFILES:
            raise SettingsError(f"APP_PROFILE must be one of {', '.join(PROFILES)}; got {profile!r}.")

        secret_key = env.get("SECRET_KEY", "").strip()
        admin_email = env.get("ADMIN_EMAIL", "").strip().lower()
        ratelimit_storage_uri = env.get("RATELIMIT_STORAGE_URI", "").strip() or MEMORY_RATELIMIT_STORAGE
        ratelimit_default = "true" if profile == "public" else "false"
        # Compose passes unset variables as empty strings; treat those as unset.
        ratelimit_enabled = (env.get("RATELIMIT_ENABLED") or ratelimit_default).strip().lower() == "true"
        try:
            trusted_proxy_count = int(env.get("TRUSTED_PROXY_COUNT") or "0")
        except ValueError:
            raise SettingsError("TRUSTED_PROXY_COUNT must be an integer.") from None
        if trusted_proxy_count < 0:
            raise SettingsError("TRUSTED_PROXY_COUNT must not be negative.")
        ai_enabled = (env.get("AI_ENABLED") or "false").strip().lower() == "true"
        ai_model = (env.get("AI_MODEL") or DEFAULT_AI_MODEL).strip()
        ai_invite_pepper = (env.get("AI_INVITE_PEPPER") or "").strip()
        try:
            ai_monthly_budget_usd = float(env.get("AI_MONTHLY_BUDGET_USD") or "0")
        except ValueError:
            raise SettingsError("AI_MONTHLY_BUDGET_USD must be a number.") from None
        jev_enabled = (env.get("JEV_ENABLED") or "false").strip().lower() == "true"
        try:
            jev_monthly_budget_usd = float(env.get("JEV_MONTHLY_BUDGET_USD") or "0")
        except ValueError:
            raise SettingsError("JEV_MONTHLY_BUDGET_USD must be a number.") from None
        if jev_enabled:
            if jev_monthly_budget_usd <= 0:
                raise SettingsError("JEV_ENABLED=true needs JEV_MONTHLY_BUDGET_USD greater than 0.")
            if not (env.get("TYPESAFE_API_KEY") or "").strip():
                raise SettingsError("JEV_ENABLED=true needs TYPESAFE_API_KEY.")
        if ai_enabled:
            from deskagent import pricing

            if ai_monthly_budget_usd <= 0:
                raise SettingsError("AI_ENABLED=true needs AI_MONTHLY_BUDGET_USD greater than 0.")
            if ai_model not in pricing.load():
                raise SettingsError(f"AI_MODEL {ai_model!r} has no price in config/llm_pricing.toml.")
        smtp_host = (env.get("SMTP_HOST") or "").strip()
        public_base_url = (env.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
        mail_ready = bool(smtp_host) and public_base_url.startswith("https://")
        signup_default = "true" if profile == "local" or mail_ready else "false"
        signup_enabled = (env.get("SIGNUP_ENABLED") or signup_default).strip().lower() == "true"
        if profile == "public":
            problems = []
            if env.get("SESSION_COOKIE_SECURE", "false").strip().lower() != "true":
                problems.append("SESSION_COOKIE_SECURE must be true")
            if signup_enabled and not mail_ready:
                problems.append("SIGNUP_ENABLED needs SMTP_HOST and an https:// PUBLIC_BASE_URL")
            if ai_enabled and (
                len(ai_invite_pepper) < MIN_AI_INVITE_PEPPER_LENGTH or ai_invite_pepper in EXAMPLE_PLACEHOLDERS
            ):
                problems.append(
                    f"AI_INVITE_PEPPER must be a random value of at least {MIN_AI_INVITE_PEPPER_LENGTH} characters"
                )
            if (
                not secret_key
                or secret_key in {DEV_SECRET_KEY, *EXAMPLE_PLACEHOLDERS}
                or len(secret_key) < MIN_PUBLIC_SECRET_KEY_LENGTH
            ):
                problems.append(
                    f"SECRET_KEY must be set to a random value of at least {MIN_PUBLIC_SECRET_KEY_LENGTH} characters"
                )
            db_password = env.get("DB_PASSWORD", "")
            if not db_password or db_password in {DEV_DB_PASSWORD, *EXAMPLE_PLACEHOLDERS}:
                problems.append("DB_PASSWORD must be set to a non-default value")
            if not admin_email or admin_email == DEFAULT_ADMIN_EMAIL or "@" not in admin_email:
                problems.append(f"ADMIN_EMAIL must be set to an address other than {DEFAULT_ADMIN_EMAIL}")
            if not ratelimit_enabled:
                problems.append("RATELIMIT_ENABLED must stay on")
            if ratelimit_storage_uri.startswith(MEMORY_RATELIMIT_STORAGE):
                problems.append("RATELIMIT_STORAGE_URI must point at shared storage such as redis://")
            if problems:
                raise SettingsError("public profile refused to start: " + "; ".join(problems) + ".")

        return cls(
            profile=profile,
            secret_key=secret_key or DEV_SECRET_KEY,
            session_cookie_secure=env.get("SESSION_COOKIE_SECURE", "false").strip().lower() == "true",
            admin_email=admin_email or DEFAULT_ADMIN_EMAIL,
            ratelimit_enabled=ratelimit_enabled,
            ratelimit_storage_uri=ratelimit_storage_uri,
            trusted_proxy_count=trusted_proxy_count,
            ai_enabled=ai_enabled,
            ai_monthly_budget_usd=ai_monthly_budget_usd,
            ai_model=ai_model,
            ai_invite_pepper=ai_invite_pepper or DEV_AI_INVITE_PEPPER,
            jev_enabled=jev_enabled,
            jev_monthly_budget_usd=jev_monthly_budget_usd,
            dart_api_key=(env.get("DART_API_KEY") or "").strip(),
            signup_enabled=signup_enabled,
            smtp_host=smtp_host,
            public_base_url=public_base_url,
        )

    def flask_config(self) -> dict[str, object]:
        return {
            "APP_PROFILE": self.profile,
            "SECRET_KEY": self.secret_key,
            "PERMANENT_SESSION_LIFETIME": timedelta(days=7),
            "SESSION_COOKIE_HTTPONLY": True,
            "SESSION_COOKIE_SAMESITE": "Lax",
            "SESSION_COOKIE_SECURE": self.session_cookie_secure,
            "ADMIN_EMAIL": self.admin_email,
            "RATELIMIT_ENABLED": self.ratelimit_enabled,
            "RATELIMIT_STORAGE_URI": self.ratelimit_storage_uri,
            "AI_ENABLED": self.ai_enabled,
            "AI_MONTHLY_BUDGET_USD": self.ai_monthly_budget_usd,
            "AI_MODEL": self.ai_model,
            "AI_INVITE_PEPPER": self.ai_invite_pepper,
            "JEV_ENABLED": self.jev_enabled,
            "JEV_MONTHLY_BUDGET_USD": self.jev_monthly_budget_usd,
            "SIGNUP_ENABLED": self.signup_enabled,
            "PUBLIC_BASE_URL": self.public_base_url,
        }
