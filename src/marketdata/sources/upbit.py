"""Upbit daily candles (Quotation REST API, no key).

Endpoint and fields follow the official reference: GET /v1/candles/days with
`market`, `to` (exclusive, ISO 8601) and `count` (at most 200); each item has
candle_date_time_utc, opening_price, high_price, low_price, trade_price and
candle_acc_trade_volume.

Rate limits (https://docs.upbit.com/kr/docs/rate-limits): the candle group
allows 10 requests per second per IP; the `sec` field of the Remaining-Req
header is what is left in the current second (`min` is deprecated). Ignoring
429 leads to a 418 block, so a 429 backs off and a 418 stops immediately.
Requests with an Origin header get a much lower limit; requests does not send
one.

The registry keeps this source off for the public profile until its terms are
checked (config/data_sources.toml).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

import requests

from marketdata.bars import Bar

BASE_URL = "https://api.upbit.com/v1/candles/days"
MAX_COUNT = 200
MIN_INTERVAL = 1 / 8  # stay under the 10 req/s candle group limit
MAX_429_RETRIES = 3


class UpbitBlocked(RuntimeError):
    """Upbit answered 418: the IP is blocked for a while. Do not retry."""


def remaining_per_second(header: str | None) -> int | None:
    """`group=candle; min=1800; sec=29` -> 29."""
    for part in (header or "").split(";"):
        key, _, value = part.strip().partition("=")
        if key == "sec" and value.isdigit():
            return int(value)
    return None


def parse_candles(market: str, items: list[dict]) -> list[Bar]:
    bars = [
        Bar(
            symbol=market,
            ts=datetime.fromisoformat(item["candle_date_time_utc"]).replace(tzinfo=UTC),
            open=float(item["opening_price"]),
            high=float(item["high_price"]),
            low=float(item["low_price"]),
            close=float(item["trade_price"]),
            volume=float(item["candle_acc_trade_volume"]),
            source="upbit",
        )
        for item in items
    ]
    return sorted(bars, key=lambda bar: bar.ts)


class UpbitSource:
    id = "upbit"

    def __init__(self, session: requests.Session | None = None, sleep: Callable[[float], None] = time.sleep):
        self.session = session or requests.Session()
        self.sleep = sleep
        self._last_request = 0.0

    def _get(self, params: dict) -> list[dict]:
        for attempt in range(MAX_429_RETRIES + 1):
            wait = MIN_INTERVAL - (time.monotonic() - self._last_request)
            if wait > 0:
                self.sleep(wait)
            self._last_request = time.monotonic()
            response = self.session.get(BASE_URL, params=params, headers={"Accept": "application/json"}, timeout=10)
            if response.status_code == 418:
                raise UpbitBlocked(f"Upbit blocked this IP: {response.text[:200]}")
            if response.status_code == 429:
                self.sleep(2**attempt)
                continue
            response.raise_for_status()
            if remaining_per_second(response.headers.get("Remaining-Req")) == 0:
                self.sleep(1.0)
            return response.json()
        raise requests.HTTPError(f"Upbit kept answering 429 after {MAX_429_RETRIES} retries")

    def fetch_daily(self, symbol: str, start: date, end: date) -> list[Bar]:
        """Page backwards from `end` in chunks of 200 until `start` is covered."""
        bars: dict[datetime, Bar] = {}
        to = datetime(end.year, end.month, end.day, tzinfo=UTC) + timedelta(days=1)
        first = datetime(start.year, start.month, start.day, tzinfo=UTC)
        while to > first:
            items = self._get({"market": symbol, "to": to.strftime("%Y-%m-%dT%H:%M:%SZ"), "count": MAX_COUNT})
            page = parse_candles(symbol, items)
            if not page:
                break
            for bar in page:
                if first <= bar.ts < datetime(end.year, end.month, end.day, tzinfo=UTC) + timedelta(days=1):
                    bars[bar.ts] = bar
            if page[0].ts >= to:  # no progress; guard against an endless loop
                break
            to = page[0].ts
        return [bars[ts] for ts in sorted(bars)]
