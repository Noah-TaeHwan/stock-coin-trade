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
    order_columns = {column["name"] for column in inspect(db.engine).get_columns("stock_order")}
    assert "simulated" in order_columns  # added by ALTER TABLE in stock_trading.ensure_stock_order_columns()


def test_seed_demo_data_is_idempotent():
    bootstrap.create_tables()
    bootstrap.seed_demo_data()
    first = _member_count()
    bootstrap.seed_demo_data()
    assert _member_count() == first
    assert first >= 50  # 30 sample investors + 20 market-bot accounts


def test_dart_disclosures_table_is_idempotent_and_keeps_the_first_row():
    from datetime import date, datetime

    import dart_radar

    bootstrap.create_tables()
    bootstrap.create_tables()
    row = {
        "rcept_no": "20260922900001",
        "rcept_dt": date(2026, 9, 23),
        "corp_code": "00000001",
        "corp_name": "테스트",
        "stock_code": "123456",
        "corp_cls": "K",
        "report_nm": "주권매매거래정지 (상장폐지 사유발생)",
        "rm": "코",
        "flr_nm": "테스트",
        "first_seen_at": datetime(2026, 9, 23, 0, 5),
        "kind": "trading_halt",
        "corrected": False,
        "risk": True,
        "kind_prob": None,
        "risk_prob": None,
        "judged_by": "rules",
        "model": None,
        "judged_at": datetime(2026, 9, 23, 0, 5),
    }
    with db.engine.begin() as conn:
        conn.execute(text("DELETE FROM dart_disclosures WHERE rcept_no = :n"), {"n": row["rcept_no"]})
    dart_radar.save([row])
    dart_radar.save([{**row, "kind": "other"}])  # 이미 있는 번호는 덮어쓰지 않는다
    assert dart_radar.known_numbers(["20260922900001", "X"]) == {"20260922900001"}
    got = dart_radar.query(date(2026, 9, 23), date(2026, 9, 23), ("123456",), None, True, 10)
    assert [(r["rcept_no"], r["kind"]) for r in got] == [("20260922900001", "trading_halt")]
