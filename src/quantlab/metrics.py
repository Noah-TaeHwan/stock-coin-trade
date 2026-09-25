"""Performance metrics from a daily mark-to-market equity curve.

Returns are bar-to-bar changes of the equity curve, so Sharpe, Sortino and
volatility use every bar, not only the days a trade closed. Annualisation
uses the asset's calendar: 252 bars a year for KRX stocks, 365 for crypto.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from quantlab.engine import Result

# Below this per-bar deviation a ratio is dominated by float noise, so it is undefined.
_NEGLIGIBLE = 1e-12


def returns(equity: pd.Series) -> pd.Series:
    return equity.pct_change().dropna()


def max_drawdown(equity: pd.Series) -> float:
    return float((equity / equity.cummax() - 1).min())


def cagr(equity: pd.Series, periods_per_year: int) -> float:
    periods = len(equity) - 1
    if periods <= 0 or equity.iloc[0] <= 0 or equity.iloc[-1] <= 0:
        return 0.0
    return float((equity.iloc[-1] / equity.iloc[0]) ** (periods_per_year / periods) - 1)


def sharpe(rets: pd.Series, periods_per_year: int, risk_free_annual: float = 0.0) -> float | None:
    excess = rets - risk_free_annual / periods_per_year
    deviation = excess.std(ddof=1)
    if len(excess) < 2 or math.isnan(deviation) or deviation < _NEGLIGIBLE:
        return None
    return float(excess.mean() / deviation * math.sqrt(periods_per_year))


def sortino(rets: pd.Series, periods_per_year: int, risk_free_annual: float = 0.0) -> float | None:
    excess = rets - risk_free_annual / periods_per_year
    downside = math.sqrt(float((np.minimum(excess, 0) ** 2).mean())) if len(excess) else 0.0
    if len(excess) < 2 or downside < _NEGLIGIBLE:
        return None
    return float(excess.mean() / downside * math.sqrt(periods_per_year))


def summarize(result: Result, periods_per_year: int, risk_free_annual: float = 0.0) -> dict:
    equity = result.equity
    rets = returns(equity)
    mdd = max_drawdown(equity)
    growth = cagr(equity, periods_per_year)
    closed = [trade for trade in result.trades if trade.side == "SELL"]
    traded = sum(trade.price * trade.units for trade in result.trades)
    return {
        "bars": int(len(equity)),
        "totalReturn": float(equity.iloc[-1] / equity.iloc[0] - 1),
        "cagr": growth,
        "annualVolatility": float(rets.std(ddof=1) * math.sqrt(periods_per_year)) if len(rets) > 1 else None,
        "sharpe": sharpe(rets, periods_per_year, risk_free_annual),
        "sortino": sortino(rets, periods_per_year, risk_free_annual),
        "maxDrawdown": mdd,
        "calmar": growth / abs(mdd) if mdd < 0 else None,
        "exposure": float(result.position.mean()),
        "trades": len(result.trades),
        "closedTrades": len(closed),
        "winRate": (sum(1 for trade in closed if trade.pnl > 0) / len(closed)) if closed else None,
        "realizedPnl": float(sum(trade.pnl for trade in closed)),
        "turnover": float(traded / equity.mean()) if len(equity) else 0.0,
        "costs": float(sum(trade.costs for trade in result.trades)),
        "periodsPerYear": periods_per_year,
        "riskFreeAnnual": risk_free_annual,
    }
