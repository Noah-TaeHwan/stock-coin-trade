"""Tools the agent may call, and the backends that execute them.

All tools are read-only or idempotent: there is no order tool. Backtest
results go into the conversation's Ledger, which is what number receipts are
resolved against.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Protocol

from deskagent.numbers import Ledger

STRATEGIES = ["ma2050", "trend", "pullback", "rsi", "breakout", "momentum"]

TOOLS = [
    {
        "name": "list_sources",
        "description": (
            "List the market data sources, their licence status and whether this deployment uses them. "
            "Call this before answering questions about where the data comes from."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "run_backtest",
        "description": (
            "Backtest a long-only daily strategy on stored bars. Signals at the close, fills at the next open, "
            "costs in basis points. Returns metrics and a buy-and-hold benchmark with the same costs; ratios are "
            "fractions (0.1 = 10%). The result has a receiptId; cite numbers from it by path, e.g. metrics.sharpe, "
            "benchmark.totalReturn, parameters.fast, receipt.barCount. Same inputs give the same receiptId."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "KRX code such as 005930, or KRW-BTC"},
                "strategy": {"type": "string", "enum": STRATEGIES},
                "fast": {"type": "integer", "description": "fast window; only for ma2050, trend, pullback"},
                "slow": {"type": "integer", "description": "slow window; only for ma2050, trend, pullback"},
                "fee_bps": {"type": "number"},
                "slippage_bps": {"type": "number"},
                "start": {"type": "string", "description": "YYYY-MM-DD, inclusive"},
                "end": {"type": "string", "description": "YYYY-MM-DD, exclusive"},
            },
            "required": ["symbol", "strategy"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_backtest",
        "description": "Look up a stored backtest by its 64-character receiptId.",
        "input_schema": {
            "type": "object",
            "properties": {"receipt_id": {"type": "string"}},
            "required": ["receipt_id"],
            "additionalProperties": False,
        },
    },
]

TOOL_NAMES = {tool["name"] for tool in TOOLS}
RUN_KEYS = ("receiptId", "strategy", "parameters", "metrics", "benchmark", "receipt")


class ToolFailed(Exception):
    """A tool call the backend rejected; the message goes back to the model as an error result."""


class Backend(Protocol):
    def sources(self) -> dict: ...

    def run_backtest(self, payload: dict) -> dict: ...

    def get_backtest(self, receipt_id: str) -> dict | None: ...


def _payload(args: dict) -> dict:
    payload = {"symbol": args["symbol"], "strategy": args["strategy"]}
    for key in ("fast", "slow", "start", "end"):
        if args.get(key) is not None:
            payload[key] = args[key]
    if args.get("fee_bps") is not None:
        payload["feeRate"] = float(args["fee_bps"]) / 1e4
    if args.get("slippage_bps") is not None:
        payload["slippage"] = float(args["slippage_bps"]) / 1e4
    return payload


def execute(backend: Backend, ledger: Ledger, name: str, args: dict) -> str:
    """Run one tool call and return its JSON text; raise ToolFailed with a message for the model."""
    if name not in TOOL_NAMES:
        raise ToolFailed(f"unknown tool {name!r}")
    if not isinstance(args, dict):
        raise ToolFailed("tool input must be an object")
    if name == "list_sources":
        return json.dumps(backend.sources(), ensure_ascii=False)
    if name == "run_backtest":
        if not isinstance(args.get("symbol"), str) or args.get("strategy") not in STRATEGIES:
            raise ToolFailed("symbol (string) and strategy (one of " + ", ".join(STRATEGIES) + ") are required")
        run = backend.run_backtest(_payload(args))
    else:
        receipt_id = args.get("receipt_id")
        if not isinstance(receipt_id, str):
            raise ToolFailed("receipt_id (string) is required")
        run = backend.get_backtest(receipt_id)
        if run is None:
            raise ToolFailed(f"no stored backtest with receipt {receipt_id[:12]}")
    trimmed = {key: run[key] for key in RUN_KEYS if key in run}
    ledger.add_run(trimmed)
    return json.dumps(trimmed, ensure_ascii=False)


class LocalBackend:
    """Synthetic bars and an in-memory run store: evals and tests, no database."""

    def __init__(self, end: date = date(2025, 12, 31)):
        from marketdata.sources.synthetic import SyntheticSource

        self._source = SyntheticSource()
        self._end = end
        self._runs: dict[str, dict] = {}

    def sources(self) -> dict:
        from marketdata import registry

        reg = registry.load()
        return {
            "profile": "eval",
            "sources": [
                {"id": s.id, "status": s.status, "enabled": s.id == "synthetic", "attribution": s.attribution}
                for s in sorted(reg.sources.values(), key=lambda s: s.id)
            ],
        }

    def run_backtest(self, payload: dict) -> dict:
        from quantlab import engine
        from quantlab.backtest import backtest

        try:
            end = date.fromisoformat(payload.get("end") or self._end.isoformat())
            start = date.fromisoformat(payload.get("start") or f"{end.year - 3}-{end.month:02d}-{end.day:02d}")
            costs = engine.Costs(
                fee_bps=round(payload.get("feeRate", 0.00015) * 1e4, 6),
                slippage_bps=round(payload.get("slippage", 0.0005) * 1e4, 6),
            )
            bars = self._source.fetch_daily(payload["symbol"].upper(), start, end)
            result = backtest(bars, payload["strategy"], payload.get("fast"), payload.get("slow"), costs)
        except (ValueError, KeyError, TypeError) as exc:
            raise ToolFailed(str(exc)) from None
        run = {
            "receiptId": result["receipt"]["receiptId"],
            "strategy": result["strategy"],
            "parameters": result["receipt"]["params"],
            "metrics": result["metrics"],
            "benchmark": result["benchmark"],
            "receipt": result["receipt"],
        }
        self._runs[run["receiptId"]] = run
        return run

    def get_backtest(self, receipt_id: str) -> dict | None:
        return self._runs.get(receipt_id)
