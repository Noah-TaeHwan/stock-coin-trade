"""Registry rules, synthetic bars and quality checks (no database)."""

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from marketdata import calendars, quality, registry
from marketdata.bars import Bar, checksum
from marketdata.sources.synthetic import SyntheticSource

VALID_SOURCE = """
[sources.demo]
name = "demo"
kind = "api"
status = "{status}"
checked_on = "2026-09-25"
checked_by = "tester"
commercial_use = "allowed"
redistribution = "{redistribution}"
modification = "allowed"
attribution = "demo source"
enabled = {{ local = true, public = {public} }}
"""


def _registry(tmp_path, status="verified", redistribution="allowed", public="true"):
    path = tmp_path / "sources.toml"
    path.write_text(VALID_SOURCE.format(status=status, redistribution=redistribution, public=public))
    return registry.load(path)


# ── Registry ─────────────────────────────────────────────────────────────────


def test_policy_accepts_a_verified_redistributable_public_source(tmp_path):
    assert registry.policy_problems(_registry(tmp_path)) == []


@pytest.mark.parametrize(
    ("status", "redistribution", "problem"),
    [
        ("unverified", "allowed", "status"),
        ("verified", "forbidden", "redistribution"),
        ("verified", "unknown", "redistribution"),
    ],
)
def test_policy_rejects_unsafe_public_sources(tmp_path, status, redistribution, problem):
    problems = registry.policy_problems(_registry(tmp_path, status, redistribution))
    assert any(problem in p for p in problems)


def test_require_refuses_a_source_switched_off_for_the_profile(tmp_path):
    reg = _registry(tmp_path, public="false")
    assert reg.require("demo", "local").id == "demo"
    with pytest.raises(registry.SourceNotAllowed):
        reg.require("demo", "public")


def test_malformed_entries_are_rejected(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text(VALID_SOURCE.format(status="maybe", redistribution="allowed", public="true"))
    with pytest.raises(registry.RegistryError, match="status"):
        registry.load(path)


# ── Synthetic source ─────────────────────────────────────────────────────────


def test_synthetic_bars_are_deterministic_and_windows_agree():
    source = SyntheticSource()
    full = source.fetch_daily("005930", date(2025, 1, 1), date(2025, 3, 31))
    again = source.fetch_daily("005930", date(2025, 1, 1), date(2025, 3, 31))
    window = source.fetch_daily("005930", date(2025, 2, 1), date(2025, 2, 28))
    assert full == again
    assert window == [bar for bar in full if bar.ts.month == 2]
    assert checksum(full) == checksum(again)


def test_synthetic_calendars_match_the_asset():
    krx = SyntheticSource().fetch_daily("005930", date(2025, 6, 2), date(2025, 6, 15))
    btc = SyntheticSource().fetch_daily("KRW-BTC", date(2025, 6, 2), date(2025, 6, 15))
    assert len(krx) == 10 and all(bar.ts.weekday() < 5 for bar in krx)
    assert len(btc) == 14
    assert all(bar.source == "synthetic" and bar.ts.tzinfo is not None for bar in krx + btc)


@pytest.mark.parametrize("symbol", ["005930", "000660", "KRW-BTC", "KRW-ETH", "123456", "KRW-XYZ"])
def test_synthetic_bars_pass_the_quality_checks(symbol):
    bars = SyntheticSource().fetch_daily(symbol, date(2024, 1, 1), date(2025, 12, 31))
    findings = quality.check(bars)
    assert not quality.has_errors(findings), findings[:3]
    assert not [f for f in findings if f.check == "calendar_gap"]


# ── Quality checks ───────────────────────────────────────────────────────────


def _bar(day, **prices):
    base = {"open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0, "volume": 1.0}
    base.update(prices)
    return Bar("005930", calendars.bar_time(day), source="test", **base)


def _checks(findings):
    return {(f.check, f.severity) for f in findings}


def test_quality_flags_broken_ohlc_and_non_positive_prices():
    bars = [_bar(date(2025, 6, 2), high=99.0), _bar(date(2025, 6, 3), low=0.0)]
    assert {("ohlc_order", "error"), ("non_positive", "error")} <= _checks(quality.check(bars))


def test_quality_flags_duplicates_gaps_jumps_and_staleness():
    monday = _bar(date(2025, 6, 2))
    bars = [monday, replace(monday), _bar(date(2025, 6, 4), open=150, high=160, low=140, close=150)]
    findings = quality.check(bars, as_of=datetime(2025, 6, 30, tzinfo=UTC))
    assert {("duplicate", "error"), ("calendar_gap", "warn"), ("jump", "warn"), ("stale", "warn")} <= _checks(findings)
    assert quality.has_errors(findings)


def test_a_clean_series_has_no_findings():
    bars = [_bar(date(2025, 6, day)) for day in (2, 3, 4, 5, 6)]
    assert quality.check(bars, as_of=datetime(2025, 6, 7, tzinfo=UTC)) == []
