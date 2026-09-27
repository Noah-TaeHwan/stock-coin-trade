# F5 공시 레이더와 관심 종목 공시

방문자가 금융감독원 DART 공시 목록과 유형·위험 표시를 로그인 없이 본다. 주식 화면에서 ★로 고른 관심 종목의 최근 30일 공시를 모아 보고, 공시 줄에서 그 종목의 백테스트로 간다. 공개 사이트에서도 켜져 있다(노아 판정 2026-09-26: 출처 표시·정확성 비보장 고지).

## 하위 기능

- `f5-list`: `GET /api/disclosures`(오늘) 또는 `?date=YYYY-MM-DD`가 200. 응답의 `attribution`에 "DART"가, `notice`에 "정확성"이 들어 있다.
- `f5-watchlist`: `?symbols=005930,000660`(6자리 최대 20개, 중복 제거)이 두 종목의 최근 30일 공시만 준다. 관심 종목은 서버에 저장하지 않는다.
- `f5-backtest-link`: 공시 줄의 "백테스트" 링크가 `/quant.html?symbol=<코드>`로 가고, 퀀트 랩 종목 칸이 채워진다.
  - 링크는 `/api/quant/overview`의 `backtestable` 종목(최근 3년 60봉 이상) 줄에만 붙는다. 공개 사이트에서는 000660·005930이다.
  - 다른 종목 줄에는 링크가 없다. 따라가 봐야 "시세가 부족합니다"로 끝나기 때문이다.
  - 공개 사이트는 백테스트 결과 위에 "합성 데이터 · 실제 시세 아님" 배지를 붙인다.
- `f5-cap`: 한 번에 최대 500건이다. 500건이 차면 제목에 "(최대 500건)"을 붙인다.

## 사용자 경로

- 화면: `/events.html`(명령 `DISC`), 필터의 "★ 내 관심 종목" 버튼(`?watch=1`), 오른쪽 "읽는 법"의 고지.
- API: `GET /api/disclosures?date=&symbol=&symbols=&kind=&risk=&limit=`.
- 관심 종목: 브라우저 `localStorage.stockWatchlist`(주식 화면 ★).

## 주행

전제 조건: `scripts/verify/stack.sh doctor`가 `ok`. 검증 스택은 DART 수집(worker)을 띄우지 않으므로 공시 행이 없다.

- **API.** `python3 scripts/verify/f5_disclosures.py`. `[검증용 예시]` 행 3개(005930·000660·대조 035720)를 넣는다. 그 뒤 출처·"정확성" 고지, 중복을 넣은 `symbols`가 두 종목만 주는지, 잘못된 코드·`symbol`+`symbols`·21개가 400인지 확인하고 예시 행을 지운다(남은 0개 확인).
- 화면용 예시 행 넣기·지우기: `python3 -c 'import sys; sys.path.insert(0,"scripts/verify"); import f5_disclosures as f; f._seed()'` / 같은 명령에서 `f._seed()` 대신 `print(f._cleanup())`(0이 나와야 한다).
- **화면.** 쿠키 없는 Playwright로 `localStorage.stockWatchlist`에 `["005930","000660"]`를 넣고 `/events.html?watch=1`을 연다. 제목이 "내 관심 종목 2개 최근 30일 공시"이고, 다른 종목 행이 없으며, 행마다 백테스트 링크가 있다. 링크를 누르면 `/quant.html?symbol=…`의 종목 칸(`[data-symbol]`)이 채워진다.
  - 캡처: `s3-watchlist-disclosures.png`, 그리고 `[data-symbol]` 칸이 보이게 찍은 퀀트 화면(요소 캡처).
  - 화면에서 읽은 값은 `ui/f5-ui.json` 한 파일에 저장한다: `location.href`(3334인지), 제목 텍스트, 행 종목코드 목록, 클릭 뒤 `[data-symbol]` 값. 이 파일에 없는 값은 "미검증"으로 보고한다.
  - (선택) 빈 목록 안내는 `stockWatchlist`에 `[]`를 넣고 `s3-watchlist-empty.png`로 남긴다.

## 함정

- `symbol`과 `symbols`를 함께 보내면 400이다.
- 관심 종목이 비어 있으면 서버를 부르지 않고 "주식 화면에서 ★…" 안내를 보여 준다.
- 공개 서버의 수집은 SSM `dart-api-key`가 있을 때만 worker에 걸린다. 주말·휴일에는 오늘 목록이 비는 것이 정상이다(OpenDART 013 "조회된 데이터 없음").
- 서버는 수집을 시작한 날부터의 공시만 가진다. 새 서버에서는 "최근 30일" 조회가 거짓으로 비어 보인다. `docs/deploy/aws.md` 5절처럼 최근 30일 영업일을 한 번 채운다.
- 공개 서버에서 링크 조건을 볼 때는 공시가 많은 영업일(`?date=`)과 `?symbol=005930`·`?symbol=035420`을 함께 연다. 링크는 앞의 둘에만 있어야 한다. 기록: `docs/evidence/verify-followup-2026-09-27.md`.
- 검증용 예시 행은 주행 뒤 `DELETE FROM dart_disclosures WHERE report_nm LIKE '[검증용 예시]%'`로 지운다.
