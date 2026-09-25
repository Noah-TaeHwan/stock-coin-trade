"""Long-only strategies. Each returns the target position decided at each close.

A target of 1 means "hold after this close"; the engine fills the change at
the next bar's open, so a signal can never trade on the bar that produced it.
Comparisons with NaN (indicator warm-up) are False, so no signal fires
before every indicator it uses is fully formed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from quantlab import indicators as ind


@dataclass(frozen=True)
class StrategySpec:
    name: str
    label: str
    default_fast: int | None
    default_slow: int | None
    uses_fast_slow: bool
    rule: str


def _cross_above(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a > b) & (a.shift(1) <= b.shift(1))


def _cross_below(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a < b) & (a.shift(1) >= b.shift(1))


def _hold(buy: pd.Series, sell: pd.Series) -> pd.Series:
    """Enter on buy, leave on sell; ignore signals that do not change the state."""
    target = np.zeros(len(buy), dtype=int)
    holding = 0
    for index, (b, s) in enumerate(zip(buy.to_numpy(), sell.to_numpy(), strict=True)):
        if not holding and b:
            holding = 1
        elif holding and s:
            holding = 0
        target[index] = holding
    return pd.Series(target, index=buy.index, name="target")


def ma_cross(frame: pd.DataFrame, fast: int, slow: int) -> pd.Series:
    fast_ma, slow_ma = ind.sma(frame["close"], fast), ind.sma(frame["close"], slow)
    return _hold(_cross_above(fast_ma, slow_ma), _cross_below(fast_ma, slow_ma))


def pullback(frame: pd.DataFrame, fast: int, slow: int) -> pd.Series:
    close = frame["close"]
    fast_ma, slow_ma = ind.sma(close, fast), ind.sma(close, slow)
    buy = (fast_ma > slow_ma) & _cross_above(close, fast_ma)
    return _hold(buy, fast_ma < slow_ma)


def rsi_reversal(frame: pd.DataFrame, fast: int, slow: int) -> pd.Series:
    value = ind.rsi(frame["close"], 14)
    level_30, level_70 = pd.Series(30.0, index=value.index), pd.Series(70.0, index=value.index)
    return _hold(_cross_above(value, level_30), _cross_below(value, level_70))


def breakout(frame: pd.DataFrame, fast: int, slow: int) -> pd.Series:
    close, volume = frame["close"], frame["volume"]
    buy = (close > ind.prior_max(close, 20)) & (volume > ind.prior_mean(volume, 20))
    return _hold(buy, close < ind.sma(close, 10))


def momentum(frame: pd.DataFrame, fast: int, slow: int) -> pd.Series:
    close = frame["close"]
    mom, trend = ind.momentum(close, 60), ind.sma(close, 60)
    return _hold((mom > 0) & (close > trend), (mom <= 0) | (close < trend))


STRATEGIES: dict[str, tuple[StrategySpec, Callable[[pd.DataFrame, int, int], pd.Series]]] = {
    "ma2050": (
        StrategySpec(
            "ma2050", "이동평균 교차", 20, 50, True, "fast 이평이 slow 이평을 상향 돌파하면 매수, 하향 돌파하면 매도"
        ),
        ma_cross,
    ),
    "trend": (
        StrategySpec(
            "trend", "단기 추세추종", 5, 20, True, "fast 이평이 slow 이평을 상향 돌파하면 매수, 하향 돌파하면 매도"
        ),
        ma_cross,
    ),
    "pullback": (
        StrategySpec(
            "pullback",
            "상승추세 눌림목",
            20,
            60,
            True,
            "fast 이평 > slow 이평인 상태에서 종가가 fast 이평을 상향 돌파하면 매수, fast 이평 < slow 이평이면 매도",
        ),
        pullback,
    ),
    "rsi": (
        StrategySpec(
            "rsi", "RSI 과매도 반등", None, None, False, "RSI(14)가 30을 상향 돌파하면 매수, 70을 하향 돌파하면 매도"
        ),
        rsi_reversal,
    ),
    "breakout": (
        StrategySpec(
            "breakout",
            "거래량 20일 돌파",
            None,
            None,
            False,
            "종가가 직전 20일 최고가를 넘고 거래량이 직전 20일 평균을 넘으면 매수, 종가가 10일 이평 아래면 매도",
        ),
        breakout,
    ),
    "momentum": (
        StrategySpec(
            "momentum",
            "60일 모멘텀",
            None,
            None,
            False,
            "60일 수익률 > 0이고 종가 > 60일 이평이면 매수, 둘 중 하나가 깨지면 매도",
        ),
        momentum,
    ),
}


def resolve(strategy: str, fast: int | None = None, slow: int | None = None) -> tuple[StrategySpec, int, int]:
    """Validate the strategy and the fast/slow windows that will actually be used."""
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy {strategy!r}")
    spec, _ = STRATEGIES[strategy]
    if not spec.uses_fast_slow:
        return spec, 0, 0
    fast = spec.default_fast if fast is None else int(fast)
    slow = spec.default_slow if slow is None else int(slow)
    if not (2 <= fast < slow <= 250):
        raise ValueError("fast/slow must satisfy 2 <= fast < slow <= 250")
    return spec, fast, slow


def targets(frame: pd.DataFrame, strategy: str, fast: int | None = None, slow: int | None = None) -> pd.Series:
    spec, fast, slow = resolve(strategy, fast, slow)
    return STRATEGIES[spec.name][1](frame, fast, slow)
