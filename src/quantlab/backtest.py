"""One call from bars to a complete, receipted backtest result."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict

from marketdata.bars import Bar
from marketdata.calendars import CRYPTO, calendar_for, periods_per_year
from quantlab import engine, metrics, receipts, strategies
from quantlab.frame import bars_to_frame


def config_for(symbol: str, costs: engine.Costs, initial_capital: float, risk_free_annual: float = 0.0):
    calendar = calendar_for(symbol)
    return engine.Config(
        initial_capital=initial_capital,
        costs=costs,
        fractional=calendar == CRYPTO,
        periods_per_year=periods_per_year(calendar),
        risk_free_annual=risk_free_annual,
    )


def backtest(
    bars: Sequence[Bar],
    strategy: str,
    fast: int | None = None,
    slow: int | None = None,
    costs: engine.Costs | None = None,
    initial_capital: float = 10_000_000.0,
    risk_free_annual: float = 0.0,
) -> dict:
    if len(bars) < 2:
        raise ValueError("at least two bars are needed")
    symbols = {bar.symbol for bar in bars}
    if len(symbols) != 1:
        raise ValueError("bars must belong to one symbol")
    symbol = symbols.pop()
    costs = costs or engine.Costs()
    spec, fast, slow = strategies.resolve(strategy, fast, slow)
    config = config_for(symbol, costs, initial_capital, risk_free_annual)

    frame = bars_to_frame(bars)
    target = strategies.targets(frame, spec.name, fast or None, slow or None)
    result = engine.run(frame, target, config)
    benchmark = engine.buy_and_hold(frame, config)

    params = {
        "symbol": symbol,
        "strategy": spec.name,
        "fast": fast or None,
        "slow": slow or None,
        "costs": asdict(costs),
        "initialCapital": initial_capital,
        "riskFreeAnnual": risk_free_annual,
        "fractional": config.fractional,
        "periodsPerYear": config.periods_per_year,
    }
    return {
        "strategy": {"name": spec.name, "label": spec.label, "rule": spec.rule},
        "metrics": metrics.summarize(result, config.periods_per_year, risk_free_annual),
        "benchmark": metrics.summarize(benchmark, config.periods_per_year, risk_free_annual),
        "equity": result.equity,
        "benchmarkEquity": benchmark.equity,
        "position": result.position,
        "trades": result.trades,
        "receipt": receipts.make(bars, params),
    }
