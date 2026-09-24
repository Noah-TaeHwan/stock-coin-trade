"""bootstrap.create_tables()/seed_demo_data() against a real MariaDB.

Expects database/db.sql to be loaded first, as docker-entrypoint-initdb.d
does in Compose and the CI workflow does explicitly.
"""

import pytest
from sqlalchemy import inspect, text

import bootstrap
import db

pytestmark = pytest.mark.integration

# Tables the instructor modules create themselves instead of database/db.sql.
MODULE_MANAGED_TABLES = {
    "hts_watch_memo",
    "alternative_position",
    "alternative_order",
    "kis_practice_account",
    "kis_practice_position",
    "kis_practice_order",
    "system_error_log",
    "api_usage_log",
}


def _member_count() -> int:
    with db.engine.connect() as conn:
        return conn.execute(text("SELECT COUNT(*) FROM member")).scalar_one()


def test_create_tables_is_idempotent():
    bootstrap.create_tables()
    bootstrap.create_tables()
    tables = set(inspect(db.engine).get_table_names())
    assert MODULE_MANAGED_TABLES.issubset(tables), MODULE_MANAGED_TABLES - tables
    columns = {column["name"] for column in inspect(db.engine).get_columns("alternative_order")}
    assert "source" in columns  # added by ALTER TABLE in alternatives.ensure_tables()


def test_seed_demo_data_is_idempotent():
    bootstrap.create_tables()
    bootstrap.seed_demo_data()
    first = _member_count()
    bootstrap.seed_demo_data()
    assert _member_count() == first
    assert first >= 50  # 30 sample investors + 20 market-bot accounts
