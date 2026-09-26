"""The committed data source registry must satisfy the publication policy."""

import pytest

from marketdata import registry


@pytest.fixture(scope="module")
def reg():
    return registry.load()


def test_registry_loads_and_names_every_source_in_use(reg):
    expected = {
        "synthetic",
        "synthetic_sql",
        "upbit",
        "krx_openapi",
        "datagokr_stock",
        "yfinance",
        "naver_finance",
        "krx_kind",
        "exchange_quotes",
        "coinmarketcap",
        "bithumb_notices",
        "dart",
    }
    assert expected <= set(reg.sources)


def test_everything_enabled_for_public_is_verified_and_redistributable(reg):
    assert registry.policy_problems(reg) == []


def test_unofficial_and_unverified_sources_are_off_in_public(reg):
    for source in reg.sources.values():
        if source.status != "verified" or source.kind == "unofficial":
            assert not source.allowed_in("public"), source.id


def test_public_data_is_synthetic_or_a_verified_source_noah_approved(reg):
    # 공개 사이트는 합성 데이터와, 노아가 약관을 판정해 공개를 허락한 출처(DART, 2026-09-26)만 쓴다.
    public = reg.enabled("public")
    assert sorted(source.id for source in public) == ["dart", "synthetic", "synthetic_sql"]
    assert all(source.kind == "synthetic" or source.status == "verified" for source in public)


def test_every_source_has_an_attribution_text(reg):
    assert all(source.attribution.strip() for source in reg.sources.values())


def test_noah_terms_decisions_2026_09_26_are_recorded(reg):
    """노아 판정(docs/evidence/data-rights-2026-09-26.md §8)이 레지스트리에 반영돼 있다."""
    dart = reg.sources["dart"]
    assert dart.status == "verified" and "노아" in dart.checked_by and dart.terms_url.startswith("https://opendart")
    # S3(2026-09-26)에서 출처·정확성 비보장 고지(dart_radar.NOTICE)를 붙여 공개했다.
    assert dart.allowed_in("public") and dart.attribution
    for scraped in ("naver_finance", "krx_kind"):
        assert not reg.sources[scraped].allowed_in("local"), f"{scraped}: 약관이 자동 수집을 금지해 로컬에서도 끈다"
    assert reg.sources["upbit"].commercial_use == "forbidden"
    assert reg.sources["upbit"].redistribution == "forbidden"
