"""Characterization tests for the create_app() split (docs/adr/0001-app-factory.md)."""

import os
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

import app as app_module
from settings import SettingsError

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "python-stock-backend"
ROUTE_SNAPSHOT = Path(__file__).with_name("snapshots") / "routes_local.txt"


def _route_lines(flask_app):
    return sorted(
        f"{' '.join(sorted(rule.methods - {'HEAD', 'OPTIONS'}))} {rule.rule} {rule.endpoint}"
        for rule in flask_app.url_map.iter_rules()
    )


def test_route_table_matches_snapshot(app):
    # The snapshot was generated from the factory and checked against the
    # original module-level app: same 122 rules and methods; only the 14
    # routes that lived on the app gained the "core." endpoint prefix.
    assert _route_lines(app) == ROUTE_SNAPSHOT.read_text(encoding="utf-8").splitlines()


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_session_config_comes_from_settings(app):
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert app.config["APP_PROFILE"] == "local"


def test_public_profile_with_default_secret_refuses_to_build_the_app(monkeypatch):
    monkeypatch.setenv("APP_PROFILE", "public")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(SettingsError):
        app_module.create_app()


def test_each_create_app_call_returns_an_independent_app(local_settings):
    first = app_module.create_app(local_settings)
    second = app_module.create_app(local_settings)
    assert first is not second
    assert _route_lines(first) == _route_lines(second)


def test_import_and_create_app_do_not_touch_the_database_or_start_threads():
    """Run in a fresh interpreter so module import side effects are observable.

    DB_PORT points at a closed local port: any connection attempt raises. The
    pre-factory app.py created tables and seeded data at import time, and
    started an APScheduler thread, so it failed this check.
    """
    script = textwrap.dedent(
        """
        import threading
        import app
        flask_app = app.create_app()
        flask_app.test_client().get("/health")
        names = sorted(t.name for t in threading.enumerate())
        assert names == ["MainThread"], names
        print("ok")
        """
    )
    env = {
        **os.environ,
        "APP_PROFILE": "local",
        "DB_HOST": "127.0.0.1",
        "DB_PORT": "9",
        "PYTHONPATH": str(BACKEND_DIR),
    }
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip().endswith("ok")


@pytest.mark.parametrize(
    ("command", "target", "message"),
    [
        ("init-db", "bootstrap.create_tables", "init-db: tables are ready"),
        ("seed-demo", "bootstrap.seed_demo_data", "seed-demo: done"),
    ],
)
def test_cli_commands_call_the_bootstrap_steps(app, command, target, message):
    with patch(target) as step:
        result = app.test_cli_runner().invoke(args=[command])
    assert result.exit_code == 0, result.output
    assert message in result.output
    step.assert_called_once_with()
