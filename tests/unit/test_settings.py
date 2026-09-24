from datetime import timedelta
from pathlib import Path

import pytest
from dotenv import dotenv_values

from settings import DEV_DB_PASSWORD, DEV_SECRET_KEY, Settings, SettingsError

STRONG_SECRET = "s" * 32
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
        }
    )
    assert settings.is_public
    assert settings.session_cookie_secure is True


def test_flask_config_matches_the_original_session_settings():
    config = Settings.from_env({"SECRET_KEY": STRONG_SECRET}).flask_config()
    assert config == {
        "APP_PROFILE": "local",
        "SECRET_KEY": STRONG_SECRET,
        "PERMANENT_SESSION_LIFETIME": timedelta(days=7),
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": False,
    }
