"""Runtime settings for the Flask app, read once from the environment.

APP_PROFILE selects how strict startup is:
- local: developer and classroom runs; the historical dev fallbacks still work.
- public: an internet-facing deployment; startup fails instead of silently
  falling back to a well-known secret.
"""

from __future__ import annotations

import os
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

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_env_file() -> None:
    """Read the repository-root .env for runs outside Docker.

    Variables already set in the environment (for example by Compose) win,
    and a missing file is ignored. Call this before importing modules that
    read os.environ at import time.
    """
    load_dotenv(REPO_ROOT / ".env", override=False)


class SettingsError(RuntimeError):
    """Raised when the environment cannot be used for the selected profile."""


@dataclass(frozen=True)
class Settings:
    profile: str
    secret_key: str
    session_cookie_secure: bool

    @property
    def is_public(self) -> bool:
        return self.profile == "public"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if environ is None else environ
        profile = env.get("APP_PROFILE", "local").strip().lower()
        if profile not in PROFILES:
            raise SettingsError(f"APP_PROFILE must be one of {', '.join(PROFILES)}; got {profile!r}.")

        secret_key = env.get("SECRET_KEY", "").strip()
        if profile == "public":
            problems = []
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
            if problems:
                raise SettingsError("public profile refused to start: " + "; ".join(problems) + ".")

        return cls(
            profile=profile,
            secret_key=secret_key or DEV_SECRET_KEY,
            session_cookie_secure=env.get("SESSION_COOKIE_SECURE", "false").strip().lower() == "true",
        )

    def flask_config(self) -> dict[str, object]:
        return {
            "APP_PROFILE": self.profile,
            "SECRET_KEY": self.secret_key,
            "PERMANENT_SESSION_LIFETIME": timedelta(days=7),
            "SESSION_COOKIE_HTTPONLY": True,
            "SESSION_COOKIE_SAMESITE": "Lax",
            "SESSION_COOKIE_SECURE": self.session_cookie_secure,
        }
