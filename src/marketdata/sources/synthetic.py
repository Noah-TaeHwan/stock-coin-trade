"""Deterministic synthetic daily bars (geometric Brownian motion).

Labelled "synthetic" everywhere they are stored or shown. The same symbol,
start and end always give the same bars, so tests and research reports can
be reproduced exactly. Each symbol's path starts at ANCHOR_DATE; asking for a
later window replays the path up to it, so overlapping windows agree.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from datetime import date

from marketdata.bars import Bar
from marketdata.calendars import bar_time, calendar_for, periods_per_year, trading_days

ANCHOR_DATE = date(2020, 1, 1)


@dataclass(frozen=True)
class Profile:
    start_price: float
    annual_drift: float
    annual_vol: float
    base_volume: float


# Illustrative parameters, not estimates of any real series.
PROFILES = {
    "005930": Profile(55_000, 0.06, 0.28, 12_000_000),
    "000660": Profile(95_000, 0.09, 0.40, 3_000_000),
    "KRW-BTC": Profile(9_000_000, 0.25, 0.65, 3_000),
    "KRW-ETH": Profile(160_000, 0.20, 0.80, 20_000),
}
DEFAULT_KRX = Profile(30_000, 0.05, 0.30, 1_000_000)
DEFAULT_CRYPTO = Profile(1_000, 0.10, 0.90, 100_000)


def _seed(symbol: str) -> int:
    return int.from_bytes(hashlib.sha256(f"synthetic:{symbol}".encode()).digest()[:8], "big")


def _round_price(value: float, calendar: str) -> float:
    # KRX prices are whole won; crypto keeps 4 decimals like the DB column.
    return float(round(value)) if calendar == "krx" else round(value, 4)


class SyntheticSource:
    id = "synthetic"

    def fetch_daily(self, symbol: str, start: date, end: date) -> list[Bar]:
        calendar = calendar_for(symbol)
        profile = PROFILES.get(symbol) or (DEFAULT_CRYPTO if calendar == "crypto" else DEFAULT_KRX)
        dt = 1 / periods_per_year(calendar)
        drift = (profile.annual_drift - 0.5 * profile.annual_vol**2) * dt
        step_vol = profile.annual_vol * math.sqrt(dt)
        rng = random.Random(_seed(symbol))

        bars = []
        previous_close = profile.start_price
        for day in trading_days(calendar, min(ANCHOR_DATE, start), end):
            gap = rng.gauss(0, step_vol * 0.25)
            open_ = previous_close * math.exp(gap)
            close = previous_close * math.exp(drift + step_vol * rng.gauss(0, 1))
            high = max(open_, close) * math.exp(abs(rng.gauss(0, step_vol * 0.5)))
            low = min(open_, close) * math.exp(-abs(rng.gauss(0, step_vol * 0.5)))
            volume = profile.base_volume * math.exp(rng.gauss(0, 0.35))
            previous_close = close
            if day < start:
                continue
            bars.append(
                Bar(
                    symbol=symbol,
                    ts=bar_time(day),
                    open=_round_price(open_, calendar),
                    high=_round_price(high, calendar),
                    low=_round_price(low, calendar),
                    close=_round_price(close, calendar),
                    volume=round(volume, 4 if calendar == "crypto" else 0),
                    source=self.id,
                )
            )
        return bars
