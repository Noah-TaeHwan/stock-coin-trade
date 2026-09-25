"""Walk-forward evaluation: pick parameters in-sample, judge them out-of-sample.

For each fold, every candidate (fast, slow) pair is backtested on the
training window and the best in-sample Sharpe wins; that pair is then run on
the following test window, which the choice never saw. Test windows do not
overlap, so their results describe performance on unseen data. Each test run
starts from the full warm-up history (indicators need past bars) but only
the test window's bars count, and a position the test window inherits from
the last training close is entered at the first test open.

The stitched curve chains each test window's bar-to-bar returns, so the one
return between two windows (last close of one, first close of the next) is
not included.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import pandas as pd

from marketdata.bars import Bar
from quantlab import engine, metrics, strategies
from quantlab.backtest import config_for
from quantlab.frame import bars_to_frame


@dataclass(frozen=True)
class Fold:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    fast: int
    slow: int
    in_sample_sharpe: float | None
    out_of_sample: dict


def _sharpe_key(value: float | None) -> float:
    return float("-inf") if value is None else value


def walk_forward(
    bars: Sequence[Bar],
    strategy: str,
    grid: Iterable[tuple[int, int]],
    train_bars: int,
    test_bars: int,
    costs: engine.Costs | None = None,
    initial_capital: float = 10_000_000.0,
) -> tuple[list[Fold], pd.Series]:
    """Folds and the stitched out-of-sample equity curve (starting at 1.0).

    Each window starts from `initial_capital`; with whole-share sizing it must
    buy at least one share, so it cannot be a unit amount.
    """
    frame = bars_to_frame(bars)
    symbol = bars[0].symbol
    config = config_for(symbol, costs or engine.Costs(), initial_capital)
    candidates = [strategies.resolve(strategy, fast, slow)[1:] for fast, slow in grid]
    folds, pieces = [], []
    start = 0
    while start + train_bars + test_bars <= len(frame):
        train = frame.iloc[start : start + train_bars]
        best, best_sharpe = candidates[0], None
        for fast, slow in candidates:
            result = engine.run(train, strategies.targets(train, strategy, fast, slow), config)
            score = metrics.sharpe(metrics.returns(result.equity), config.periods_per_year)
            if best_sharpe is None or _sharpe_key(score) > _sharpe_key(best_sharpe):
                best, best_sharpe = (fast, slow), score
        history = frame.iloc[: start + train_bars + test_bars]
        target = strategies.targets(history, strategy, *best)
        test_index = frame.index[start + train_bars : start + train_bars + test_bars]
        # The target decided at the last training close is filled at the first test open.
        carried = int(target.iloc[start + train_bars - 1])
        test_result = engine.run(history.loc[test_index], target.loc[test_index], config, initial_target=carried)
        folds.append(
            Fold(
                train.index[0],
                train.index[-1],
                test_index[0],
                test_index[-1],
                best[0],
                best[1],
                best_sharpe,
                metrics.summarize(test_result, config.periods_per_year),
            )
        )
        pieces.append(metrics.returns(test_result.equity))
        start += test_bars
    stitched = (1 + pd.concat(pieces)).cumprod() if pieces else pd.Series(dtype=float)
    return folds, stitched
