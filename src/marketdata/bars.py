"""The daily bar every source produces and every consumer reads."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Bar:
    symbol: str
    ts: datetime  # bar open time, timezone-aware UTC
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str

    def canonical(self) -> str:
        """Stable text form used for checksums (prices rounded like the DB column)."""
        prices = "|".join(f"{value:.4f}" for value in (self.open, self.high, self.low, self.close))
        return f"{self.symbol}|{self.ts.isoformat()}|{prices}|{self.volume:.8f}|{self.source}"


def checksum(bars: Iterable[Bar]) -> str:
    """sha256 over the bars in (symbol, ts) order: same input rows, same checksum."""
    digest = hashlib.sha256()
    for bar in sorted(bars, key=lambda b: (b.symbol, b.ts)):
        digest.update(bar.canonical().encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()
