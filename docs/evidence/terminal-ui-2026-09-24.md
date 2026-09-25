# 터미널형(Bloomberg·TWS) UI 검증 — 2026-09-24

이 기록은 브랜치 `claude/jolly-knuth-mu6vxr`의 커밋 `2b3e4ce`부터 이 문서를 추가한 커밋까지를 대상으로 한다. 기준은 `main`의 `dcb9e08`이다. 백엔드 코드는 바꾸지 않았다.

## 무엇을 바꿨나

| 영역 | 변경 |
|---|---|
| 디자인 토큰 | `frontend/css/style.css`의 기존 변수 이름(`--bg`, `--surface`, `--accent`, `--up` 등)은 그대로 두고 값만 다크로 바꿨다(검정 바탕, 앰버 강조, 상승 초록·하락 빨강). 패널·도크·호가 사다리·티커 컴포넌트를 추가했다. |
| 공통 셸 | `frontend/js/common.js`의 헤더를 3단으로 바꿨다: 명령줄(`<GO>`, `/` 포커스), 기능키(`Alt+1~9`), 티커 테이프. 푸터는 연결 상태 바로 바꿨다. 차트 옵션·등락 색 헬퍼를 추가했다. |
| 핵심 화면 | 대시보드는 MON 마켓 모니터로, 주식·코인 화면은 TWS형 3열 워크스페이스로 재배치했다. 구성: 종목 목록 / 시세·차트·하단 도크 / 주문 티켓·호가 사다리. |
| 나머지 화면 | 페이지별 스타일에 남아 있던 밝은 배경·테두리·본문 색을 다크 토큰에 대응시켰다. HTS 시뮬레이터와 퀀트 랩은 개별 조정했다. |
| 차트·그리드 | lightweight-charts 6곳은 공통 다크 옵션을 쓴다. AG Grid는 공식 `data-ag-theme-mode="dark"`를 쓴다. Highcharts는 전역 다크 기본값을 쓴다. |
| 접근성 | 명령줄에 `CVD`를 입력하면 상승 색이 파랑으로 바뀐다. Bloomberg의 색각이상 대응 팔레트 방식을 따른 것이고, 선택은 브라우저에 저장된다. |

디자인 근거: [Bloomberg UX — Designing the Terminal for color accessibility](https://www.bloomberg.com/ux/2021/10/14/designing-the-terminal-for-color-accessibility/)에서 두 원칙을 가져왔다. 앰버는 비의미 정보에만 쓰고, 등락은 의미 색으로만 표시한다. [IBKR TWS Mosaic](https://www.ibkrguides.com/traderworkstation/mosaic-layout.htm)에서는 색으로 연결된 창과 하단 탭 구조를 가져왔다. [AG Grid 테마 모드](https://www.ag-grid.com/javascript-data-grid/theming-colors/)는 공식 방식 그대로 썼다. React 기반 디자인 시스템(Blueprint 등)은 정적 HTML 57개를 전부 다시 써야 해서 도입하지 않았다.

이전 기록의 남은 문제도 이번 변경으로 해결했다. [로컬 실행 검증](README.md)에 적힌 주식 거래 내역 수량과 평균단가의 `rgba(255,255,255,0.7)` 글자색 문제다. 두 값은 토큰 색으로 바꿨고, 해당 문자열은 저장소에 남아 있지 않다.

## 실행 환경

- 클라우드 작업 컨테이너: Docker 29.3.1, Compose v5.1.1, x86_64
- [PORTFOLIO_LOCAL.md](../../PORTFOLIO_LOCAL.md)의 `.env.portfolio` 생성 절차와 Compose 명령으로 네 서비스를 실행했다.
- 이 컨테이너에서만 저장소 밖 임시 오버라이드 한 개를 함께 썼다. 커밋하지 않았다.
  - 프런트엔드 bind mount: 수정한 정적 파일을 바로 반영하기 위해서다.
  - 백엔드 이미지에 작업 환경의 HTTPS 프록시 CA 주입: 사내 프록시가 없는 로컬 PC에서는 필요 없다.
- 브라우저: Playwright 1.56.1 + Chromium, 로캘 `ko-KR`, 시간대 `Asia/Seoul`
- 계정: 로컬 합성 테스트 계정 `terminal` 1개. 앱 내부 모의 주문만 실행했다.
- 실행하지 않은 것: KIS·KB·Alpaca 주문과 실제 계좌, AWS

## 검사 결과

| 항목 | 방법 | 결과 |
|---|---|---|
| JS 문법 | `node --check frontend/js/*.js` | 전부 통과 |
| Python 회귀 | `python3 -m py_compile python-stock-backend/*.py` | 통과 (백엔드 변경 없음) |
| KIS MCP 경계 | `python3 scripts/test_kis_mcp.py` | 통과 |
| 커리큘럼 임베드 | `python3 scripts/embed_curriculum.py --check` | 통과, 파일 변경 없음 |
| 공백 | `git diff --check` | 통과 |
| 옛 등락 색 잔존 | `#E11D48`, `#2563EB`, `#1565C0`, `rgba(255,255,255,0.7)` 검색 | `frontend/`에 0건 |
| 57개 화면 1440×900 | Playwright로 각 화면을 열고 계산 색으로 글자·배경 대비를 전수 점검 | 대비 3:1 미만 0건, 가로 넘침 0, 모든 화면 바탕 검정 |
| 57개 화면 390×844 | 같은 방법 | 대비 3:1 미만 0건, 문서 가로 넘침 0 |
| 명령줄 | `STK 005930`, `000660`, `BTC`, `CRY ETH`, `KRW-XRP`, `HOLD`, `hist`, `키 발급`, `삼성`, `KIS`, `QNT` 입력 후 Enter | 각각 주식·코인·보유·이력·학습·퀀트 화면으로 이동. `삼성`은 주식 검색 결과 2건을 열었다. |
| 단축키·도움말 | `Alt+2`, `/`, `HELP` | 주식 화면 이동, 명령줄 포커스, 명령 33개 목록 표시 |
| CVD 팔레트 | `CVD` 입력 후 새로고침 | `--up`이 `#00D26A`에서 `#3D9BFF`로 바뀌고 새로고침 후에도 유지 |
| 주식 모의 매수 | 주문 티켓에서 카카오 1주 BUY | "매수 완료". 포지션 도크 수량 0 → 1, 체결 도크 최상단에 BUY 1주 37,000원 |
| 코인 모의 매수 | 주문 티켓에서 XRP 10,000원 BUY | 매수 가능 KRW가 10,000원 감소, 보유 도크에 XRP 표시 |
| 로그아웃 | 헤더 로그아웃 후 실전연습 메뉴 열기 | 비로그인 잠금 화면 표시 |
| 호가 사다리 | 주식(합성 5단계)·코인(업비트 8단계) | 매도 위, 현재가 가운데, 매수 아래로 각각 10행·16행 |

대비 점검의 한계: 그라데이션 배경, canvas(차트), SVG 안의 글자는 계산하지 않았다. 이 부분은 스크린샷을 직접 보고 확인했다.

## 화면

- [대시보드 MON](terminal-dashboard.png)
- [주식 워크스페이스](terminal-stock.png)
- [코인 워크스페이스](terminal-coin.png)
- [학습 화면 예시](terminal-learning.png)
- [390px 모바일 대시보드](terminal-mobile.png)

## 남은 문제와 범위

- `code.highcharts.com`은 이 작업 컨테이너의 외부 접속 정책에서 403으로 차단됐다. 그래서 보유자산 화면의 Highcharts 원형·막대 차트는 렌더링을 확인하지 못했다. 전역 다크 옵션은 Highcharts가 로드된 경우에만 적용되도록 방어했다.
- 다음 콘솔 오류는 로컬 범위의 기존 제약이라 이번 변경과 무관하다.
  - KIS·KB 차트 화면의 502: 브로커 키가 전달되지 않는다.
  - OHLCV DB 화면의 503: 외부 DB가 없다.
  - 에러분석 화면의 403: 관리자 전용 API다.
- 관찰만 하고 고치지 않은 것: 로컬 백엔드에서 같은 종목의 현재가 API 값과 일봉 차트 가격대가 다르게 오는 경우가 있다(예: 005930). 백엔드 시세 소스 동작이라 이번 UI 범위에서 제외했다.
- 라이트 모드 토글, 새 폰트 파일, 학습 문서 내용과 가이드 SVG 재작성은 범위 밖이다. 흰 바탕용 가이드 이미지는 밝은 판 위에 올려 표시한다.

후속 작업은 [터미널 UI 마감 검증](terminal-ui-polish-2026-09-25.md)에 기록했다. 남아 있던 4px 초과 모서리와 뒤집힌 등락 색을 정리했고, 1열 화면을 다열 패널로 바꿨다. HTS 시뮬레이터는 주식 화면에 흡수했다.
