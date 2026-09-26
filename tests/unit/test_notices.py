"""빗썸 공지 레이더(src/deskjev/notices.py + 김프 matrix). Jev와 빗썸 응답은 가짜로 만든다: 네트워크 없음."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from flask import Flask

import arbitrage
import jev_usage
from deskjev import notices

NOW = datetime(2026, 9, 26, 9, 0, tzinfo=notices.KST)


def _notice(title: str, *categories: str, published: str = "2026-09-24 10:00:00") -> dict:
    return {
        "title": title,
        "categories": list(categories),
        "pc_url": "https://feed.bithumb.com/notice/1",
        "published_at": published,
    }


def _choice(probabilities: dict[str, float], choice: str | None = None):
    top = max(probabilities, key=probabilities.get)
    return SimpleNamespace(choice=choice or top, confidence=probabilities[top], probabilities=probabilities)


def _answers(kind: dict, scope: dict | None = None) -> dict:
    return {"kind": _choice(kind), "scope": _choice(scope or {"coins": 1.0})}


# ── 규칙 ────────────────────────────────────────────────────────────────────


def test_tickers_come_from_uppercase_parentheses_only():
    assert notices.tickers("아발란체(AVAX) 네트워크 계열 가상자산 3종 입출금 일시 중지 안내 (09/23 재개)") == ["AVAX"]
    assert notices.tickers("비트겟(Bitget) 거래소 대상 출금 주의 안내") == []  # 거래소 이름은 대소문자가 섞여 있다
    assert notices.tickers("이더리움(ETH), 체인링크(LINK) 입출금 일시 중지 안내 (10/01 오전 10시~)") == ["ETH", "LINK"]
    assert notices.tickers("그래비티(G) 입출금 중지 (1)") == ["G"]


@pytest.mark.parametrize(
    ("title", "categories", "kind", "coins"),
    [
        # 재개 날짜가 지났으면 끝난 중단이다. 날짜 비교는 코드가 한다.
        ("인젝티브(INJ) 입출금 일시 중지 안내 (09/25 재개)", ["입출금"], "none", ["INJ"]),
        ("비트코인(BTC) 입출금 일시 중지 안내 (09/30 재개)", ["입출금"], "suspend", ["BTC"]),
        ("만트라(MANTRA) 출금 일시 중지 안내 (09/25 오전 10시~)", ["입출금"], "suspend", ["MANTRA"]),
        ("인젝티브(INJ) 거래유의종목 지정 해제", ["거래유의"], "none", ["INJ"]),
        ("트론(TRX) 거래유의종목 지정 안내", ["거래유의"], "caution", ["TRX"]),
        ("비트겟(Bitget) 거래소 대상 출금 주의 안내", ["안내"], "external", "ALL"),
        ("가상자산 정기실사를 위한 가상자산 입출금 일시 중지 안내", ["점검", "입출금"], "suspend", "ALL"),
        ("코인 이자받기(자유형 스테이킹) 앱토스(APT) 오픈 기념 이벤트", ["이벤트"], "none", ["APT"]),
        ("리플(XRP) 입출금 재개 안내", ["입출금"], "none", ["XRP"]),
    ],
)
def test_rules_decide_the_clear_titles(title, categories, kind, coins):
    got = notices.rules(_notice(title, *categories), NOW)
    assert (got.kind, got.coins, got.by, got.probability) == (kind, coins, "rules", None)
    assert got.risk == (kind != "none")


def test_network_family_is_flagged_so_tokens_on_that_chain_match():
    got = notices.rules(_notice("이더리움(ETH) 네트워크 계열 가상자산 5종 입출금 일시 중지 안내", "입출금"), NOW)
    assert (got.kind, got.coins, got.network) == ("suspend", ["ETH"], True)


@pytest.mark.parametrize(
    "title",
    [
        "솔라나(SOL) 네트워크 업그레이드 지원 안내",  # 입출금 중단을 뜻하지만 낱말이 없다
        "일부 가상자산 입출금 지연 안내",  # 대상이 불명확하다
        "고객 자산 보호 체계 안내",
    ],
)
def test_rules_leave_the_ambiguous_titles_to_jev(title):
    assert notices.rules(_notice(title, "안내"), NOW) is None


def test_rules_fallback_warns_only_for_risk_categories():
    wallet = notices.judge(_notice("솔라나(SOL) 네트워크 업그레이드 지원 안내", "입출금"), NOW)
    assert (wallet.risk, wallet.kind, wallet.coins, wallet.by) == (True, "unknown", ["SOL"], "rules")
    general = notices.judge(_notice("고객 자산 보호 체계 안내", "안내"), NOW)
    assert (general.risk, general.kind) == (False, "unknown")


# ── Jev 답의 결정 정책 ───────────────────────────────────────────────────────


def test_risk_probability_is_the_sum_over_risk_kinds():
    # 중단 0.3 + 거래 경고 0.3 = 위험 0.6. 가장 큰 단일 항목(none 0.4)이 아니라 위험 합으로 판단한다.
    got = notices.decide(_answers({"suspend": 0.3, "caution": 0.3, "none": 0.4}), _notice("X(SOL) 안내"), 500)
    assert (got.risk, got.kind, got.coins, got.by, got.input_tokens) == (True, "suspend", ["SOL"], "jev", 500)
    assert got.probability == pytest.approx(0.6)


def test_low_risk_probability_is_not_a_warning():
    got = notices.decide(_answers({"none": 0.9, "suspend": 0.1}), _notice("X(SOL) 안내"))
    assert (got.risk, got.kind) == (False, "none") and got.probability == pytest.approx(0.1)


def test_scope_all_and_external_mean_every_coin():
    everything = notices.decide(_answers({"suspend": 0.95}, {"all": 0.9, "coins": 0.1}), _notice("전체 점검 안내"))
    assert everything.coins == "ALL"
    external = notices.decide(_answers({"external": 0.9}), _notice("오케이엑스(OKX) 거래소 대상 출금 주의"))
    assert external.coins == "ALL"
    unknown = notices.decide(_answers({"suspend": 0.9}), _notice("일부 가상자산 입출금 지연 안내"))
    assert unknown.coins == "UNKNOWN"


def test_options_jev_was_not_given_are_dropped():
    got = notices.decide(_answers({"transfer_funds": 0.9, "none": 0.1}), _notice("X(SOL) 안내"))
    assert (got.risk, got.kind) == (False, "none")
    with pytest.raises(ValueError):
        notices.decide(_answers({"transfer_funds": 1.0}), _notice("X(SOL) 안내"))


def test_the_distribution_wins_over_a_mismatched_choice_label():
    answers = {"kind": _choice({"none": 0.9, "suspend": 0.1}, choice="suspend"), "scope": _choice({"coins": 1.0})}
    assert notices.decide(answers, _notice("X(SOL) 안내")).risk is False


def test_ask_pins_the_model_and_sends_only_title_and_categories():
    seen = {}

    class FakeClient:
        def system_one(self, state, questions, *, model):
            seen.update(state=state, questions=set(questions), model=model)
            return SimpleNamespace(answers=_answers({"suspend": 0.9}), usage=SimpleNamespace(input_tokens=321))

    notice = _notice("솔라나(SOL) 네트워크 업그레이드 지원 안내", "입출금")
    got = notices.judge(notice, NOW, lambda n: notices.ask(FakeClient(), n))
    assert seen == {
        "state": {"title": notice["title"], "categories": ["입출금"]},
        "questions": {"kind", "scope"},
        "model": notices.MODEL,
    }
    assert (got.by, got.kind, got.input_tokens) == ("jev", "suspend", 321)


def test_rules_first_means_no_jev_call_for_clear_titles():
    ask = Mock()
    notices.judge(_notice("트론(TRX) 거래유의종목 지정 안내", "거래유의"), NOW, ask)
    ask.assert_not_called()


# ── 김프 matrix의 notices ────────────────────────────────────────────────────

FEED = [
    _notice("비트코인(BTC) 입출금 일시 중지 안내", "입출금"),
    _notice("가상자산 정기실사를 위한 가상자산 입출금 일시 중지 안내", "점검", "입출금"),
    _notice("이더리움(ETH) 네트워크 계열 가상자산 5종 입출금 일시 중지 안내", "입출금"),
    _notice("코스모스(ATOM) 입출금 일시 중지 안내", "입출금"),
    _notice("업비트(Upbit) 거래소 대상 출금 주의 안내", "안내"),
    _notice("비트겟(Bitget) 거래소 대상 출금 주의 안내", "안내"),
    _notice("솔라나(SOL) 네트워크 업그레이드 지원 안내", "입출금"),
    _notice("한가위 이벤트", "이벤트"),
]


def _resp(status=200, body=None):
    response = Mock(status_code=status, ok=200 <= status < 300)
    response.json.return_value = body
    return response


def _fake_get(feed=FEED):
    def get(url, params=None, **kwargs):
        if "bithumb.com/v1/notices" in url:
            return _resp(body=feed)
        return _resp(404, {})  # 시세·호가는 이 테스트의 관심이 아니다

    return get


class FakeJev:
    calls = 0

    def system_one(self, state, questions, *, model):
        FakeJev.calls += 1
        return SimpleNamespace(answers=_answers({"suspend": 0.8, "none": 0.2}), usage=SimpleNamespace(input_tokens=400))


@pytest.fixture
def radar(monkeypatch):
    arbitrage._cache.clear()
    arbitrage._ask_jev.cache_clear()
    FakeJev.calls = 0
    recorded = []
    monkeypatch.setattr(jev_usage, "client", lambda **kw: FakeJev())
    monkeypatch.setattr(jev_usage, "over_budget", lambda budget: False)
    monkeypatch.setattr(jev_usage, "record", recorded.append)
    monkeypatch.setattr(arbitrage, "_notices_allowed", lambda: True)
    monkeypatch.setattr(arbitrage, "_now", lambda: NOW)
    flask_app = Flask(__name__)
    flask_app.config.update(TESTING=True, JEV_ENABLED=True, JEV_MONTHLY_BUDGET_USD=1.0)
    flask_app.register_blueprint(arbitrage.arb_bp)
    return flask_app, recorded


def _matrix(flask_app, symbol="BTC", get=None):
    with patch("arbitrage.requests.get", side_effect=get or _fake_get()) as mocked:
        body = flask_app.test_client().get(f"/api/arb/{symbol}/matrix").get_json()
    return body, mocked


def test_matrix_lists_risk_notices_for_the_coin_and_for_all_coins(radar):
    flask_app, recorded = radar
    body, _ = _matrix(flask_app, "BTC")
    titles = [n["title"] for n in body["notices"]]
    # BTC 자체, 전체 자산, 우리 거래소(업비트) 대상 출금 주의만 남는다. ETH 계열·ATOM·SOL·비트겟·이벤트는 빠진다.
    assert titles == [FEED[0]["title"], FEED[1]["title"], FEED[4]["title"]]
    assert body["notices"][0] == {
        "title": FEED[0]["title"],
        "url": "https://feed.bithumb.com/notice/1",
        "publishedAt": "2026-09-24 10:00:00",
        "kind": "suspend",
        "coins": ["BTC"],
        "network": False,
        "probability": None,
        "by": "rules",
        "exchange": None,
        "source": "공지 출처: 빗썸",
    }
    assert body["notices"][2]["exchange"] == "UPBIT"
    assert body["noticeStatus"] == {"status": "ok", "judge": "jev", "reason": None, "attribution": "공지 출처: 빗썸"}
    assert FakeJev.calls == 1 and recorded == [400]  # 규칙이 못 정한 SOL 공지 하나만 물었다


def test_network_family_notice_reaches_tokens_on_that_chain(radar):
    flask_app, _ = radar
    body, _ = _matrix(flask_app, "LINK")  # LINK는 이더리움 네트워크 토큰
    assert FEED[2]["title"] in [n["title"] for n in body["notices"]]


def test_jev_verdict_carries_its_probability(radar):
    flask_app, _ = radar
    body, _ = _matrix(flask_app, "SOL")
    sol = next(n for n in body["notices"] if n["title"] == FEED[6]["title"])
    assert (sol["by"], sol["kind"], sol["probability"]) == ("jev", "suspend", 0.8)


def test_cached_titles_are_not_billed_again(radar):
    flask_app, recorded = radar
    _matrix(flask_app)
    arbitrage._cache.clear()  # 공지 목록 캐시가 지나도 제목별 판정은 남는다
    _matrix(flask_app)
    assert FakeJev.calls == 1 and recorded == [400]


def test_notice_list_is_fetched_once_per_ttl(radar):
    flask_app, _ = radar
    _, first = _matrix(flask_app)
    _, second = _matrix(flask_app)
    fetched = [c for c in (*first.call_args_list, *second.call_args_list) if "notices" in c.args[0]]
    assert len(fetched) == 1 and fetched[0].kwargs["params"] == {"count": 20}


def test_jev_failure_falls_back_to_rules(radar, monkeypatch):
    flask_app, recorded = radar

    class Down:
        def system_one(self, *args, **kwargs):
            raise TimeoutError("jev timeout")

    monkeypatch.setattr(jev_usage, "client", lambda **kw: Down())
    body, _ = _matrix(flask_app, "SOL")
    sol = next(n for n in body["notices"] if n["title"] == FEED[6]["title"])
    assert (sol["by"], sol["kind"]) == ("rules", "unknown")
    assert body["noticeStatus"]["judge"] == "rules" and body["noticeStatus"]["reason"] == "unavailable"
    assert recorded == []


@pytest.mark.parametrize(("config", "reason"), [({"JEV_ENABLED": False}, "off"), ({}, "budget")])
def test_jev_off_or_over_budget_uses_rules_without_calling(radar, monkeypatch, config, reason):
    flask_app, recorded = radar
    flask_app.config.update(config)
    monkeypatch.setattr(jev_usage, "over_budget", lambda budget: True)
    body, _ = _matrix(flask_app, "SOL")
    assert body["noticeStatus"]["reason"] == reason and FakeJev.calls == 0 and recorded == []
    assert any(n["by"] == "rules" and n["kind"] == "unknown" for n in body["notices"])


def test_disallowed_source_makes_no_external_call(radar, monkeypatch):
    flask_app, _ = radar
    monkeypatch.setattr(arbitrage, "_notices_allowed", lambda: False)
    body, mocked = _matrix(flask_app)
    assert not [c for c in mocked.call_args_list if "notices" in c.args[0]]
    assert body["notices"] == [] and body["noticeStatus"]["status"] == "disabled"
    assert FakeJev.calls == 0


def test_notice_failure_does_not_break_the_matrix(radar):
    flask_app, _ = radar

    def get(url, params=None, **kwargs):
        return _resp(503, {}) if "notices" in url else _resp(404, {})

    with patch("arbitrage.requests.get", side_effect=get):
        response = flask_app.test_client().get("/api/arb/BTC/matrix")
    assert response.status_code == 200
    assert response.get_json()["notices"] == [] and response.get_json()["noticeStatus"]["status"] == "error"


def test_only_bithumb_feed_links_are_passed_through(radar):
    flask_app, _ = radar
    feed = [{**FEED[0], "pc_url": "javascript:alert(1)"}]
    body, _ = _matrix(flask_app, get=_fake_get(feed))
    assert body["notices"][0]["url"] is None


def test_notice_source_is_registered_for_local_only():
    import price_sources

    with patch("price_sources.profile", return_value="public"):
        assert price_sources.allowed("bithumb_notices") is False
    with patch("price_sources.profile", return_value="local"):
        assert price_sources.allowed("bithumb_notices") is True


# ── 평가(evals/jev_notices) ─────────────────────────────────────────────────


def test_eval_labels_agree_with_the_grader_under_the_oracle():
    from deskjev import eval_notices

    cases = eval_notices.load_cases(eval_notices.EVAL_DIR / "cases.jsonl")
    assert len(cases) >= 150 and sum(c["source"] == "real" for c in cases) == 20
    rows = eval_notices.run(eval_notices.OracleClient(cases), cases)
    jev = eval_notices.policy_summary(rows, "jev")
    assert (jev["risk_recall"], jev["precision"], jev["kind_accuracy"], jev["coins_accuracy"]) == (1, 1, 1, 1)
    rules = eval_notices.policy_summary(rows, "rules")
    assert rules["jev_share"] == 0 and rules["ece"] is None


def test_live_eval_refuses_to_run_without_a_spend_cap():
    from deskjev import eval_notices

    with pytest.raises(SystemExit):
        eval_notices.main(["--mode", "live"])
