"""Research data store on PostgreSQL 16: schema, partitions, ingestion, quality API."""

from datetime import date

import pytest
from sqlalchemy import text

from marketdata import ingest, registry, store

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def engine():
    engine = store.engine_from_env()
    store.ensure_schema(engine)
    yield engine
    engine.dispose()


def test_schema_upgrade_is_idempotent(engine):
    store.ensure_schema(engine)
    with engine.connect() as conn:
        columns = {
            row[0]
            for row in conn.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = 'market_data'")
            )
        }
        indexes = {
            row[0] for row in conn.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'market_data'"))
        }
    assert "source" in columns
    assert "idx_market_data_symbol_time" not in indexes


def test_new_partition_takes_over_rows_from_the_default_partition(engine):
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO market_data (symbol, trade_time, open, high, low, close, volume, adjusted_close) "
                "VALUES ('PART-TEST', '2029-03-02', 1, 1, 1, 1, 1, 1) ON CONFLICT DO NOTHING"
            )
        )
    try:
        created = store.ensure_partitions(engine, 2029, 2029)
        assert created == ["market_data_2029"]
        assert store.ensure_partitions(engine, 2029, 2029) == []
        with engine.connect() as conn:
            where = conn.execute(
                text("SELECT tableoid::regclass::text FROM market_data WHERE symbol = 'PART-TEST'")
            ).scalar_one()
            in_default = conn.execute(
                text("SELECT count(*) FROM market_data_default WHERE symbol = 'PART-TEST'")
            ).scalar_one()
        assert (where, in_default) == ("market_data_2029", 0)
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM market_data WHERE symbol = 'PART-TEST'"))
            conn.execute(text("DROP TABLE IF EXISTS market_data_2029"))


def test_range_query_prunes_other_year_partitions(engine):
    store.ensure_partitions(engine, 2025, 2026)
    with engine.connect() as conn:
        plan = "\n".join(
            row[0]
            for row in conn.execute(
                text(
                    "EXPLAIN SELECT * FROM market_data WHERE symbol = '005930' "
                    "AND trade_time >= '2026-01-01' AND trade_time < '2026-07-01'"
                )
            )
        )
    assert "market_data_2026" in plan
    assert "market_data_2025" not in plan


def test_synthetic_ingestion_is_idempotent_and_recorded(engine):
    args = (engine, "synthetic", ["SYN-TEST"], date(2026, 1, 1), date(2026, 3, 31), "local")
    first = ingest.ingest(*args)
    second = ingest.ingest(*args)
    try:
        assert first.status == second.status == "succeeded"
        assert first.checksum == second.checksum and first.row_count == second.row_count == 90
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT count(*), min(source), max(source) FROM market_data WHERE symbol = 'SYN-TEST'")
            ).one()
            runs = conn.execute(
                text("SELECT status, row_count FROM ingestion_runs WHERE run_id IN (:a, :b)"),
                {"a": first.run_id, "b": second.run_id},
            ).all()
        assert tuple(rows) == (90, "synthetic", "synthetic")
        assert sorted(runs) == [("succeeded", 90), ("succeeded", 90)]
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM market_data WHERE symbol = 'SYN-TEST'"))


def test_disabled_source_is_refused_before_anything_is_written(engine, tmp_path):
    path = tmp_path / "sources.toml"
    path.write_text(
        '[sources.synthetic]\nname="s"\nkind="synthetic"\nstatus="verified"\ncommercial_use="allowed"\n'
        'redistribution="allowed"\nmodification="allowed"\nattribution="s"\n'
        "enabled = { local = true, public = false }\n"
    )
    with pytest.raises(registry.SourceNotAllowed):
        ingest.ingest(
            engine, "synthetic", ["SYN-TEST"], date(2026, 1, 1), date(2026, 1, 5), "public", reg=registry.load(path)
        )


def test_a_batch_with_quality_errors_is_rejected_whole(engine, monkeypatch):
    from dataclasses import replace

    real = ingest.SOURCES["synthetic"]

    class Broken:
        id = "synthetic"

        def fetch_daily(self, symbol, start, end):
            bars = real().fetch_daily(symbol, start, end)
            return bars[:-1] + [replace(bars[-1], high=bars[-1].low - 1)]

    monkeypatch.setitem(ingest.SOURCES, "synthetic", Broken)
    result = ingest.ingest(engine, "synthetic", ["SYN-BAD"], date(2026, 1, 1), date(2026, 1, 10), "local")
    with engine.connect() as conn:
        stored = conn.execute(text("SELECT count(*) FROM market_data WHERE symbol = 'SYN-BAD'")).scalar_one()
        errors = conn.execute(
            text("SELECT count(*) FROM dq_results WHERE run_id = :id AND severity = 'error'"), {"id": result.run_id}
        ).scalar_one()
    assert (result.status, stored, errors) == ("rejected", 0, 1)


def test_data_quality_endpoint_reports_the_last_ingestion(engine, client):
    ingest.ingest(engine, "synthetic", ["SYN-API"], date(2026, 1, 1), date(2026, 1, 31), "local")
    try:
        body = client.get("/api/quant/data-quality?symbol=SYN-API&days=3650").get_json()
        assert body["bars"] == 31 and body["sources"] == ["synthetic"] and body["errors"] == 0
        assert body["lastIngestion"]["status"] == "succeeded"
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM market_data WHERE symbol = 'SYN-API'"))
