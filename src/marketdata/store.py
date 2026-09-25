"""PostgreSQL storage for research bars: schema upgrades, partitions, runs.

All steps are idempotent so they can run on every deployment. The quant
schema itself is created by database/quant-postgres.sql.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import date

from sqlalchemy import Engine, create_engine, text

from marketdata.bars import Bar
from marketdata.quality import Finding

DEFAULT_URL = "postgresql+psycopg://quant:quant@postgres:5432/quant_research"
PARTITION_PREFIX = "market_data_"
DEFAULT_PARTITION = "market_data_default"

SCHEMA_STATEMENTS = (
    # Which source wrote each bar. Rows loaded by the SQL seed keep this label.
    "ALTER TABLE market_data ADD COLUMN IF NOT EXISTS source varchar(40) NOT NULL DEFAULT 'synthetic_sql'",
    # The primary key (symbol, trade_time) already serves symbol + time lookups in
    # both directions, so this index only cost writes.
    "DROP INDEX IF EXISTS idx_market_data_symbol_time",
    """CREATE TABLE IF NOT EXISTS ingestion_runs (
        run_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        source varchar(40) NOT NULL,
        symbols text[] NOT NULL,
        start_date date NOT NULL,
        end_date date NOT NULL,
        row_count integer NOT NULL DEFAULT 0,
        checksum char(64),
        status varchar(12) NOT NULL CHECK (status IN ('succeeded', 'rejected', 'failed')),
        message text,
        started_at timestamptz NOT NULL DEFAULT now(),
        finished_at timestamptz
    )""",
    """CREATE TABLE IF NOT EXISTS dq_results (
        dq_result_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        run_id bigint REFERENCES ingestion_runs(run_id) ON DELETE CASCADE,
        symbol varchar(20) NOT NULL,
        check_name varchar(30) NOT NULL,
        severity varchar(5) NOT NULL CHECK (severity IN ('error', 'warn')),
        trade_time timestamptz,
        detail text NOT NULL,
        checked_at timestamptz NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_dq_results_symbol ON dq_results(symbol, checked_at DESC)",
)


def engine_from_env() -> Engine:
    return create_engine(os.environ.get("QUANT_DATABASE_URL", DEFAULT_URL), pool_pre_ping=True)


def ensure_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        for statement in SCHEMA_STATEMENTS:
            conn.execute(text(statement))


def existing_partitions(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT c.relname FROM pg_inherits i "
                "JOIN pg_class c ON c.oid = i.inhrelid JOIN pg_class p ON p.oid = i.inhparent "
                "WHERE p.relname = 'market_data'"
            )
        )
        return {row[0] for row in rows}


def ensure_partitions(engine: Engine, first_year: int, through_year: int) -> list[str]:
    """Create yearly partitions first_year..through_year that do not exist yet.

    Rows already sitting in the DEFAULT partition for that year are moved into
    the new partition in the same transaction; PostgreSQL refuses to attach a
    partition whose range overlaps rows in DEFAULT. The new table is created
    with LIKE ... INCLUDING DEFAULTS INCLUDING CONSTRAINTS plus a CHECK matching
    the range, then attached (the approach the PostgreSQL 16 partitioning docs
    describe for adding partitions to a live table).
    """
    created = []
    present = existing_partitions(engine)
    for year in range(first_year, through_year + 1):
        name = f"{PARTITION_PREFIX}{year}"
        if name in present:
            continue
        lower, upper = date(year, 1, 1).isoformat(), date(year + 1, 1, 1).isoformat()
        with engine.begin() as conn:
            conn.execute(text(f"CREATE TABLE {name} (LIKE market_data INCLUDING DEFAULTS INCLUDING CONSTRAINTS)"))
            conn.execute(
                text(
                    f"ALTER TABLE {name} ADD CONSTRAINT {name}_range "
                    f"CHECK (trade_time >= '{lower}' AND trade_time < '{upper}')"
                )
            )
            conn.execute(
                text(
                    f"WITH moved AS (DELETE FROM {DEFAULT_PARTITION} "
                    f"WHERE trade_time >= '{lower}' AND trade_time < '{upper}' RETURNING *) "
                    f"INSERT INTO {name} SELECT * FROM moved"
                )
            )
            conn.execute(
                text(f"ALTER TABLE market_data ATTACH PARTITION {name} FOR VALUES FROM ('{lower}') TO ('{upper}')")
            )
            # The CHECK only made the attach skip its validation scan.
            conn.execute(text(f"ALTER TABLE {name} DROP CONSTRAINT {name}_range"))
        created.append(name)
    return created


def upsert_bars(conn, bars: Sequence[Bar]) -> int:
    if not bars:
        return 0
    conn.execute(
        text(
            "INSERT INTO market_data (symbol, trade_time, open, high, low, close, volume, adjusted_close, source) "
            "VALUES (:symbol, :ts, :open, :high, :low, :close, :volume, :close, :source) "
            "ON CONFLICT (symbol, trade_time) DO UPDATE SET open = EXCLUDED.open, high = EXCLUDED.high, "
            "low = EXCLUDED.low, close = EXCLUDED.close, volume = EXCLUDED.volume, "
            "adjusted_close = EXCLUDED.adjusted_close, source = EXCLUDED.source"
        ),
        [
            {
                "symbol": b.symbol,
                "ts": b.ts,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": int(round(b.volume)),
                "source": b.source,
            }
            for b in bars
        ],
    )
    return len(bars)


def start_run(conn, source: str, symbols: Sequence[str], start: date, end: date) -> int:
    return conn.execute(
        text(
            "INSERT INTO ingestion_runs (source, symbols, start_date, end_date, status) "
            "VALUES (:source, :symbols, :start, :end, 'failed') RETURNING run_id"
        ),
        {"source": source, "symbols": list(symbols), "start": start, "end": end},
    ).scalar_one()


def finish_run(conn, run_id: int, status: str, row_count: int, checksum: str | None, message: str = "") -> None:
    conn.execute(
        text(
            "UPDATE ingestion_runs SET status = :status, row_count = :rows, checksum = :checksum, "
            "message = :message, finished_at = now() WHERE run_id = :run_id"
        ),
        {"status": status, "rows": row_count, "checksum": checksum, "message": message, "run_id": run_id},
    )


def record_findings(conn, run_id: int | None, findings: Sequence[Finding]) -> None:
    if not findings:
        return
    conn.execute(
        text(
            "INSERT INTO dq_results (run_id, symbol, check_name, severity, trade_time, detail) "
            "VALUES (:run_id, :symbol, :check, :severity, :ts, :detail)"
        ),
        [
            {
                "run_id": run_id,
                "symbol": f.symbol,
                "check": f.check,
                "severity": f.severity,
                "ts": f.ts,
                "detail": f.detail,
            }
            for f in findings
        ],
    )


def load_bars(conn, symbol: str, start: date | None = None, end: date | None = None) -> list[Bar]:
    """Stored bars for one symbol. A time range lets PostgreSQL prune partitions."""
    clauses, params = ["symbol = :symbol"], {"symbol": symbol}
    if start:
        clauses.append("trade_time >= :start")
        params["start"] = start
    if end:
        clauses.append("trade_time < :end")
        params["end"] = end
    rows = conn.execute(
        text(
            "SELECT symbol, trade_time, open, high, low, close, volume, source FROM market_data "
            f"WHERE {' AND '.join(clauses)} ORDER BY trade_time"
        ),
        params,
    )
    return [Bar(r[0], r[1], float(r[2]), float(r[3]), float(r[4]), float(r[5]), float(r[6]), r[7]) for r in rows]
