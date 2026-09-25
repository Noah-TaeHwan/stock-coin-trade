# 터미널 UI 마감 검증 — 2026-09-25

이 기록의 대상은 브랜치 `claude/quirky-einstein-v1s739`의 커밋 `7292111`부터 이 문서를 추가한 커밋까지이고, 기준은 `main`의 `2e7bab4`([터미널형 UI 전환](terminal-ui-2026-09-24.md))이다. 백엔드와 DB 스키마는 바꾸지 않았다.

## 무엇을 바꿨나

| 영역 | 변경 |
|---|---|
| 페이지 키트 | `frontend/css/style.css`에 간격·글자 토큰과 공통 틀을 추가했다. 한 줄 제목 바(`.term-pagehead`), 단계 바, 화면 틀 5종(도구·로그·차트·2열·3열), KPI 스트립, 결과 콘솔, 문서 틀(목차 레일 + 읽기 폭)이다. 페이지마다 복사돼 있던 카드 스타일 블록은 지우고 이 키트로 합쳤다. |
| 모서리 | 4px를 넘는 하드코딩 반경과 Tailwind `rounded-*`를 토큰(2~4px)으로 바꿨다. 원형 점(50%)만 남겼다. |
| 색 | 옛 한국식 색을 기계적으로 치환하면서 뒤집힌 등락 색을 바로잡았다(KIS 차트 `.up/.down`, Pine 랩 `.buy/.sell`, 대체자산 호가 머리글, 기업분석 이익 막대). 보라·인디고·네이비·그라데이션·파란 글로우와 장식용 하늘색 테두리는 토큰으로 바꿨다. 차트 선 색은 `TERM_PALETTE`/`TERM_MA_COLORS`로 통일했고, 상승 초록과 헷갈리던 라임은 회색으로 바꿨다. |
| 화면 밀도 | 테스트 9개 화면은 좌측 설정 레일과 우측 2열 테스트 목록(버튼 \| 결과)으로 바꿨다. 로그 6개 화면은 KPI 스트립, 높이를 채우는 그리드, 우측 상세 JSON으로 바꿨다. 차트 2개 화면은 좌측 컨트롤과 차트로 나눴다. 실계좌 연습, AI, 퀀트, Pine 랩, 대체자산 화면도 다열 패널로 재배치했다. 대시보드 모니터는 20행까지 채운다. |
| 학습 문서 | 학습 17개 화면, Pine 가이드, Open API 화면에 목차 레일(스크롤 위치 표시)과 940px 읽기 폭을 적용했다. 1100px 이하에서는 목차가 본문 위로 올라간다. |
| HTS 흡수 | 화면번호(`0130` 관심, `0101` 호가, `0400` 차트, `0600`·`4990` 주문, `0919` 기업분석)는 명령줄 명령으로 옮겼다. `HTS`를 입력하면 이 목록이 뜬다. 주식 화면 하단 도크에는 `KIS·KB 원본` 탭(시세·호가·차트 원본 응답 로그)과 `메모` 탭(기존 `hts-memos` API)을 추가했다. `hts.html`은 주식 화면으로 보내는 리다이렉트만 남겼다. `Alt+8`은 KIS 실습으로 바꿨다. |
| 회귀 방지 | `scripts/check_terminal_ui.py`를 추가했다. 4px를 넘는 반경, `rounded-*`, 금지 색, 뒤집힌 등락 색 쌍을 찾으면 종료 코드 1을 반환한다. `scripts/embed_curriculum.py --check`는 생성 결과와 페이지를 실제로 비교한다. 이 검사 없이는 생성기 CSS가 밝은 색으로 남아 있어도 다시 생성할 때까지 드러나지 않았다. |

드로잉(차트 위 그리기) 기능은 원본과 포크의 전체 히스토리에 구현된 적이 없다. 학습 문서의 TradingView "그리기 도구" 설명만 있다. 그래서 이번 범위에서 뺐다.

## 실행 환경

- 클라우드 작업 컨테이너: Docker 29.3.1, Compose v5.1.1, x86_64
- 스택: [PORTFOLIO_LOCAL.md](../../PORTFOLIO_LOCAL.md)의 Compose 절차로 실행했다. 커밋하지 않은 임시 오버라이드를 함께 썼다: 프런트엔드 bind mount와 백엔드 이미지의 프록시 CA 주입. [이전 기록](terminal-ui-2026-09-24.md)과 같은 방식이다.
- 비교 기준(전): 같은 스택의 백엔드 앞에 `2e7bab4`의 `frontend/`를 따로 띄워 같은 스크립트로 측정했다.
- 브라우저: Playwright 1.56.1 + Chromium, 로캘 `ko-KR`, 시간대 `Asia/Seoul`
- 계정: 로컬 합성 테스트 계정 `terminal` 1개. 앱 내부 모의 주문만 실행했다.
- 실행하지 않은 것: KIS·KB·Alpaca 주문과 실제 계좌, AWS

## 검사 결과

### 정적 검사

| 항목 | 방법 | 결과 |
|---|---|---|
| JS 문법 | `node --check`로 `frontend/js/*.js` 전체 검사 | 통과 |
| Python | `python3 -m py_compile scripts/*.py` | 통과 |
| UI 규칙 | `python3 scripts/check_terminal_ui.py` | 위반 0 |
| 커리큘럼 임베드 | `python3 scripts/embed_curriculum.py --check` | 차이 0 |
| KIS MCP 경계 | `python3 scripts/test_kis_mcp.py` | 통과 |
| 공백 | `git diff --check` | 통과 |

### 전 화면 점검

리다이렉트만 남은 `hts.html`을 뺀 56개 화면을 각각 열고, 계산된 스타일로 측정했다.

| 항목 | 전 (`2e7bab4`, 1440×900) | 후 (1440×900) | 후 (390×844) |
|---|---|---|---|
| 반경이 4px를 넘는 요소(원형 제외) | 1,562 | 0 | 0 |
| 글자·배경 대비 3:1 미만 | — | 0 | 0 |
| 문서 가로 넘침 | — | 0 | 0 |
| 페이지 스크립트 오류 | — | 0 | 0 |
| 한 화면(900px)에 들어가는 화면 수 | 18 / 56 | 40 / 56 | — |
| 56개 화면 스크롤 길이 합 | 127,432px | 100,956px (−20.8%) | — |

전후 스크롤 길이(1440×900, px):

| 화면 | 전 | 후 |
|---|---|---|
| 테스트: alpaca-test / broker-api-test / kb-api-test | 1,460 / 1,710 / 1,624 | 900 / 900 / 900 |
| 테스트: aws-broker-api-test / aws-alpaca-test / kis-order-flow-test | 1,449 / 1,329 / 1,140 | 900 / 900 / 900 |
| 로그: kis·kb·alpaca-api-history | 1,173 / 1,162 / 1,162 | 900 / 900 / 900 |
| 차트: kis-chart / kb-chart | 1,132 / 1,263 | 900 / 900 |
| pine-script-lab | 2,007 | 900 |
| kis-real-trading-practice | 1,307 | 900 |
| quant | 2,054 | 1,071 |
| 학습: kis-test / kb-securities / tradingview-pine | 11,901 / 11,725 / 17,278 | 9,928 / 9,092 / 12,766 |

테스트·로그·차트 화면은 이제 모두 한 화면에 들어간다. 학습 문서의 스크롤 길이가 줄어든 것은 글을 뺐기 때문이 아니다. 여백과 제목 크기를 줄이고 읽기 폭을 정했기 때문이다.

대비 점검은 그라데이션 배경, canvas(차트), SVG 안의 글자를 계산하지 못한다. 이 부분은 스크린샷을 직접 보고 확인했다.

### 기능

| 항목 | 방법 | 결과 |
|---|---|---|
| 주식 모의 매수 | 카카오 수량 1 → BUY | "매수 완료". 체결 도크 최상단에 `카카오 035720 BUY 1주 37,000원` |
| 코인 모의 매수 | XRP 10,000원 → 매수 버튼 | `POST /api/trade/order/buy` 200. 매수 가능 KRW 99,916,000 → 99,906,000. 보유 도크와 주문 내역에 XRP |
| 등락 색 | KIS 차트 `.up/.down`, Pine 랩 `.buy/.sell` 계산 색 | 초록 `rgb(0,210,106)` / 빨강 `rgb(255,77,77)` |
| CVD 팔레트 | `CVD` 입력 후 대체자산 호가 머리글 | `--up` `#3D9BFF`. 매수 머리글 파랑, 매도 머리글 빨강 |
| 학습 문서 목차 | kis-test 목차 19개 중 6번째 클릭 | 해당 절이 상단 85px로 이동하고 목차 표시가 옮겨간다. 커리큘럼 하위 항목을 누르면 접힌 절이 열린다. |
| HTS 리다이렉트 | `/hts.html` 열기 | `/trade/stock.html?focus=watch`로 이동, 관심 탭 선택 |
| 화면번호 명령 | `0130`, `0101`, `0400`, `0600`, `4990`, `0919`, `RAW` 입력 후 Enter | 7개 모두 예상 화면으로 이동. `?focus=order`는 수량 입력에 포커스 |
| `HTS` 명령·`Alt+8` | 명령줄 `HTS`, 단축키 `Alt+8` | 화면번호 목록 표시 / `/learning/kis-regist.html` 이동 |
| KIS·KB 원본 탭 | `KIS 조회`, `KB 조회` | 키 파일이 없어 HTTP 502. 탭은 오류 상태와 원인(`kis.key`·`kb.key` 없음)을 보여주고 요청·응답 JSON을 로그로 쌓는다. |
| 메모 탭 | 삼성전자 메모 저장 → 새로고침 | "저장했습니다." 새로고침 후 내용 유지, 메모 목록 1행 |

## 화면

- [테스트 화면 전](terminal-polish-test-before.png) → [후](terminal-polish-test.png) (alpaca-test)
- [로그 화면](terminal-polish-log.png) (kis-api-history)
- [Pine 랩](terminal-polish-pine-lab.png)
- [주식 화면 KIS·KB 원본 탭](terminal-polish-stock-broker.png)
- [학습 문서 전](terminal-polish-doc-before.png) → [후](terminal-polish-doc.png) (kis-test)
- [390px 학습 문서](terminal-polish-mobile-doc.png) (kis-regist)

## 남은 문제와 범위

- `code.highcharts.com`은 이 작업 컨테이너에서 403으로 막혀 있다. 그래서 보유자산 화면의 Highcharts 차트는 이번에도 그려지는 것을 보지 못했다. 색은 `termColors()`에서 가져오도록 바꿨다.
- KIS·KB 원본 탭과 KIS·KB 차트는 로컬에 브로커 키가 없어 502 오류 상태만 확인했다. 정상 응답의 요약 표시는 실제 키로 확인해야 한다.
- 대시보드 코인 모니터는 20행까지 채우게 했지만, 로컬 백엔드가 11개 마켓만 돌려줘 11행이다.
- 드로잉 기능은 위 이유로 범위에서 뺐다. 라이트 모드와 학습 문서 내용 재작성도 범위 밖이다.
