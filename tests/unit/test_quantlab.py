"""quantlab: golden values, independent metric checks, properties, old-engine regressions."""

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from marketdata.bars import Bar
from marketdata.sources.synthetic import SyntheticSource
from quantlab import engine, indicators, metrics, strategies
from quantlab.backtest import backtest
from quantlab.frame import bars_to_frame
from quantlab.validation import walk_forward

DAYS = pd.date_range("2025-01-06", periods=8, freq="B", tz="UTC")


def _frame(opens, closes):
    opens, closes = np.asarray(opens, float), np.asarray(closes, float)
    return pd.DataFrame(
        {
            "open": opens,
            "high": np.maximum(opens, closes) + 1,
            "low": np.minimum(opens, closes) - 1,
            "close": closes,
            "volume": 1000.0,
        },
        index=pd.date_range("2025-01-06", periods=len(opens), freq="B", tz="UTC"),
    )


# ── Golden: 8 bars computed by hand ──────────────────────────────────────────
#
# capital 1000, fee 10 bps, slippage 0, tax 0, whole units.
# targets decided at the close: [0, 1, 1, 0, 0, 1, 1, 1]
# bar 2 open 100: buy floor(1000 / (100 * 1.001)) = 9 units, cost 900 + 0.9 fee -> cash 99.1
# bar 4 open 120: sell 9 * 120 = 1080, fee 1.08 -> cash 1178.02, pnl 1080 - 1.08 - 900.9 = 178.02
# bar 6 open 110: buy floor(1178.02 / 110.11) = 10 units, cost 1100 + 1.1 -> cash 76.92
# the last target (bar 7) is never filled; the position stays open.
GOLDEN_OPENS = [100, 100, 100, 110, 120, 115, 110, 105]
GOLDEN_CLOSES = [100, 101, 110, 118, 116, 112, 108, 104]
GOLDEN_TARGETS = [0, 1, 1, 0, 0, 1, 1, 1]
GOLDEN_EQUITY = [1000.0, 1000.0, 99.1 + 9 * 110, 99.1 + 9 * 118, 1178.02, 1178.02, 76.92 + 10 * 108, 76.92 + 10 * 104]


def _golden():
    frame = _frame(GOLDEN_OPENS, GOLDEN_CLOSES)
    config = engine.Config(initial_capital=1000, costs=engine.Costs(fee_bps=10, slippage_bps=0, sell_tax_bps=0))
    return engine.run(frame, pd.Series(GOLDEN_TARGETS, index=frame.index), config)


def test_golden_equity_curve():
    assert _golden().equity.round(6).tolist() == pytest.approx(GOLDEN_EQUITY)


def test_golden_trades_fill_at_the_next_open():
    trades = _golden().trades
    assert [(t.ts.day, t.side, t.price, t.units) for t in trades] == [
        (DAYS[2].day, "BUY", 100.0, 9.0),
        (DAYS[4].day, "SELL", 120.0, 9.0),
        (DAYS[6].day, "BUY", 110.0, 10.0),
    ]
    assert trades[1].pnl == pytest.approx(178.02)
    assert _golden().position.tolist() == [0, 0, 1, 1, 0, 0, 1, 1]


def test_golden_round_trip_charges_slippage_both_ways_and_tax_on_the_sell():
    # capital 1000, fee 0, slippage 100 bps, sell tax 20 bps.
    # buy at open 100 -> 101, floor(1000 / 101) = 9 units, cash 91
    # sell at open 110 -> 108.9, proceeds 980.1, tax 1.9602 -> cash 1069.1398, pnl 69.1398
    frame = _frame([100, 100, 110], [100, 105, 110])
    config = engine.Config(initial_capital=1000, costs=engine.Costs(fee_bps=0, slippage_bps=100, sell_tax_bps=20))
    result = engine.run(frame, pd.Series([1, 0, 0], index=frame.index), config)
    buy, sell = result.trades
    assert (buy.price, buy.units, sell.price) == pytest.approx((101.0, 9.0, 108.9))
    assert sell.costs == pytest.approx(1.9602)
    assert sell.pnl == pytest.approx(69.1398)
    assert result.equity.tolist() == pytest.approx([1000.0, 91 + 9 * 105, 1069.1398])


# ── Metrics against independent textbook formulas ───────────────────────────


def test_metrics_on_a_hand_checked_curve():
    equity = pd.Series([100.0, 110.0, 99.0, 108.9])
    r = np.array([0.1, -0.1, 0.1])
    assert metrics.max_drawdown(equity) == pytest.approx(99 / 110 - 1)
    assert metrics.sharpe(pd.Series(r), 252) == pytest.approx(r.mean() / r.std(ddof=1) * math.sqrt(252))
    assert metrics.cagr(equity, 252) == pytest.approx(1.089 ** (252 / 3) - 1)


@given(st.lists(st.floats(-0.08, 0.08), min_size=30, max_size=300), st.sampled_from([252, 365]))
@settings(max_examples=60, deadline=None)
def test_metrics_match_a_separate_reference_implementation(daily, ppy):
    rets = np.asarray(daily)
    equity = pd.Series(1000 * np.cumprod(np.concatenate([[1.0], 1 + rets])))
    got = metrics.returns(equity).to_numpy()
    assert got == pytest.approx(rets, abs=1e-9)
    peak = np.maximum.accumulate(equity.to_numpy())
    assert metrics.max_drawdown(equity) == pytest.approx((equity.to_numpy() / peak - 1).min())
    std = rets.std(ddof=1)
    got_sharpe = metrics.sharpe(pd.Series(rets), ppy)
    if std < 1e-12:
        assert got_sharpe is None
    else:
        assert got_sharpe == pytest.approx(rets.mean() / std * math.sqrt(ppy), rel=1e-6)
    downside = math.sqrt(np.mean(np.minimum(rets, 0) ** 2))
    if downside >= 1e-12:
        assert metrics.sortino(pd.Series(rets), ppy) == pytest.approx(rets.mean() / downside * math.sqrt(ppy))


# ── Properties ───────────────────────────────────────────────────────────────

price_paths = st.lists(st.floats(-0.06, 0.06), min_size=80, max_size=160).map(
    lambda steps: 100 * np.cumprod(1 + np.asarray(steps))
)


def _path_frame(closes):
    opens = np.concatenate([[closes[0]], closes[:-1]]) * 1.001
    return _frame(opens, closes)


@given(price_paths, st.sampled_from(sorted(strategies.STRATEGIES)), st.data())
@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_no_lookahead_truncating_the_future_changes_nothing_before_it(closes, strategy, data):
    frame = _path_frame(closes)
    cut = data.draw(st.integers(10, len(frame) - 1))
    config = engine.Config(initial_capital=1_000_000, fractional=True)
    full_targets = strategies.targets(frame, strategy)
    head = frame.iloc[: cut + 1]
    head_targets = strategies.targets(head, strategy)
    assert head_targets.tolist() == full_targets.iloc[: cut + 1].tolist()
    full = engine.run(frame, full_targets, config)
    part = engine.run(head, head_targets, config)
    assert part.equity.tolist() == pytest.approx(full.equity.iloc[: cut + 1].tolist())


@given(price_paths)
@settings(max_examples=40, deadline=None)
def test_zero_cost_always_long_equals_buy_and_hold(closes):
    frame = _path_frame(closes)
    config = engine.Config(initial_capital=1000, costs=engine.Costs(0, 0, 0), fractional=True)
    result = engine.buy_and_hold(frame, config)
    expected = 1000 * frame["close"] / frame["open"].iloc[0]
    assert result.equity.tolist() == pytest.approx(expected.tolist(), rel=1e-6)


@given(price_paths, st.sampled_from(sorted(strategies.STRATEGIES)), st.floats(0, 50), st.floats(0, 50))
@settings(max_examples=40, deadline=None)
def test_higher_costs_never_raise_final_equity(closes, strategy, low, extra):
    frame = _path_frame(closes)
    target = strategies.targets(frame, strategy)
    cheap = engine.run(frame, target, engine.Config(costs=engine.Costs(low, low, 0), fractional=True))
    dear = engine.run(
        frame, target, engine.Config(costs=engine.Costs(low + extra, low + extra, extra), fractional=True)
    )
    assert dear.equity.iloc[-1] <= cheap.equity.iloc[-1] + 1e-6


@given(price_paths, st.sampled_from(sorted(strategies.STRATEGIES)), st.sampled_from([0.01, 7.0, 1000.0]))
@settings(max_examples=40, deadline=None)
def test_percentage_results_do_not_depend_on_the_price_scale(closes, strategy, scale):
    base, scaled = _path_frame(closes), _path_frame(np.asarray(closes) * scale)
    config = engine.Config(initial_capital=1_000_000, fractional=True)
    a = engine.run(base, strategies.targets(base, strategy), config)
    b = engine.run(scaled, strategies.targets(scaled, strategy), config)
    assert metrics.returns(b.equity).tolist() == pytest.approx(metrics.returns(a.equity).tolist(), abs=1e-6)


# ── Regressions for the old engine (python-stock-backend/quant.py) ───────────

SAMPLE = SyntheticSource().fetch_daily("005930", date(2023, 1, 1), date(2025, 12, 31))


def test_regression_fast_and_slow_are_used():
    a, b = backtest(SAMPLE, "ma2050", 20, 50), backtest(SAMPLE, "ma2050", 5, 120)
    assert a["metrics"]["totalReturn"] != b["metrics"]["totalReturn"]
    assert a["receipt"]["params"]["fast"] == 20 and b["receipt"]["params"]["slow"] == 120


def test_regression_fills_happen_on_the_bar_after_the_signal():
    result = backtest(SAMPLE, "ma2050")
    frame = bars_to_frame(SAMPLE)
    target = strategies.targets(frame, "ma2050")
    first_buy = result["trades"][0]
    signal_bar = target.index[target.diff().fillna(target) > 0][0]
    assert first_buy.ts == frame.index[frame.index.get_loc(signal_bar) + 1]
    assert first_buy.price == pytest.approx(frame.loc[first_buy.ts, "open"] * (1 + 5e-4))


def test_regression_sharpe_uses_daily_equity_returns():
    result = backtest(SAMPLE, "trend")
    rets = result["equity"].pct_change().dropna().to_numpy()
    assert result["metrics"]["sharpe"] == pytest.approx(rets.mean() / rets.std(ddof=1) * math.sqrt(252))


def test_regression_drawdown_while_holding_is_counted():
    # Price halves while the position is open and recovers before the exit.
    frame = _frame([100, 100, 100, 60, 50, 90, 120, 120], [100, 100, 80, 55, 70, 110, 120, 120])
    target = pd.Series([1, 1, 1, 1, 1, 1, 0, 0], index=frame.index)
    result = engine.run(
        frame, target, engine.Config(initial_capital=1000, costs=engine.Costs(0, 0, 0), fractional=True)
    )
    assert metrics.max_drawdown(result.equity) == pytest.approx(55 / 100 - 1)


def test_regression_cagr_uses_the_whole_period():
    result = backtest(SAMPLE, "ma2050")
    equity = result["equity"]
    assert result["metrics"]["cagr"] == pytest.approx(
        (equity.iloc[-1] / equity.iloc[0]) ** (252 / (len(equity) - 1)) - 1
    )


def test_regression_indicators_wait_for_a_full_window():
    close = pd.Series(np.arange(1.0, 61.0))
    assert indicators.sma(close, 50).first_valid_index() == 49
    assert indicators.rsi(close, 14).first_valid_index() == 14


def test_breakout_levels_exclude_the_current_bar():
    series = pd.Series([1.0, 2.0, 3.0, 4.0])
    assert indicators.prior_max(series, 2).tolist()[2:] == [2.0, 3.0]
    assert indicators.prior_mean(series, 2).tolist()[2:] == [1.5, 2.5]


def test_regression_invalid_parameters_are_value_errors():
    with pytest.raises(ValueError):
        strategies.resolve("ma2050", 50, 20)
    with pytest.raises(ValueError):
        strategies.resolve("nope")
    with pytest.raises(ValueError):
        engine.Costs(fee_bps=-1)


# ── Receipts and walk-forward ────────────────────────────────────────────────


def test_receipt_is_stable_for_the_same_inputs_and_changes_with_them():
    a, b = backtest(SAMPLE, "rsi"), backtest(SAMPLE, "rsi")
    c = backtest(SAMPLE, "rsi", costs=engine.Costs(fee_bps=2))
    assert a["receipt"]["receiptId"] == b["receipt"]["receiptId"] != c["receipt"]["receiptId"]
    assert a["receipt"]["sources"] == ["synthetic"] and a["receipt"]["barCount"] == len(SAMPLE)


def test_walk_forward_tests_only_on_unseen_windows():
    folds, oos = walk_forward(SAMPLE, "ma2050", [(5, 20), (10, 50), (20, 60)], train_bars=250, test_bars=60)
    assert folds
    for fold in folds:
        assert fold.train_end < fold.test_start
    starts = [fold.test_start for fold in folds]
    assert starts == sorted(starts)
    assert all(later.test_start > earlier.test_end for earlier, later in zip(folds, folds[1:], strict=False))
    assert len(oos) == sum(fold.out_of_sample["bars"] - 1 for fold in folds)
    # Whole-share KRX sizing must be able to buy: some fold has to be invested.
    assert any(fold.out_of_sample["exposure"] > 0 for fold in folds)


def test_walk_forward_test_window_inherits_the_position_from_the_training_close():
    # A dip, then a steady rise: MA 5/20 crosses up once inside the first training window and
    # never crosses back, so every test window must be invested from its first bar.
    closes = 100 * np.cumprod(np.concatenate([np.full(40, 0.995), np.full(360, 1.002)]))
    bars = [
        Bar("005930", ts.to_pydatetime(), o, max(o, c) + 1, min(o, c) - 1, c, 1000.0, "synthetic")
        for ts, o, c in zip(
            pd.date_range("2020-01-01", periods=400, freq="B", tz="UTC"),
            np.concatenate([[100.0], closes[:-1]]),
            closes,
            strict=True,
        )
    ]
    folds, _ = walk_forward(bars, "ma2050", [(5, 20)], train_bars=200, test_bars=50, costs=engine.Costs(0, 0, 0))
    for fold in folds:
        assert fold.out_of_sample["exposure"] == 1.0


def test_research_report_is_reproducible():
    from quantlab.research import report

    args = ("005930", date(2016, 1, 1), date(2025, 12, 31), "ma2050", engine.Costs())
    first, second = report(*args), report(*args)
    assert first == second
    assert "## 2. 워크포워드" in first and "사후 최적" in first and "`synthetic`" in first


@pytest.mark.parametrize(
    ("path", "argv"),
    [
        ("krx-005930-ma-walkforward.md", ["--symbol", "005930", "--start", "2016-01-01", "--end", "2025-12-31"]),
        (
            "crypto-krw-btc-ma-walkforward.md",
            ["--symbol", "KRW-BTC", "--start", "2018-01-01", "--end", "2025-12-31", "--fee-bps", "5"],
        ),
    ],
)
def test_committed_research_reports_match_a_fresh_run(tmp_path, path, argv):
    from pathlib import Path

    from quantlab import research

    research.main([*argv, "--strategy", "ma2050", "--out", str(tmp_path / path)])
    committed = Path(__file__).parents[2] / "docs" / "research" / path
    assert (tmp_path / path).read_text(encoding="utf-8") == committed.read_text(encoding="utf-8")
