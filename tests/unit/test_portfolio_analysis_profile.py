"""공개 자산 분석은 지원하는 현금·주식만 집계한다."""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from flask import session

import members


@pytest.mark.parametrize(
    ("profile", "names", "total", "score", "position_count", "source_calls"),
    [
        ("public", ["현금", "주식"], 130, 71, 1, 0),
        ("local", ["현금", "주식", "코인", "대체자산"], 220, 92, 3, 1),
    ],
)
def test_portfolio_analysis_uses_only_profile_assets(
    app, monkeypatch, profile, names, total, score, position_count, source_calls
):
    class DB:
        crypto_queries = 0

        def get(self, _model, _member_id):
            return SimpleNamespace(asset=100)

        def query(self, *_models):
            self.crypto_queries += 1
            return self

        def join(self, *_args):
            return self

        def filter(self, *_args):
            return self

        def all(self):
            return [
                (
                    SimpleNamespace(buy_crypto_count=2, buy_average=15, buy_total_krw=30),
                    SimpleNamespace(market_code="KRW-BTC", korean_name="비트코인"),
                )
            ]

    db = DB()
    calls = {"upbit": 0, "alternative": 0}

    def fake_upbit(*_args, **_kwargs):
        calls["upbit"] += 1
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: [{"market": "KRW-BTC", "trade_price": 20}])

    def fake_alternatives(*_args):
        calls["alternative"] += 1
        return [{"name": "선물", "category": "선물", "evalAmount": 50, "pnl": -10}]

    monkeypatch.setattr(members, "session_scope", lambda: nullcontext(db))
    monkeypatch.setattr(
        members.stock_trading,
        "get_positions",
        lambda *_args: [{"name": "주식", "sector": "기타", "evalAmount": 30, "pnl": 5}],
    )
    monkeypatch.setattr(members.requests, "get", fake_upbit)
    monkeypatch.setattr(members, "get_alternative_positions", fake_alternatives)
    app.config["APP_PROFILE"] = profile

    with app.test_request_context("/api/member/portfolio-analysis"):
        session["member_id"] = 1
        data = members.portfolio_analysis().get_json()

    assert [item["name"] for item in data["allocation"]] == names
    assert data["totalAsset"] == total
    assert data["diversification"]["score"] == score
    assert data["positionStats"]["count"] == position_count
    assert db.crypto_queries == source_calls
    assert calls == {"upbit": source_calls, "alternative": source_calls}
