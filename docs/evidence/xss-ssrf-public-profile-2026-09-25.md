# XSS·SSRF·공개 프로필 검증 — 2026-09-25

- 대상 브랜치: `claude/wonderful-faraday-826uz8`(1-1, 1-2 위에 쌓음)
- 포트폴리오 계획 Phase 1의 세 번째 묶음(1-3)이다.

## 고친 문제

| 문제 | 이전 동작 |
|---|---|
| 저장형 XSS | 익명 사용자가 Qdrant 지식 베이스에 문서를 추가할 수 있었다. 그 제목·본문·분류가 검색·목록·AI 분석 근거 화면에 `innerHTML`로 그대로 들어가서, 모든 방문자의 브라우저에서 스크립트가 실행됐다. AI 답변을 바꾸는 `markdownToHtml`도 이스케이프를 하지 않았다. |
| 그 밖의 비이스케이프 삽입 | 종목명·코인명·섹터·API 키 이름·오류 메시지 등 서버 값을 11개 파일에서 이스케이프 없이 넣었다. |
| 인라인 핸들러 주입 | `onclick="selectCoin('${값}')"` 형태가 있었다. HTML 이스케이프만으로는 막을 수 없다(브라우저가 속성값의 `&#39;`를 `'`로 되돌린 뒤 JS로 해석). `encodeURIComponent`도 `'`를 인코딩하지 않는다. |
| 복사된 이스케이프 함수 | 같은 함수가 9개 파일에 10벌 있었다. |
| 크롤러 SSRF | `requests`가 리디렉션을 모두 따라간 뒤 최종 주소만 검사해서, 중간 홉의 내부 주소(예: `169.254.169.254`)에는 이미 요청이 간 뒤였다. |
| 공개 배포 노출면 | 브로커 실습(KIS·KB·Alpaca·AWS SSM·거래소), 호스트 Docker socket을 쓰는 LEAN, 외부 DB 기본 DSN을 쓰는 OHLCV, 검토하지 않은 선물 손익 모델이 모든 배포에 등록됐다. |
| CORS 접두사 일치 | flask-cors는 `"http://localhost:*"`를 앞에서부터 맞추는 정규식으로 다룬다. 그래서 `http://localhost.evil.example`도 자격증명과 함께 허용됐다. `127.0.0.1`의 `.`도 아무 문자와 일치했다. |

## 바꾼 것

- **프런트**
  - `common.js`에 공용 함수 세 개를 두었다.
    - `escapeHtml`: HTML 이스케이프
    - `jsArg`: JSON 문자열 리터럴로 만든 뒤 속성용 이스케이프. 인라인 핸들러 인자에 쓴다.
    - `safeHttpUrl`: http·https 주소만 허용한다.
  - 복사본 10벌은 공용 함수를 쓰게 바꿨다.
  - 서버 값을 넣는 곳을 모두 이스케이프했다: `common.js`, `order.js`, `stock.js`, `alternatives.js`, `hold_crypto.js`, `api-keys.js`, `pine.js`, `error-analysis.js`, `quant-lab.js`, `analysis.js`, `index.html`, `ohlcv-db.html`.
  - `markdownToHtml`은 먼저 이스케이프하고, 그다음 제목·굵게·기울임·목록만 태그로 바꾼다.
  - KRX 뉴스 링크는 http·https만 허용한다.
- **Qdrant**
  - 문서 추가는 관리자 전용이다(403).
  - 제목은 200자, 분류는 50자로 자른다.
  - 검색 `limit`이 숫자가 아니면 500 대신 400을 돌려준다.
- **크롤러**
  - `allow_redirects=False`로 한 홉씩 따라가고, 요청 전에 홉마다 공개 주소인지 검사한다. 상대 경로는 `urljoin`으로 처리한다. 리디렉션은 최대 5번이다.
  - DNS 재바인딩(검사 후 다른 IP로 해석)은 막지 못한다. 대신 public 프로필은 이 라우트를 등록하지 않는다.
- **공개 프로필**
  - public은 블루프린트 12개를 등록하지 않는다.
    - 브로커 실습 9개
    - `ai_sheet`(크롤러·LEAN·Docker socket)
    - `ohlcv_db`(외부 DB 기본 DSN)
    - `alternatives`(선물 손익 모델 미검토)
  - 라우트 수는 local 126개, public 70개다. 둘 다 스냅샷으로 고정했다(`tests/unit/snapshots/routes_{local,public}.txt`).
- **CORS**
  - local 개발 출처는 정확한 정규식(`^http://localhost(:\d+)?$`, `^http://127\.0\.0\.1(:\d+)?$`)으로 맞춘다.
  - public의 `/api/*`는 교차 출처를 허용하지 않는다(프런트와 같은 출처로 서비스).
  - `/openapi/*`는 모든 출처를 받지만 자격증명은 허용하지 않는다.

## 결과

| 항목 | 방법 | 결과 |
|---|---|---|
| 브라우저 XSS | Playwright(Chromium 1194) + 정적 서버. API 응답을 `<img src=x onerror=...>` 공격 문자열로 바꿔치기해 지식 검색·지식 데이터셋 화면을 연다 | **수정 후**: 실행 0회, 삽입된 `<img>` 0개, 공격 문자열이 글자로 표시됨, 대화상자 0개 |
| 같은 검사의 대조군 | 같은 스크립트를 `origin/main` 프런트에 실행 | **수정 전**: 지식 검색 5회, 지식 데이터셋 7회 실행 |
| 마크다운 | `markdownToHtml('## 제목\n**굵게** <img ...>')` | 제목·굵게만 태그가 되고 `<img>`는 `&lt;img ...&gt;` 글자로 남음 |
| 서버 단위 테스트 | `tests/unit/test_public_profile.py` | 21개 통과 |
| 테스트가 실제로 잡는지 | CORS를 옛 접두사 패턴으로 / Qdrant 관리자 검사 제거 / 홉 검사 없이 리디렉션 따라가기로 바꾼 코드 | 각각 2개·1개·3개 실패로 검출. 되돌린 뒤 통과 |
| 전체 | `ruff check .`, 포맷 검사, `pytest`, 모든 JS `node --check` | 단위 137개 통과. MariaDB·PostgreSQL 통합 14개 통과 |

## 달라진 동작

- local
  - 비관리자는 Qdrant에 문서를 추가할 수 없다(403). 지식 데이터셋 화면의 추가 버튼은 관리자만 쓸 수 있다.
  - `localhost`와 비슷하게 생긴 출처에는 CORS 헤더를 주지 않는다.
- public
  - 위 12개 블루프린트의 경로가 404다.
  - `/api/*`는 교차 출처 CORS 헤더를 주지 않는다.
- 화면에서 서버 값에 섞인 `<`·`&` 같은 문자가 태그로 해석되지 않고 글자 그대로 보인다.

## 검증하지 못한 것

- 57개 화면 전체의 시각 회귀. 이번 검사는 저장형 XSS 경로인 지식 검색·지식 데이터셋 두 화면만 브라우저로 확인했다. 나머지는 템플릿의 이스케이프를 코드로 확인했고, JS 문법만 검사했다.
- public 프로필에서 빠진 경로를 가리키는 메뉴 정리. 메뉴 재구성은 Phase 7에서 한다.
- DOMPurify 도입(계획상 should). 지금은 "먼저 이스케이프, 그다음 제한된 마크다운" 방식이다.
