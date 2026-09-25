"""In-sample vs walk-forward report for one symbol, as Markdown.

    python -m quantlab.research --symbol 005930 --start 2016-01-01 --end 2025-12-31 \
        --strategy ma2050 --out docs/research/krx-005930-ma-walkforward.md

Bars come from the deterministic synthetic source, so anyone can re-run the
command and get the same numbers (the receipt ids in the report prove it).
The report compares three things on the same bars and costs:

1. the strategy's default parameters over the whole period,
2. the best (fast, slow) pair chosen with hindsight over the whole period
   (in-sample: what a naive optimisation would report), and
3. walk-forward: the pair is re-chosen on each training window and judged
   only on the following, unseen test window.
"""

from __future__ import annotations

import argparse
from datetime import date
from itertools import product
from pathlib import Path

from marketdata.calendars import CRYPTO, calendar_for
from marketdata.sources.synthetic import SyntheticSource
from quantlab import ENGINE_VERSION, engine, metrics
from quantlab.backtest import backtest, config_for
from quantlab.frame import bars_to_frame
from quantlab.validation import walk_forward

FAST = (5, 10, 20, 30)
SLOW = (40, 60, 90, 120, 200)


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:+.2f}%"


def _num(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"


def _row(label: str, m: dict, extra: str = "") -> str:
    return (
        f"| {label} | {_pct(m['totalReturn'])} | {_pct(m['cagr'])} | {_num(m['sharpe'])} | "
        f"{_pct(m['maxDrawdown'])} | {m['trades']} | {extra} |"
    )


def report(symbol: str, start: date, end: date, strategy: str, costs: engine.Costs) -> str:
    bars = SyntheticSource().fetch_daily(symbol, start, end)
    crypto = calendar_for(symbol) == CRYPTO
    per_year = 365 if crypto else 252
    grid = [(f, s) for f, s in product(FAST, SLOW) if f < s]

    default = backtest(bars, strategy, costs=costs)
    runs = [(pair, backtest(bars, strategy, *pair, costs=costs)) for pair in grid]
    (best_pair, best) = max(runs, key=lambda run: run[1]["metrics"]["sharpe"] or float("-inf"))

    train, test = 3 * per_year, per_year // 2
    folds, oos = walk_forward(bars, strategy, grid, train_bars=train, test_bars=test, costs=costs)
    frame = bars_to_frame(bars)
    config = config_for(symbol, costs, 10_000_000)
    oos_frame = frame.loc[folds[0].test_start : folds[-1].test_end]
    hold = engine.buy_and_hold(oos_frame, config)
    hold_m = metrics.summarize(hold, per_year)
    oos_equity = oos / oos.iloc[0] if len(oos) else oos
    oos_m = {
        "totalReturn": float(oos.iloc[-1] - 1),
        "cagr": metrics.cagr(oos_equity, per_year),
        "sharpe": metrics.sharpe(metrics.returns(oos), per_year),
        "maxDrawdown": metrics.max_drawdown(oos),
        "trades": sum(fold.out_of_sample["trades"] for fold in folds),
    }
    # The hindsight-best run over the same span: a slice of the full-period run, so its
    # indicators are warmed up exactly like the walk-forward windows.
    span = best["equity"].loc[folds[0].test_start : folds[-1].test_end]
    span_trades = [trade for trade in best["trades"] if folds[0].test_start <= trade.ts <= folds[-1].test_end]
    best_span = {
        "totalReturn": float(span.iloc[-1] / span.iloc[0] - 1),
        "cagr": metrics.cagr(span, per_year),
        "sharpe": metrics.sharpe(metrics.returns(span), per_year),
        "maxDrawdown": metrics.max_drawdown(span),
        "trades": len(span_trades),
    }

    lines = [
        f"# {symbol} · {default['strategy']['label']} — 표본 내 최적화 vs 워크포워드",
        "",
        f"- 데이터: `synthetic`(결정적 GBM, 실제 시세 아님) {bars[0].ts.date()} ~ {bars[-1].ts.date()}, {len(bars)}봉",
        f"- 엔진: `{ENGINE_VERSION}`, 비용: 수수료 {costs.fee_bps}bp · 슬리피지 {costs.slippage_bps}bp · "
        f"매도세 {costs.sell_tax_bps}bp, 연 {per_year}봉",
        f"- 규칙: {default['strategy']['rule']}",
        f"- 탐색 격자: fast {FAST} × slow {SLOW} 중 fast < slow인 {len(grid)}쌍, 선택 기준은 Sharpe",
        f"- 재현: `PYTHONPATH=src python -m quantlab.research --symbol {symbol} --start {start} --end {end} "
        f"--strategy {strategy}`",
        "",
        "## 1. 전체 기간(표본 내)",
        "",
        "| 실행 | 총수익률 | CAGR | Sharpe | MDD | 체결 | 영수증 |",
        "|---|---|---|---|---|---|---|",
        _row(
            f"기본값 {default['receipt']['params']['fast']}/{default['receipt']['params']['slow']}",
            default["metrics"],
            f"`{default['receipt']['receiptId'][:12]}`",
        ),
        _row(f"사후 최적 {best_pair[0]}/{best_pair[1]}", best["metrics"], f"`{best['receipt']['receiptId'][:12]}`"),
        _row("매수 후 보유", default["benchmark"]),
        "",
        "사후 최적값은 결과를 본 뒤 고른 파라미터라서, 이 숫자는 실제로 얻을 수 있었던 성과가 아니다.",
        "",
        f"## 2. 워크포워드(학습 {train}봉 → 검증 {test}봉, 겹치지 않는 {len(folds)}개 구간)",
        "",
        "| 구간 | 학습 기간 | 검증 기간 | 선택 | 학습 Sharpe | 검증 수익률 | 검증 Sharpe |",
        "|---|---|---|---|---|---|---|",
    ]
    for number, fold in enumerate(folds, 1):
        lines.append(
            f"| {number} | {fold.train_start.date()} ~ {fold.train_end.date()} | {fold.test_start.date()} ~ "
            f"{fold.test_end.date()} | {fold.fast}/{fold.slow} | {_num(fold.in_sample_sharpe)} | "
            f"{_pct(fold.out_of_sample['totalReturn'])} | {_num(fold.out_of_sample['sharpe'])} |"
        )
    lines += [
        "",
        f"## 3. 같은 검증 구간({folds[0].test_start.date()} ~ {folds[-1].test_end.date()}) 비교",
        "",
        "| 실행 | 총수익률 | CAGR | Sharpe | MDD | 체결 | 비고 |",
        "|---|---|---|---|---|---|---|",
        _row("워크포워드(검증 구간 이어 붙임)", oos_m, "매 구간 학습 구간에서만 선택"),
        _row(f"사후 최적 {best_pair[0]}/{best_pair[1]}", best_span, "전체 기간을 보고 고름"),
        _row("매수 후 보유", hold_m),
        "",
        "워크포워드 수익률은 구간 사이의 1봉 수익률을 포함하지 않는다(`src/quantlab/validation.py`).",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--strategy", default="ma2050")
    parser.add_argument("--fee-bps", type=float, default=1.5)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    text = report(args.symbol, args.start, args.end, args.strategy, engine.Costs(args.fee_bps, args.slippage_bps))
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
