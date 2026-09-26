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


def test_only_synthetic_data_is_public_until_terms_are_checked(reg):
    public = reg.enabled("public")
    assert sorted(source.id for source in public) == ["synthetic", "synthetic_sql"]
    assert {source.kind for source in public} == {"synthetic"}


def test_every_source_has_an_attribution_text(reg):
    assert all(source.attribution.strip() for source in reg.sources.values())


def test_noah_terms_decisions_2026_09_26_are_recorded(reg):
    """노아 판정(docs/evidence/data-rights-2026-09-26.md §8)이 레지스트리에 반영돼 있다."""
    dart = reg.sources["dart"]
    assert dart.status == "verified" and "노아" in dart.checked_by and dart.terms_url.startswith("https://opendart")
    assert not dart.allowed_in("public"), "공개는 S3에서 정확성 비보장 고지를 붙인 뒤 켠다"
    for scraped in ("naver_finance", "krx_kind"):
        assert not reg.sources[scraped].allowed_in("local"), f"{scraped}: 약관이 자동 수집을 금지해 로컬에서도 끈다"
    assert reg.sources["upbit"].commercial_use == "forbidden"
    assert reg.sources["upbit"].redistribution == "forbidden"
