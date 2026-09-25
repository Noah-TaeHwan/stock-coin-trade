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
