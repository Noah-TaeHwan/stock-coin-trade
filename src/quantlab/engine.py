"""Execution and daily mark-to-market for one long-only position.

Timeline for bar t:
1. At the open of t, fill the target decided at the close of t-1.
   Buys pay open * (1 + slippage) plus the fee; sells receive
   open * (1 - slippage) minus the fee and the sell tax.
2. At the close of t, value the account: cash + units * close.
3. The strategy's target at the close of t is filled at the open of t+1.
   The last bar's target is never filled (there is no next open).

Sizing is all-in: a buy spends the available cash (whole units for KRX
stocks, 8 decimal places for crypto). Costs are in basis points per side.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

BPS = 1e-4


@dataclass(frozen=True)
class Costs:
    fee_bps: float = 1.5
    slippage_bps: float = 5.0
    # Securities transaction tax on KRX sells. Left at 0 until the current rate
    # and its effective date are confirmed from an official source.
    sell_tax_bps: float = 0.0

    def __post_init__(self):
        for name, value in asdict(self).items():
            if not (0 <= value <= 500):
                raise ValueError(f"{name} must be between 0 and 500 bps")


@dataclass(frozen=True)
class Config:
    initial_capital: float = 10_000_000.0
    costs: Costs = field(default_factory=Costs)
    fractional: bool = False  # True for crypto
    periods_per_year: int = 252
    risk_free_annual: float = 0.0


@dataclass(frozen=True)
class Trade:
    ts: pd.Timestamp
    side: str
    price: float
    units: float
    costs: float
    pnl: float  # realised, net of all costs; 0 for buys


@dataclass(frozen=True)
class Result:
    equity: pd.Series
    position: pd.Series
    trades: list[Trade]


def _units(cash: float, price: float, fee: float, fractional: bool) -> float:
    affordable = cash / (price * (1 + fee))
    return math.floor(affordable * 1e8) / 1e8 if fractional else float(math.floor(affordable))


def run(frame: pd.DataFrame, targets: pd.Series, config: Config, initial_target: int = 0) -> Result:
    """Simulate `targets` (decided at each close) on `frame`.

    `initial_target` is the target in force before the first bar; 1 buys at
    the first open (used for the buy-and-hold benchmark).
    """
    if not frame.index.equals(targets.index):
        raise ValueError("targets must share the frame's index")
    fee, slip, tax = config.costs.fee_bps * BPS, config.costs.slippage_bps * BPS, config.costs.sell_tax_bps * BPS
    opens, closes = frame["open"].to_numpy(), frame["close"].to_numpy()
    wanted = targets.to_numpy()

    cash, units, entry_cost = float(config.initial_capital), 0.0, 0.0
    pending = initial_target
    equity = np.empty(len(frame))
    position = np.zeros(len(frame), dtype=int)
    trades: list[Trade] = []
    for t, ts in enumerate(frame.index):
        if pending == 1 and units == 0:
            price = opens[t] * (1 + slip)
            size = _units(cash, price, fee, config.fractional)
            if size > 0:
                notional = size * price
                charge = notional * fee
                cash -= notional + charge
                units, entry_cost = size, notional + charge
                trades.append(Trade(ts, "BUY", price, size, charge, 0.0))
        elif pending == 0 and units > 0:
            price = opens[t] * (1 - slip)
            proceeds = units * price
            charge = proceeds * (fee + tax)
            cash += proceeds - charge
            trades.append(Trade(ts, "SELL", price, units, charge, proceeds - charge - entry_cost))
            units, entry_cost = 0.0, 0.0
        equity[t] = cash + units * closes[t]
        position[t] = 1 if units > 0 else 0
        pending = int(wanted[t])
    return Result(
        pd.Series(equity, index=frame.index, name="equity"),
        pd.Series(position, index=frame.index, name="position"),
        trades,
    )


def buy_and_hold(frame: pd.DataFrame, config: Config) -> Result:
    """Benchmark: buy at the first open with the same costs, never sell."""
    return run(frame, pd.Series(1, index=frame.index), config, initial_target=1)
