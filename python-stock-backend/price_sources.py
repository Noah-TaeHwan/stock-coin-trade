"""Which market data sources this deployment may call, and how to label them.

The data source registry (config/data_sources.toml) decides per APP_PROFILE.
Web requests read the profile from the Flask app; the worker and CLI read it
from the environment. When no licensed live source is allowed (the public
profile today), quotes and charts come from the deterministic synthetic
source and every response says so.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

from flask import current_app, has_app_context

from marketdata import registry
from marketdata.sources.synthetic import SyntheticSource
from settings import profile_from_env

SIMULATED_ATTRIBUTION = "시뮬레이션 가격 — 외부 시세를 가져오지 못해 표시하는 값입니다"


@lru_cache(maxsize=1)
def _registry() -> registry.Registry:
    return registry.load()


def profile() -> str:
    return current_app.config["APP_PROFILE"] if has_app_context() else profile_from_env()


def allowed(source_id: str) -> bool:
    return _registry().get(source_id).allowed_in(profile())


def label(source_id: str) -> dict:
    """`{"source": id, "attribution": text}` for API responses."""
    if source_id == "simulated":
        return {"source": "simulated", "attribution": SIMULATED_ATTRIBUTION}
    return {"source": source_id, "attribution": _registry().get(source_id).attribution}


@lru_cache(maxsize=256)
def synthetic_bars(symbol: str, end: date, days: int) -> tuple:
    """Synthetic daily bars for the `days` calendar days ending on `end`."""
    return tuple(SyntheticSource().fetch_daily(symbol, end - timedelta(days=days), end))


def synthetic_quote(symbol: str, today: date | None = None) -> dict:
    """Quote from the last two synthetic daily bars up to today."""
    bars = synthetic_bars(symbol, today or date.today(), 10)
    last, previous = bars[-1], bars[-2]
    price, prev_close = int(round(last.close)), int(round(previous.close))
    change = price - prev_close
    return {
        "symbol": symbol,
        "price": price,
        "prevClose": prev_close,
        "change": change,
        "changeRate": round(change / prev_close * 100, 2) if prev_close else 0.0,
        "volume": int(last.volume),
        **label("synthetic"),
    }


def synthetic_chart(symbol: str, days: int, today: date | None = None) -> list[dict]:
    """Daily candles in the chart API format ({x, o, h, l, c, v}, x in ms)."""
    return [
        {"x": int(bar.ts.timestamp() * 1000), "o": round(bar.open, 2), "h": round(bar.high, 2),
         "l": round(bar.low, 2), "c": round(bar.close, 2), "v": int(bar.volume)}
        for bar in synthetic_bars(symbol, today or date.today(), days)
    ]
