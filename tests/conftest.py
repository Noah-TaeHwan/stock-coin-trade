"""Shared pytest fixtures (Flask testing pattern: app factory + test client)."""

import pytest

from settings import Settings

# A syntactically valid public-profile secret for tests only.
TEST_SECRET_KEY = "test-secret-key-0123456789abcdef0123456789"


@pytest.fixture
def local_settings() -> Settings:
    return Settings.from_env({"APP_PROFILE": "local", "SECRET_KEY": TEST_SECRET_KEY})


@pytest.fixture
def app(local_settings):
    import app as app_module

    flask_app = app_module.create_app(local_settings)
    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def pytest_collection_modifyitems(config, items):
    """Skip @pytest.mark.integration tests unless real databases are configured.

    CI sets RUN_INTEGRATION=1 next to the MariaDB/PostgreSQL service containers
    (.github/workflows/ci.yml). Locally, export the same DB_* and
    QUANT_DATABASE_URL variables and RUN_INTEGRATION=1.
    """
    import os

    # @pytest.mark.network tests call real third-party APIs; CI never runs them.
    if os.environ.get("RUN_NETWORK") != "1":
        skip_network = pytest.mark.skip(reason="network test: set RUN_NETWORK=1 to call the real API")
        for item in items:
            if "network" in item.keywords:
                item.add_marker(skip_network)
    if os.environ.get("RUN_INTEGRATION") == "1":
        return
    skip = pytest.mark.skip(reason="integration test: set RUN_INTEGRATION=1 with DB_* and QUANT_DATABASE_URL")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)
