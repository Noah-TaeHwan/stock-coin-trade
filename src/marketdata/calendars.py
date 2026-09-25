"""Trading calendars for daily bars (bar open time is 00:00 UTC of the date)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

# KRX: weekdays only. Exchange holidays are not modelled, so a real KRX series
# shows holiday "gaps" that quality.py reports as warnings, not errors.
KRX = "krx"
# Crypto trades every day.
CRYPTO = "crypto"


def calendar_for(symbol: str) -> str:
    return CRYPTO if "-" in symbol else KRX


def trading_days(calendar: str, start: date, end: date) -> list[date]:
    if end < start:
        return []
    days = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
    if calendar == KRX:
        return [day for day in days if day.weekday() < 5]
    if calendar == CRYPTO:
        return days
    raise ValueError(f"unknown calendar {calendar!r}")


def bar_time(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def periods_per_year(calendar: str) -> int:
    return 252 if calendar == KRX else 365
