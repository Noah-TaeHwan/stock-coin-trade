"""DART 공시 레이더(src/deskjev/disclosures + dart_radar + /api/disclosures). 네트워크 없음: Jev·DART는 가짜."""

from types import SimpleNamespace

import pytest

from deskjev import disclosures as dj


def _answers(kind: dict[str, float], risk: float):
    top = max(kind, key=kind.get)
    return {
        "kind": SimpleNamespace(choice=top, confidence=kind[top], probabilities=kind),
        "risk": SimpleNamespace(noul=risk),
    }


class FakeJev:
    """system_one을 흉내 낸다. 받은 state를 기록한다."""

    def __init__(self, kind=None, risk=0.1, tokens=520):
        self.kind, self.risk, self.tokens, self.seen = kind or {"other": 0.9, "earnings": 0.1}, risk, tokens, []

    def system_one(self, state, questions, *, model):
        self.seen.append({"state": state, "questions": set(questions), "model": model})
        return SimpleNamespace(answers=_answers(self.kind, self.risk), usage=SimpleNamespace(input_tokens=self.tokens))


# ── 규칙 표 ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("report_nm", "kind", "risk"),
    [
        ("주요사항보고서(유상증자결정)", "rights_offering", False),
        ("주요사항보고서(전환사채권발행결정)", "equity_linked", False),
        ("주요사항보고서(자기주식취득결정)", "treasury_stock", False),
        ("유무상증자결정", "rights_offering", False),
        ("무상증자결정", "capital_change", False),
        ("[기재정정]단일판매ㆍ공급계약체결", "supply_contract", False),
        ("최대주주변경을수반하는주식양수도계약체결", "control_change", False),
        ("임원ㆍ주요주주특정증권등소유상황보고서", "ownership", False),
        ("주식등의대량보유상황보고서(일반)", "ownership", False),
        ("분기보고서 (2026.07)", "periodic_report", False),
        ("증권발행실적보고서", "securities_filing", False),
        ("매출액또는손익구조30%(대규모법인은15%)이상변경", "earnings", False),
        ("[기재정정]주주총회소집결의", "shareholder_meeting", False),
        ("주권매매거래정지              (상장폐지 사유발생)", "trading_halt", True),
        ("주권매매거래정지기간변경              (회생절차 개시신청)", "trading_halt", True),
        ("주권매매거래정지해제 (액면병합 주권 변경상장)", "trading_halt", False),
        ("주권매매거래정지해제 (상장폐지에 따른 정리매매 개시)", "delisting_watch", True),
        ("기타시장안내(관리종목지정우려종목)              (주가 1,000원 미달)", "delisting_watch", True),
        ("주요사항보고서(회생절차개시신청)", "insolvency", True),
        ("파산신청기각 (취하)", "insolvency", False),
        ("채권은행등의관리절차해제", "insolvency", False),
        ("불성실공시법인지정예고              (공시번복 3건)", "unfaithful", False),
        ("불성실공시법인지정", "unfaithful", True),
    ],
)
def test_fixed_forms_are_decided_by_rules(report_nm, kind, risk):
    got = dj.judge(report_nm, "", "K")
    assert (got.kind, got.risk, got.judged_by) == (kind, risk, "rules")
    assert got.kind_prob is None and got.risk_prob is None


def test_correction_prefix_is_a_flag_and_keeps_the_original_kind():
    got = dj.judge("[기재정정]단일판매ㆍ공급계약체결", "코", "K")
    assert (got.kind, got.corrected) == ("supply_contract", True)
    assert dj.judge("[발행조건확정]증권신고서(지분증권)", "", "Y").corrected is False


def test_whitespace_runs_do_not_change_the_rule():
    assert dj.normalize("기타시장안내              (시가총액  미달)") == "기타시장안내 (시가총액 미달)"


def test_free_forms_and_unknown_forms_are_left_to_jev():
    for name in (
        "투자판단관련주요경영사항",
        "기타시장안내 (개선계획서 제출)",
        "기타경영사항(자율공시)",
        "처음보는서식",
    ):
        assert dj.by_rules(name) == (None, None), name
    # 종류는 규칙이 알지만 위험은 부제에 달린 서식
    assert dj.by_rules("조회공시요구(풍문또는보도)에대한답변(미확정) (채권자에 의한 파산신청설)") == ("inquiry", None)


def test_questions_build_with_the_installed_sdk():
    qs = dj.questions()
    assert set(qs) == {"kind", "risk"} and set(qs["kind"].criteria) == set(dj.KINDS)


def test_every_rule_kind_is_a_known_kind():
    assert {kind for _, kind, _ in dj.RULES if kind} <= set(dj.KINDS)
    assert 12 <= len(dj.KINDS) <= 20


# ── 규칙 + Jev ──────────────────────────────────────────────────────────────


def test_jev_fills_only_what_rules_left_open_and_sends_no_company_name():
    jev = FakeJev(kind={"m_and_a": 0.8, "other": 0.2}, risk=0.03)
    got = dj.judge("투자판단관련주요경영사항 (증설 투자의 건)", "코", "K", client=jev)
    assert (got.kind, got.risk, got.judged_by, got.input_tokens) == ("m_and_a", False, "jev", 520)
    assert (got.kind_prob, got.risk_prob) == (0.8, 0.03)
    sent = jev.seen[0]
    assert sent["model"] == "jev-1.13.0" and sent["questions"] == {"kind", "risk"}
    assert set(sent["state"]) == {"report_nm", "rm", "market"} and sent["state"]["market"] == "코스닥"


def test_rule_kind_is_kept_when_only_risk_is_asked():
    jev = FakeJev(kind={"other": 0.99}, risk=0.91)
    got = dj.judge("조회공시요구(풍문또는보도)에대한답변(미확정) (채권자에 의한 파산신청설)", "", "K", client=jev)
    assert (got.kind, got.kind_prob, got.risk, got.risk_prob) == ("inquiry", None, True, 0.91)


def test_decided_forms_never_call_jev():
    jev = FakeJev()
    dj.judge("주요사항보고서(유상증자결정)", "", "Y", client=jev)
    assert jev.seen == []


def test_kind_outside_the_sent_options_becomes_other():
    # 외부 API 답은 신뢰 경계 밖이다. 보낸 선택지에 없는 값은 쓰지 않는다.
    got = dj.decide("투자판단관련주요경영사항", (None, None), _answers({"<script>": 0.99}, 0.2))
    assert got.kind == "other"


def test_the_distribution_wins_over_a_mismatched_choice_label():
    answers = _answers({"earnings": 0.7, "other": 0.3}, 0.1)
    answers["kind"].choice = "other"  # sdk-python#15
    assert dj.decide("투자판단관련주요경영사항", (None, None), answers).kind == "earnings"


def test_without_jev_the_rules_fall_back_to_keywords():
    got = dj.judge("기타시장안내 (상장적격성 실질심사 사유 발생)", "", "K")
    assert (got.kind, got.risk, got.judged_by) == ("other", True, "rules")
    assert dj.judge("기타시장안내 (상장적격성 실질심사 절차 중단 안내)", "", "K").risk is False
    assert dj.judge("투자판단관련주요경영사항 (증설 투자의 건)", "", "K").risk is False


# ── 수집기(dart_radar) ────────────────────────────────────────────────────────

from datetime import date, datetime, timedelta  # noqa: E402

import dart_radar  # noqa: E402
import jev_usage  # noqa: E402


def _row(no: str, cls: str = "K", name: str = "주요사항보고서(유상증자결정)") -> dict:
    # rcept_no 앞자리와 rcept_dt가 다른 경우가 실제로 있다. 날짜는 rcept_dt만 쓴다.
    return {
        "rcept_no": no,
        "rcept_dt": "20260923",
        "corp_cls": cls,
        "corp_code": "00000001",
        "corp_name": "가나",
        "stock_code": "123456",
        "report_nm": name,
        "rm": "코",
        "flr_nm": "가나",
    }


class FakeDart:
    """list.json 쪽들을 흉내 낸다. pages는 쪽마다 행 목록, status는 모든 쪽의 상태."""

    def __init__(self, pages, status="000"):
        self.pages, self.status, self.params = pages, status, []

    def __call__(self, url, params, timeout):
        self.params.append(params)
        page = params["page_no"]
        body = {"status": self.status, "message": "msg", "total_page": len(self.pages), "list": self.pages[page - 1]}
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: body)


def test_reads_pages_until_a_stored_number_and_keeps_only_listed_companies():
    pages = [[_row("A1"), _row("A2", "E")], [_row("B1", "Y"), _row("OLD")], [_row("C1")]]
    dart = FakeDart(pages)
    items, calls = dart_radar.fetch_new(dart, "k", date(2026, 9, 23), lambda nos: {"OLD"} & set(nos))
    # 이미 본 번호가 나온 2쪽은 끝까지 읽고 멈춘다. E(기타 법인)는 빼고, 3쪽은 부르지 않는다.
    assert [i["rcept_no"] for i in items] == ["A1", "B1"] and calls == 2
    assert dart.params[0]["bgn_de"] == dart.params[0]["end_de"] == "20260923"


def test_full_sweep_reads_every_page_and_drops_duplicates():
    pages = [[_row("A1"), _row("OLD")], [_row("A1"), _row("C1")]]
    items, calls = dart_radar.fetch_new(FakeDart(pages), "k", date(2026, 9, 23), lambda nos: {"OLD"}, full=True)
    assert [i["rcept_no"] for i in items] == ["A1", "C1"] and calls == 2


def test_no_data_is_an_empty_day_and_limit_errors_raise_without_the_key():
    assert dart_radar.fetch_new(FakeDart([[]], "013"), "k", date(2026, 9, 25), lambda n: set()) == ([], 1)
    with pytest.raises(dart_radar.DartError, match="020"):
        dart_radar.fetch_new(FakeDart([[]], "020"), "k", date(2026, 9, 23), lambda n: set())

    def broken(url, params, timeout):
        raise dart_radar.requests.ConnectionError(f"{url}?crtfc_key={params['crtfc_key']}")

    with pytest.raises(dart_radar.DartError) as err:
        dart_radar.fetch_new(broken, "SECRET-KEY", date(2026, 9, 23), lambda n: set())
    assert "SECRET-KEY" not in str(err.value) and err.value.__cause__ is None


@pytest.fixture
def collector_env(monkeypatch):
    monkeypatch.setenv("DART_API_KEY", "k")
    monkeypatch.setenv("JEV_ENABLED", "true")
    monkeypatch.setenv("JEV_MONTHLY_BUDGET_USD", "1")
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-test")
    recorded, stored = [], []
    monkeypatch.setattr(jev_usage, "over_budget", lambda budget: False)
    monkeypatch.setattr(jev_usage, "record", recorded.append)
    return recorded, stored


def _collect(stored, pages):
    return dart_radar.collect(get=FakeDart(pages), known=lambda n: set(), store=stored.extend, day=date(2026, 9, 23))


def test_collect_judges_new_rows_and_calls_jev_only_for_open_forms(collector_env, monkeypatch):
    recorded, stored = collector_env
    jev = FakeJev(kind={"m_and_a": 0.9, "other": 0.1}, risk=0.02, tokens=480)
    monkeypatch.setattr(jev_usage, "client", lambda **kw: jev)
    summary = _collect(stored, [[_row("A1"), _row("A2", name="투자판단관련주요경영사항 (증설 투자의 건)")]])
    assert summary == {"day": "2026-09-23", "new": 2, "calls": 1, "jev_calls": 1} and recorded == [480]
    by_no = {row["rcept_no"]: row for row in stored}
    assert by_no["A1"]["judged_by"] == "rules" and by_no["A1"]["model"] is None
    assert (by_no["A2"]["kind"], by_no["A2"]["judged_by"], by_no["A2"]["model"]) == ("m_and_a", "jev", "jev-1.13.0")
    assert by_no["A2"]["rcept_dt"] == date(2026, 9, 23) and isinstance(by_no["A2"]["first_seen_at"], datetime)
    assert "가나" not in str(jev.seen[0]["state"])  # 회사명은 Jev에 보내지 않는다


def test_collect_falls_back_to_rules_when_jev_fails_or_budget_is_spent(collector_env, monkeypatch):
    recorded, stored = collector_env
    free = [
        _row("A1", name="기타시장안내 (상장적격성 실질심사 사유 발생)"),
        _row("A2", name="투자판단관련주요경영사항"),
    ]

    class Down:
        def system_one(self, *args, **kwargs):
            raise TimeoutError("jev timed out")

    monkeypatch.setattr(jev_usage, "client", lambda **kw: Down())
    assert _collect(stored, [free])["jev_calls"] == 0
    assert [(r["judged_by"], r["risk"]) for r in stored] == [("rules", True), ("rules", False)] and recorded == []

    stored.clear()
    monkeypatch.setattr(jev_usage, "client", lambda **kw: FakeJev())
    monkeypatch.setattr(jev_usage, "over_budget", lambda budget: True)
    assert _collect(stored, [free])["jev_calls"] == 0 and {r["judged_by"] for r in stored} == {"rules"}


def test_collect_skips_without_a_key(monkeypatch):
    monkeypatch.delenv("DART_API_KEY", raising=False)
    assert dart_radar.collect(get=None)["calls"] == 0


# ── /api/disclosures ────────────────────────────────────────────────────────


def _stored(no="20260923000001", kind="trading_halt", risk=True):
    return {
        "rcept_no": no,
        "rcept_dt": date(2026, 9, 23),
        "corp_code": "00000001",
        "corp_name": "가나",
        "stock_code": "123456",
        "corp_cls": "K",
        "report_nm": "주권매매거래정지 (상장폐지 사유발생)",
        "rm": "코",
        "flr_nm": "가나",
        "first_seen_at": datetime(2026, 9, 23, 0, 5),
        "kind": kind,
        "corrected": False,
        "risk": risk,
        "kind_prob": None,
        "risk_prob": None,
        "judged_by": "rules",
        "model": None,
        "judged_at": datetime(2026, 9, 23, 0, 5),
    }


def test_api_reads_filters_and_shows_kst_time_link_and_source(client, monkeypatch):
    seen = []
    monkeypatch.setattr(dart_radar, "query", lambda *args: seen.append(args) or [_stored()])
    body = client.get("/api/disclosures?date=2026-09-23&symbol=123456&kind=trading_halt&risk=1&limit=50").get_json()
    day = date(2026, 9, 23)
    assert seen == [(day, day, ("123456",), "trading_halt", True, 50)]
    item = body["items"][0]
    assert (item["firstSeenKst"], item["kindLabel"], item["risk"]) == ("09:05", "거래정지", True)
    assert item["url"] == "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260923000001"
    assert body["source"] == "dart" and "DART" in body["attribution"] and "투자 권유가 아닙니다" in body["notice"]
    # OpenDART 약관 제23조①: 정확성을 보장하지 않는다는 고지를 붙인다.
    assert "정확성" in body["notice"]


@pytest.mark.parametrize(
    "query_string",
    [
        "date=2026-13-01",
        "date=20260923",
        "symbol=12345",
        "symbol=00593A",
        "kind=nope",
        "risk=yes",
        "limit=0",
        "limit=501",
        "limit=x",
        "symbols=12345",
        "symbols=123456,ABCDEF",
        "symbols=" + ",".join(f"{n:06d}" for n in range(21)),
        "symbol=123456&symbols=654321",
    ],
)
def test_api_rejects_bad_input(client, monkeypatch, query_string):
    monkeypatch.setattr(dart_radar, "query", lambda *args: pytest.fail("must not query"))
    assert client.get(f"/api/disclosures?{query_string}").status_code == 400


def test_api_defaults_to_today_in_kst(client, monkeypatch):
    seen = []
    monkeypatch.setattr(dart_radar, "query", lambda *args: seen.append(args) or [])
    assert client.get("/api/disclosures").get_json()["items"] == []
    today = datetime.now(dart_radar.KST).date()
    assert seen == [(today, today, None, None, None, 200)]


def test_symbol_without_a_date_reads_the_last_30_days(client, monkeypatch):
    # 주말·휴일에 DISC 005930이 빈 화면이 되지 않게 한다.
    seen = []
    monkeypatch.setattr(dart_radar, "query", lambda *args: seen.append(args) or [_stored()])
    body = client.get("/api/disclosures?symbol=123456").get_json()
    today = datetime.now(dart_radar.KST).date()
    assert seen == [(today - timedelta(days=29), today, ("123456",), None, None, 200)]
    assert body["date"] is None and body["from"] == (today - timedelta(days=29)).isoformat()
    assert body["to"] == today.isoformat() and body["items"][0]["date"] == "2026-09-23"


def test_first_seen_shows_the_date_when_it_differs_from_the_filing_date(client, monkeypatch):
    # 지난 날짜를 나중에 수집하면 처음 본 시각이 접수일과 다르다. 그때는 날짜를 함께 보인다.
    late = {**_stored(), "first_seen_at": datetime(2026, 9, 26, 0, 24)}  # UTC → 09/26 09:24 KST
    monkeypatch.setattr(dart_radar, "query", lambda *args: [late, _stored()])
    items = client.get("/api/disclosures?date=2026-09-23").get_json()["items"]
    assert [item["firstSeenKst"] for item in items] == ["09/26 09:24", "09:05"]


def test_watchlist_symbols_read_the_last_30_days_without_duplicates(client, monkeypatch):
    # 관심 종목은 브라우저에만 있고, 화면이 여러 종목을 한 번에 묻는다(서버에 저장하지 않음).
    seen = []
    monkeypatch.setattr(dart_radar, "query", lambda *args: seen.append(args) or [_stored()])
    body = client.get("/api/disclosures?symbols=123456,654321,123456").get_json()
    today = datetime.now(dart_radar.KST).date()
    assert seen == [(today - timedelta(days=29), today, ("123456", "654321"), None, None, 200)]
    assert body["date"] is None and len(body["items"]) == 1


def test_api_is_registered_in_public_with_source_and_notice(monkeypatch):
    # 노아 판정(2026-09-26): OpenDART는 출처 표시와 정확성 비보장 고지를 붙여 공개한다.
    from app import create_app
    from settings import Settings

    public = Settings(
        profile="public",
        secret_key="p" * 40,
        session_cookie_secure=True,
        admin_email="owner@example.com",
        ratelimit_enabled=True,
    )
    monkeypatch.setattr(dart_radar, "query", lambda *args: [])
    response = create_app(public).test_client().get("/api/disclosures")
    assert response.status_code == 200
    body = response.get_json()
    assert "DART" in body["attribution"] and "정확성" in body["notice"]


@pytest.mark.parametrize(
    ("report_nm", "kind", "risk"),
    [
        # 라벨을 달며 찾은 규칙 순서 오류(evals/jev_disclosures/README.md)
        ("기업가치제고계획(자율공시) (고배당기업 표시를 위한 재공시)", "other", False),
        ("기업인수목적회사의예치ㆍ신탁계약내용변경", "other", False),
        ("유상증자최종발행가액확정 (일반공모증자-소액공모)", "rights_offering", False),
        ("증권발행결과(자율공시) (제3자배정 유상증자)", "securities_filing", False),
        ("해산사유발생(자회사의 주요경영사항)", "insolvency", False),
    ],
)
def test_rule_order_fixes_found_while_labelling(report_nm, kind, risk):
    assert dj.by_rules(report_nm) == (kind, risk)


def test_risk_is_flagged_when_either_jev_or_the_keywords_see_it():
    # 개선계획서 제출은 상장폐지 심사 절차다. Jev가 낮게 봐도 낱말이 잡는다(확률은 Jev 값 그대로).
    got = dj.decide("기타시장안내 (개선계획서 제출)", (None, None), _answers({"delisting_watch": 0.9}, 0.13))
    assert (got.risk, got.risk_prob) == (True, 0.13)
    got = dj.decide(
        "기타시장안내 (회생절차 개시신청 기각 관련 시장안내)", (None, None), _answers({"insolvency": 0.9}, 0.8)
    )
    assert got.risk is True  # 낱말은 '기각'에서 풀렸다고 보지만 Jev가 위험으로 본다


# ── evals/jev_disclosures ────────────────────────────────────────────────────


@pytest.mark.parametrize("name", ["cases.jsonl", "heldout.jsonl"])
def test_every_gold_kind_is_an_option_and_the_oracle_scores_perfectly(name):
    from deskjev.eval import load_cases
    from deskjev.eval_disclosures import EVAL_DIR, OracleClient, run, summarize

    cases = load_cases(EVAL_DIR / name)
    for case in cases:
        assert {case["kind"], *case.get("kind_alt", [])} <= set(dj.KINDS), case["id"]
        assert isinstance(case["risk"], bool) and case["stratum"] in {"fixed", "free", "risk_open"}, case["id"]
    summary = summarize(run(OracleClient(cases), cases))
    assert summary["kind_accuracy"] == 1 and summary["risk_accuracy"] == 1 and summary["errors"] == []


def test_collect_can_sweep_the_previous_day(collector_env, monkeypatch):
    _, stored = collector_env
    dart = FakeDart([[_row("A1")]])
    monkeypatch.setattr(jev_usage, "client", lambda **kw: FakeJev())
    summary = dart_radar.collect(True, get=dart, known=lambda n: set(), store=stored.extend, days_ago=1)
    yesterday = datetime.now(dart_radar.KST).date() - timedelta(days=1)
    assert summary["day"] == yesterday.isoformat() and dart.params[0]["bgn_de"] == yesterday.strftime("%Y%m%d")


def test_events_screen_keeps_the_narrow_columns_visible_and_can_show_the_filing_date():
    # 브라우저 확인은 docs/evidence에 있다. 여기서는 배치 계약(고정 배치·제목 줄바꿈·접수일 열)이 빠지지 않게 한다.
    from pathlib import Path

    frontend = Path(__file__).resolve().parents[2] / "frontend"
    html = (frontend / "events.html").read_text(encoding="utf-8")
    script = (frontend / "js" / "events.js").read_text(encoding="utf-8")
    assert ".disc-list { table-layout:fixed; }" in html and "white-space:normal" in html
    assert ".term-table.disc-list th, .term-table.disc-list td { text-align:left;" in html  # style.css보다 강하게
    assert '<th class="c-date" id="colDate" hidden>접수일</th>' in html
    assert "document.getElementById('colDate').hidden = !spanMode" in script
