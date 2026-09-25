from datetime import timedelta
from pathlib import Path

import pytest
from dotenv import dotenv_values

from settings import DEV_DB_PASSWORD, DEV_SECRET_KEY, Settings, SettingsError

STRONG_SECRET = "s" * 32
PUBLIC_ENV = {
    "APP_PROFILE": "public",
    "SECRET_KEY": STRONG_SECRET,
    "DB_PASSWORD": "a-real-db-password",
    "ADMIN_EMAIL": "owner@example.com",
    "RATELIMIT_STORAGE_URI": "redis://redis:6379/0",
}
ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"


def test_local_profile_keeps_the_classroom_fallbacks():
    settings = Settings.from_env({})
    assert settings.profile == "local"
    assert not settings.is_public
    assert settings.secret_key == DEV_SECRET_KEY
    assert settings.session_cookie_secure is False


def test_unknown_profile_is_rejected():
    with pytest.raises(SettingsError, match="APP_PROFILE"):
        Settings.from_env({"APP_PROFILE": "prod"})


def test_profile_name_is_case_insensitive():
    assert Settings.from_env({"APP_PROFILE": " Local "}).profile == "local"


@pytest.mark.parametrize(
    "secret_key",
    ["", DEV_SECRET_KEY, "too-short", "change-me-to-a-long-random-value"],
    ids=["missing", "dev-default", "short", "env-example-placeholder"],
)
def test_public_profile_refuses_weak_secret_key(secret_key):
    env = {"APP_PROFILE": "public", "SECRET_KEY": secret_key, "DB_PASSWORD": "db-password-from-secret-store"}
    with pytest.raises(SettingsError, match="SECRET_KEY"):
        Settings.from_env(env)


@pytest.mark.parametrize(
    "db_password",
    ["", DEV_DB_PASSWORD, "change-me"],
    ids=["missing", "dev-default", "env-example-placeholder"],
)
def test_public_profile_refuses_default_db_password(db_password):
    env = {"APP_PROFILE": "public", "SECRET_KEY": STRONG_SECRET, "DB_PASSWORD": db_password}
    with pytest.raises(SettingsError, match="DB_PASSWORD"):
        Settings.from_env(env)


def test_public_profile_refuses_an_unedited_env_example():
    example = dotenv_values(ENV_EXAMPLE)
    # DB_PASSWORD is commented out in the example; its documented value is the
    # same placeholder as the MariaDB passwords.
    env = {
        "APP_PROFILE": "public",
        "SECRET_KEY": example["SECRET_KEY"],
        "DB_PASSWORD": example["MARIADB_PASSWORD"],
    }
    with pytest.raises(SettingsError) as excinfo:
        Settings.from_env(env)
    assert "SECRET_KEY" in str(excinfo.value)
    assert "DB_PASSWORD" in str(excinfo.value)


def test_public_profile_reports_every_problem_at_once():
    with pytest.raises(SettingsError) as excinfo:
        Settings.from_env({"APP_PROFILE": "public"})
    assert "SECRET_KEY" in str(excinfo.value)
    assert "DB_PASSWORD" in str(excinfo.value)


def test_public_profile_accepts_strong_values():
    settings = Settings.from_env(
        {
            "APP_PROFILE": "public",
            "SECRET_KEY": STRONG_SECRET,
            "DB_PASSWORD": "db-password-from-secret-store",
            "SESSION_COOKIE_SECURE": "true",
            "ADMIN_EMAIL": "Owner@Example.com",
            "RATELIMIT_STORAGE_URI": "redis://redis:6379/0",
            "TRUSTED_PROXY_COUNT": "1",
        }
    )
    assert settings.is_public
    assert settings.session_cookie_secure is True
    assert settings.admin_email == "owner@example.com"
    assert settings.ratelimit_enabled is True
    assert settings.trusted_proxy_count == 1


PUBLIC_OK = {
    "APP_PROFILE": "public",
    "SECRET_KEY": STRONG_SECRET,
    "DB_PASSWORD": "db-password-from-secret-store",
    "ADMIN_EMAIL": "owner@example.com",
    "RATELIMIT_STORAGE_URI": "redis://redis:6379/0",
}


@pytest.mark.parametrize(
    ("override", "problem"),
    [
        ({"ADMIN_EMAIL": ""}, "ADMIN_EMAIL"),
        ({"ADMIN_EMAIL": "admin@admin.com"}, "ADMIN_EMAIL"),
        ({"RATELIMIT_STORAGE_URI": ""}, "RATELIMIT_STORAGE_URI"),
        ({"RATELIMIT_STORAGE_URI": "memory://"}, "RATELIMIT_STORAGE_URI"),
        ({"RATELIMIT_ENABLED": "false"}, "RATELIMIT_ENABLED"),
    ],
    ids=["no-admin", "default-admin", "no-storage", "memory-storage", "limiter-off"],
)
def test_public_profile_refuses_unsafe_admin_and_rate_limit_settings(override, problem):
    with pytest.raises(SettingsError, match=problem):
        Settings.from_env({**PUBLIC_OK, **override})


def test_local_profile_keeps_rate_limiting_off_unless_asked():
    assert Settings.from_env({}).ratelimit_enabled is False
    assert Settings.from_env({"RATELIMIT_ENABLED": "true"}).ratelimit_enabled is True


@pytest.mark.parametrize("value", ["one", "-1"])
def test_trusted_proxy_count_must_be_a_non_negative_integer(value):
    with pytest.raises(SettingsError, match="TRUSTED_PROXY_COUNT"):
        Settings.from_env({"TRUSTED_PROXY_COUNT": value})


def test_flask_config_keeps_the_original_session_settings():
    config = Settings.from_env({"SECRET_KEY": STRONG_SECRET}).flask_config()
    assert config == {
        "APP_PROFILE": "local",
        "SECRET_KEY": STRONG_SECRET,
        "PERMANENT_SESSION_LIFETIME": timedelta(days=7),
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": False,
        "ADMIN_EMAIL": "admin@admin.com",
        "RATELIMIT_ENABLED": False,
        "RATELIMIT_STORAGE_URI": "memory://",
        "AI_ENABLED": False,
        "AI_MONTHLY_BUDGET_USD": 0.0,
        "AI_MODEL": "claude-opus-5-5",
        "AI_INVITE_PEPPER": "dev-invite-pepper-change-me",
    }


def test_ai_is_off_by_default_and_needs_a_budget_when_on():
    assert Settings.from_env({"SECRET_KEY": STRONG_SECRET}).ai_enabled is False
    with pytest.raises(SettingsError, match="AI_MONTHLY_BUDGET_USD"):
        Settings.from_env({"SECRET_KEY": STRONG_SECRET, "AI_ENABLED": "true"})
    with pytest.raises(SettingsError, match="no price"):
        Settings.from_env({"AI_ENABLED": "true", "AI_MONTHLY_BUDGET_USD": "5", "AI_MODEL": "gpt-4o"})
    on = Settings.from_env({"AI_ENABLED": "true", "AI_MONTHLY_BUDGET_USD": "5"})
    assert on.ai_enabled and on.ai_monthly_budget_usd == 5.0 and on.ai_model == "claude-opus-5-5"


def test_public_ai_needs_a_real_invite_pepper():
    base = {**PUBLIC_ENV, "AI_ENABLED": "true", "AI_MONTHLY_BUDGET_USD": "10"}
    with pytest.raises(SettingsError, match="AI_INVITE_PEPPER"):
        Settings.from_env(base)
    with pytest.raises(SettingsError, match="AI_INVITE_PEPPER"):
        Settings.from_env({**base, "AI_INVITE_PEPPER": "short"})
    assert Settings.from_env({**base, "AI_INVITE_PEPPER": "p" * 40}).ai_invite_pepper == "p" * 40
