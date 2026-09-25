"""Technical indicators. A value exists only once its whole window is available.

The previous engine averaged partial windows from the first bar, so a
"50-day" average on day 3 was a 3-day average; these return NaN instead.
"""

from __future__ import annotations

import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=window).mean()


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """Cutler's RSI: simple averages of gains and losses over `window` changes."""
    change = close.diff()
    gain = change.clip(lower=0).rolling(window, min_periods=window).mean()
    loss = (-change.clip(upper=0)).rolling(window, min_periods=window).mean()
    value = 100 - 100 / (1 + gain / loss)
    return value.where(loss != 0, 100.0).where(gain.notna())


def momentum(close: pd.Series, lookback: int) -> pd.Series:
    return close / close.shift(lookback) - 1


def prior_max(series: pd.Series, window: int) -> pd.Series:
    """Highest value over the `window` bars before this one (excludes today)."""
    return series.shift(1).rolling(window, min_periods=window).max()


def prior_mean(series: pd.Series, window: int) -> pd.Series:
    return series.shift(1).rolling(window, min_periods=window).mean()
