"""Data quality checks for daily bars.

Severity:
- error: the bar cannot be right (OHLC order broken, non-positive price,
  duplicate timestamp). Ingestion refuses a batch with errors.
- warn: suspicious but possible (calendar gap, very large move, stale data).
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from marketdata.bars import Bar
from marketdata.calendars import CRYPTO, calendar_for, trading_days

# Daily close-to-close log return above which a move is flagged. KRX's daily
# price limit is ±30%; crypto has none, so its threshold is wider.
JUMP_LIMIT = {"krx": math.log(1.30), CRYPTO: math.log(1.60)}
STALE_AFTER = {"krx": timedelta(days=5), CRYPTO: timedelta(days=2)}


@dataclass(frozen=True)
class Finding:
    check: str
    severity: str
    symbol: str
    ts: datetime | None
    detail: str

    def as_dict(self) -> dict:
        data = asdict(self)
        data["ts"] = self.ts.isoformat() if self.ts else None
        return data


def check(bars: Sequence[Bar], as_of: datetime | None = None) -> list[Finding]:
    """Run every check on one symbol's bars (any order)."""
    if not bars:
        return []
    symbol = bars[0].symbol
    calendar = calendar_for(symbol)
    ordered = sorted(bars, key=lambda bar: bar.ts)
    findings: list[Finding] = []

    for bar in ordered:
        prices = (bar.open, bar.high, bar.low, bar.close)
        if min(prices) <= 0 or bar.volume < 0:
            findings.append(Finding("non_positive", "error", symbol, bar.ts, f"prices={prices} volume={bar.volume}"))
        if bar.high < max(bar.open, bar.close) or bar.low > min(bar.open, bar.close) or bar.low > bar.high:
            detail = f"o={bar.open} h={bar.high} l={bar.low} c={bar.close}"
            findings.append(Finding("ohlc_order", "error", symbol, bar.ts, detail))

    for ts, count in Counter(bar.ts for bar in ordered).items():
        if count > 1:
            findings.append(Finding("duplicate", "error", symbol, ts, f"{count} bars share this timestamp"))

    present = {bar.ts.date() for bar in ordered}
    expected = trading_days(calendar, ordered[0].ts.date(), ordered[-1].ts.date())
    missing = [day for day in expected if day not in present]
    if missing:
        detail = f"{len(missing)} {calendar} trading days missing, first {missing[0].isoformat()}"
        if calendar != CRYPTO:
            detail += " (KRX holidays are not modelled, so some gaps are expected)"
        findings.append(Finding("calendar_gap", "warn", symbol, None, detail))

    for previous, current in zip(ordered, ordered[1:], strict=False):
        if previous.close > 0 and current.close > 0:
            move = math.log(current.close / previous.close)
            if abs(move) > JUMP_LIMIT[calendar]:
                detail = f"close-to-close {math.exp(move) - 1:+.1%}"
                findings.append(Finding("jump", "warn", symbol, current.ts, detail))

    if as_of is not None and as_of - ordered[-1].ts > STALE_AFTER[calendar]:
        detail = f"last bar is {(as_of - ordered[-1].ts).days} days old"
        findings.append(Finding("stale", "warn", symbol, ordered[-1].ts, detail))
    return findings


def has_errors(findings: Sequence[Finding]) -> bool:
    return any(finding.severity == "error" for finding in findings)
