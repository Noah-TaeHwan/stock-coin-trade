# 패키징(README 첫 화면·공개 메뉴·검증 기록 색인) — 2026-09-25

- 대상 브랜치: `claude/wonderful-faraday-826uz8`
- 포트폴리오 계획 Phase 7이다. 데모 영상은 공개 배포 뒤에 만든다.

## 바꾼 것

- **README 첫 화면**: Noah가 만든 부분을 앞에 두고, 원본 강의 기능은 "원본 강의 기능 (edumgt)" 절 아래로 내렸다. 첫 화면에 들어간 내용:
  - 세 층의 영수증 다이어그램(mermaid)
  - 결과 표: 테스트 수, 구 엔진 오류, eval, 과최적화 측정, 라우트 수
  - 직접 확인하는 방법과 공개 데모 상태
  - 디렉터리별 기여 표
  - CI 배지
- **검증 기록 색인**
  - `docs/evidence/README.md`를 Phase별 색인으로 바꿨다.
  - 기존 내용(2026-09-23 로컬 실행 검증)은 `local-run-2026-09-23.md`로 옮기고, 이 파일을 가리키던 링크 4곳을 고쳤다. README, PORTFOLIO_LOCAL, 증거 문서 2개다.
- **메뉴**
  - 모든 프로필에 "NOAH 리서치" 그룹을 추가했다: 퀀트 백테스트·영수증, AI 리서치(초대제), Open API·MCP
  - 명령 `RSCH`/`AGENT`를 추가했다.
  - `/api/member/me`가 `profile`을 돌려준다.
  - public이면 등록되지 않은 기능의 화면을 메뉴·기능키·명령에서 뺀다: 브로커 실습 6개 그룹, 코인 거래·차익, 대체자산, OHLCV DB, AI Sheet, 옛 AI 분석
  - public의 F9는 AI 리서치로 연결한다.

## 결과

| 항목 | 방법 | 결과 |
|---|---|---|
| `/me`의 profile | `tests/unit/test_public_profile.py` | local·public 모두 확인, 통과 |
| 메뉴 | Playwright로 local·public 개발 서버의 헤더 링크·기능키·명령 목록 비교 | 아래 |
| UI 규칙 | `python3 scripts/check_terminal_ui.py` | 위반 없음 |
| 전체 | `ruff check .`, `pytest`(통합 포함) | 302개 통과 |

**Playwright 메뉴 비교**
- public
  - 헤더에 AI 리서치가 있다.
  - 브로커 실습 링크 0, 코인 거래·OHLCV 링크 없음
  - 기능키는 DASH·STK·HOLD·HIST·QNT·AI(→ `/research-agent.html`)
  - 코인 명령 없음
- local: 기존 메뉴가 그대로 있고 NOAH 리서치 그룹이 추가됐다. 기능키 9개가 모두 있다.
- 첫 시도에서 명령 목록 중 `href`가 없는 항목 때문에 public 헤더 렌더링이 멈췄다(`reading 'split'`). `href`가 없어도 동작하게 고친 뒤 확인했다.

## 검증하지 못한 것

- **README 렌더링**: mermaid 다이어그램과 앵커 링크가 GitHub에서 어떻게 보이는지는 PR 화면에서 확인한다.
- **메뉴 필터의 자동 테스트**: 프런트엔드에 JS 단위 테스트 환경이 없어 브라우저 점검만 했다.
- **public 보유자산 화면**: 코인·대체자산 부분이 해당 API 없이 표시된다. 오류로 멈추지는 않지만, 빈 칸으로 보이는지 따로 다듬지 않았다.
- **데모 영상**: 공개 배포 뒤에 만든다.
