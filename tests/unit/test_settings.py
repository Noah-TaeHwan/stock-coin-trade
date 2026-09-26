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
    "SESSION_COOKIE_SECURE": "true",
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
    "SESSION_COOKIE_SECURE": "true",
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
        "JEV_ENABLED": False,
        "JEV_MONTHLY_BUDGET_USD": 0.0,
        "SIGNUP_ENABLED": True,
        "PUBLIC_BASE_URL": "",
        "SMTP_HOST": "",
        "SMTP_PORT": 587,
        "SMTP_USER": "",
        "SMTP_PASSWORD": "",
        "SMTP_FROM": "",
        "SMTP_STARTTLS": True,
        "EMAIL_VERIFICATION": False,
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


def test_dart_key_is_read_trimmed_and_kept_out_of_flask_config():
    settings = Settings.from_env({"DART_API_KEY": "  dart-test  "})
    assert settings.dart_api_key == "dart-test"
    assert "dart-test" not in str(settings.flask_config())
    assert Settings.from_env({}).dart_api_key == ""


def test_public_profile_refuses_insecure_session_cookie():
    with pytest.raises(SettingsError, match="SESSION_COOKIE_SECURE"):
        Settings.from_env({**PUBLIC_OK, "SESSION_COOKIE_SECURE": "false"})


def test_public_signup_opens_only_when_asked_and_mail_is_configured():
    assert Settings.from_env(PUBLIC_OK).signup_enabled is False
    ready = {
        **PUBLIC_OK,
        "SMTP_HOST": "smtp.example.test",
        "SMTP_FROM": "no-reply@example.test",
        "PUBLIC_BASE_URL": "https://desk.example.test/",
    }
    # 메일 설정만으로는 열리지 않는다(인증 흐름이 준비된 배포에서 사람이 연다).
    assert Settings.from_env(ready).signup_enabled is False
    settings = Settings.from_env({**ready, "SIGNUP_ENABLED": "true"})
    assert settings.signup_enabled is True
    assert settings.public_base_url == "https://desk.example.test"


def test_public_refuses_forcing_signup_open_without_mail():
    with pytest.raises(SettingsError, match="SIGNUP_ENABLED"):
        Settings.from_env({**PUBLIC_OK, "SIGNUP_ENABLED": "true"})


def test_local_signup_is_open_by_default():
    assert Settings.from_env({"APP_PROFILE": "local"}).signup_enabled is True


def test_email_verification_is_on_for_public_and_for_local_with_mail():
    assert Settings.from_env({}).email_verification is False
    local_mail = {
        "SMTP_HOST": "mailpit",
        "SMTP_PORT": "1025",
        "SMTP_STARTTLS": "false",
        "SMTP_FROM": "no-reply@stockdesk.local",
        "PUBLIC_BASE_URL": "http://127.0.0.1:3334",
    }
    settings = Settings.from_env(local_mail)
    assert settings.email_verification is True and settings.smtp_port == 1025 and settings.smtp_starttls is False
    assert Settings.from_env(PUBLIC_OK).email_verification is True


def test_local_mail_needs_a_base_url_for_links():
    with pytest.raises(SettingsError, match="PUBLIC_BASE_URL"):
        Settings.from_env({"SMTP_HOST": "mailpit", "SMTP_FROM": "no-reply@stockdesk.local"})


def test_public_mail_requires_starttls_and_a_sender():
    mail = {**PUBLIC_OK, "SMTP_HOST": "smtp.example.test", "PUBLIC_BASE_URL": "https://desk.example.test"}
    with pytest.raises(SettingsError, match="SMTP_STARTTLS"):
        Settings.from_env({**mail, "SMTP_FROM": "no-reply@example.test", "SMTP_STARTTLS": "false"})
    with pytest.raises(SettingsError, match="SMTP_FROM"):
        Settings.from_env(mail)
    assert Settings.from_env({**mail, "SMTP_FROM": "no-reply@example.test"}).smtp_starttls is True


def test_smtp_password_is_kept_out_of_the_settings_repr():
    settings = Settings.from_env(
        {
            "SMTP_HOST": "mailpit",
            "SMTP_PASSWORD": "smtp-secret-value",
            "SMTP_FROM": "a@b.test",
            "PUBLIC_BASE_URL": "http://127.0.0.1:3334",
        }
    )
    assert "smtp-secret-value" not in repr(settings)
