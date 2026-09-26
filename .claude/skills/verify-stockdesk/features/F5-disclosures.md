# F5 공시 레이더와 관심 종목 공시

방문자가 금융감독원 DART 공시 목록과 유형·위험 표시를 로그인 없이 본다. 주식 화면에서 ★로 고른 관심 종목의 최근 30일 공시를 모아 보고, 공시 줄에서 그 종목의 백테스트로 간다. 공개 사이트에서도 켜져 있다(노아 판정 2026-09-26: 출처 표시·정확성 비보장 고지).

## 하위 기능

- `f5-list`: `GET /api/disclosures`(오늘) 또는 `?date=YYYY-MM-DD`가 200. 응답의 `attribution`에 "DART"가, `notice`에 "정확성"이 들어 있다.
- `f5-watchlist`: `?symbols=005930,000660`(6자리 최대 20개, 중복 제거)이 두 종목의 최근 30일 공시만 준다. 관심 종목은 서버에 저장하지 않는다.
- `f5-backtest-link`: 공시 줄의 "백테스트" 링크가 `/quant.html?symbol=<코드>`로 가고, 퀀트 랩 종목 칸이 채워진다.

## 사용자 경로

- 화면: `/events.html`(명령 `DISC`), 필터의 "★ 내 관심 종목" 버튼(`?watch=1`), 오른쪽 "읽는 법"의 고지.
- API: `GET /api/disclosures?date=&symbol=&symbols=&kind=&risk=&limit=`.
- 관심 종목: 브라우저 `localStorage.stockWatchlist`(주식 화면 ★).

## 주행

전제 조건: `scripts/verify/stack.sh doctor`가 `ok`. 검증 스택은 DART 수집(worker)을 띄우지 않으므로 공시 행이 없다. 필요하면 검증 스택 MariaDB에 `[검증용 예시]` 제목의 행을 몇 개 넣고 주행 뒤 지운다.

- **API.** `curl -s 'http://127.0.0.1:3334/api/disclosures?symbols=005930,000660'`가 두 종목 행만 주고, `notice`에 "정확성"이 있다.
- **화면.** 쿠키 없는 Playwright로 `localStorage.stockWatchlist`에 `["005930","000660"]`를 넣고 `/events.html?watch=1`을 연다. 제목이 "내 관심 종목 2개 최근 30일 공시"이고, 다른 종목 행이 없으며, 행마다 백테스트 링크가 있다. 링크를 누르면 `/quant.html?symbol=…`의 종목 칸이 채워진다. 캡처는 `s3-watchlist-disclosures.png`.

## 함정

- `symbol`과 `symbols`를 함께 보내면 400이다.
- 관심 종목이 비어 있으면 서버를 부르지 않고 "주식 화면에서 ★…" 안내를 보여 준다.
- 공개 서버의 수집은 SSM `dart-api-key`가 있을 때만 worker에 걸린다. 주말·휴일에는 오늘 목록이 비는 것이 정상이다(OpenDART 013 "조회된 데이터 없음").
- 검증용 예시 행은 주행 뒤 `DELETE FROM dart_disclosures WHERE report_nm LIKE '[검증용 예시]%'`로 지운다.
