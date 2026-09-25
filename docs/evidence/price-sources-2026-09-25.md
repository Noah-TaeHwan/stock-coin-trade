# 화면 시세의 출처 제어와 표시 검증 — 2026-09-25

- 대상 브랜치: `claude/wonderful-faraday-826uz8`(2-1 위에 쌓음)
- 포트폴리오 계획 Phase 2의 두 번째 묶음(2-2)이다.

## 문제

2-1의 레지스트리는 연구 데이터 수집에만 적용됐다. 화면의 시세·차트·지수·종목 목록은 여전히 코드에 박힌 소스를 모든 배포에서 불렀다.
- 주식: Yahoo Finance, 네이버 금융, KRX KIND
- 코인: 업비트, 국내외 거래소, CoinMarketCap

이 소스들은 모두 약관을 확인하지 않았다. 공개 배포에서 이 값을 보여 주면, 재배포 조건을 모르는 데이터를 공개하게 된다.

## 바꾼 것

- **`python-stock-backend/price_sources.py`**: 레지스트리를 앱과 워커가 함께 읽는다.
  - 프로필은 웹 요청이면 Flask 설정에서, 워커·CLI면 환경변수에서 가져온다.
  - `allowed(source)`: 이 소스를 부를 수 있는지
  - `label(source)`: 응답에 붙일 `source`와 `attribution`
  - 합성 시세·차트 생성
- **주식(`stock_market.py`)**: 각 외부 호출을 레지스트리가 허용할 때만 한다.
  - yfinance·네이버가 모두 꺼진 프로필(현재 public)에서는 시세·차트·지수·대시보드가 결정적 합성 소스를 쓴다. 종목 목록은 내장 목록을 쓴다.
  - 모든 응답에 `source`와 `attribution`이 붙는다.
  - 외부 소스가 실패해서 쓰는 가짜 가격은 `source: "simulated"`로 따로 표시한다. 1-1에서 public이 거부하는 대상은 이것뿐이다. 지정된 합성 소스로 체결하는 것은 허용한다.
- **코인·차익 기능(`app.py`)**: 블루프린트마다 필요한 소스를 적어 두고(`SOURCE_DEPENDENT_BLUEPRINTS`), 그 소스가 모두 허용될 때만 등록한다.
  - 코인 시세(`market_bp`), 코인 모의거래(`trade_bp`), 차익(`arb_bp`)
  - 업비트 등을 레지스트리에서 켜면 코드 변경 없이 다시 등록된다.
- **워커**
  - CoinMarketCap 랭킹과 업비트 마켓 동기화 잡은 해당 소스가 허용될 때만 등록한다.
  - 봇은 소스가 허용된 자산군만 거래한다. 주식은 합성 소스가 있어 항상 가능하다.
- **화면(`trade/stock.html`)**: 기존 "시뮬레이션" 배지를 출처에 따라 "합성 데이터" 또는 "시뮬레이션"으로 표시하고, 툴팁에 레지스트리의 출처 문구를 보여 준다.
- **합성 소스**: 지수 두 개(`^KS11`, `^KQ11`)에 지수 규모의 예시 파라미터를 추가했다.

## 결과

| 항목 | 방법 | 결과 |
|---|---|---|
| 단위 테스트 | `tests/unit/test_price_sources.py` | 9개 통과. public에서 yfinance·requests 호출이 생기면 실패하도록 막고 시세·차트·지수·목록·대시보드를 확인. local은 yfinance 라벨, 전부 실패하면 simulated 라벨 |
| 테스트가 실제로 잡는지 | `allowed()`가 항상 True를 돌려주게 바꾼 코드 | 4개 실패로 검출. 되돌린 뒤 통과 |
| 라우트 | public 스냅샷 | 71 → 58개(코인 시세·코인 모의거래·차익 13개 제외). local은 변화 없음 |
| public 스택(HTTP) | `compose.public.yml`로 기동 | 아래 |
| 브라우저 | Playwright로 public 주식 화면 | 배지 "합성 데이터"가 보이고, 툴팁은 "합성 데이터 — 실제 시세가 아닙니다"([캡처](public-synthetic-badge.png)) |
| 전체 | `ruff check .`, `pytest` | 174개 통과 |

public 스택 결과:
- `/api/stocks/quote?symbol=005930`: `source: synthetic`과 출처 문구가 붙고, `simulated` 키는 없다.
- 차트는 합성 일봉 34개, 지수 두 개도 `synthetic`이다.
- `/api/crypto/market-list`, `/api/trade/hold`, `/api/arb/snapshot`은 모두 404다.
- 모의 매수가 합성 가격 72,527원으로 체결되고 `simulated: false`다.
- 워커 로그에는 `run_bot_trading_round`만 등록됐다.

## 달라진 동작

- local(기본): 외부 소스를 그대로 쓴다. 응답에 `source`·`attribution` 키가 추가될 뿐이다.
- public
  - 주식 시세·차트·지수·대시보드는 합성 데이터이고, 종목 목록은 내장 14종목이다.
  - 코인 시세·코인 모의거래·차익 화면의 API가 없다.
  - 워커는 봇의 주식 거래만 한다.
- `/api/stocks/list`의 `source`가 `"KRX"` 대신 `krx_kind` 또는 `builtin`이다.

## 검증하지 못한 것

- public 메뉴 정리. 코인·대체자산 메뉴가 아직 보이지만 API는 404다. 메뉴 재구성은 Phase 7에서 한다.
- 대시보드·보유자산 화면의 출처 배지. 주식 화면에만 표시했고, 나머지는 API 응답의 `source`로만 확인할 수 있다.
- 합성 시세는 하루 단위로 결정되므로 장중에는 가격이 바뀌지 않는다(의도한 동작).
