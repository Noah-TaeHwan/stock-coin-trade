"""Fetch daily bars from a registered source, check them, and store them.

    python -m marketdata.ingest --source synthetic --symbols 005930,KRW-BTC \
        --start 2025-01-02 --end 2026-09-24

The registry decides whether the source may run in the current APP_PROFILE.
A batch with quality errors is rejected as a whole and nothing is written;
warnings are stored in dq_results next to the run.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Engine

from marketdata import quality, registry, store
from marketdata.bars import checksum
from marketdata.sources.base import BarSource
from marketdata.sources.synthetic import SyntheticSource
from marketdata.sources.upbit import UpbitSource

SOURCES: dict[str, Callable[[], BarSource]] = {
    "synthetic": SyntheticSource,
    "upbit": UpbitSource,
}


@dataclass(frozen=True)
class RunResult:
    run_id: int
    status: str
    row_count: int
    checksum: str | None
    findings: list[quality.Finding]


def ingest(
    engine: Engine,
    source_id: str,
    symbols: Sequence[str],
    start: date,
    end: date,
    profile: str,
    reg: registry.Registry | None = None,
) -> RunResult:
    reg = reg or registry.load()
    reg.require(source_id, profile)  # raises SourceNotAllowed
    if source_id not in SOURCES:
        raise registry.RegistryError(f"no adapter for data source {source_id!r}")
    source = SOURCES[source_id]()

    bars, findings = [], []
    for symbol in symbols:
        symbol_bars = source.fetch_daily(symbol, start, end)
        findings.extend(quality.check(symbol_bars))
        bars.extend(symbol_bars)
    digest = checksum(bars)

    with engine.begin() as conn:
        run_id = store.start_run(conn, source_id, symbols, start, end)
        if quality.has_errors(findings):
            store.record_findings(conn, run_id, findings)
            store.finish_run(conn, run_id, "rejected", 0, digest, "quality errors; nothing written")
            return RunResult(run_id, "rejected", 0, digest, findings)
        written = store.upsert_bars(conn, bars)
        store.record_findings(conn, run_id, findings)
        store.finish_run(conn, run_id, "succeeded", written, digest)
    return RunResult(run_id, "succeeded", written, digest, findings)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", required=True)
    parser.add_argument("--symbols", required=True, help="comma-separated, e.g. 005930,KRW-BTC")
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument("--partitions-through", type=int, help="create yearly partitions up to this year first")
    args = parser.parse_args(argv)

    engine = store.engine_from_env()
    store.ensure_schema(engine)
    if args.partitions_through:
        created = store.ensure_partitions(engine, args.start.year, args.partitions_through)
        print(f"partitions created: {', '.join(created) or 'none'}")
    profile = os.environ.get("APP_PROFILE", "local").strip().lower()
    symbols = [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()]
    result = ingest(engine, args.source, symbols, args.start, args.end, profile)
    warnings = sum(1 for f in result.findings if f.severity == "warn")
    errors = sum(1 for f in result.findings if f.severity == "error")
    print(
        f"run {result.run_id}: {result.status}, {result.row_count} rows, "
        f"{errors} errors, {warnings} warnings, checksum {result.checksum}"
    )
    return 0 if result.status == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
