# 검증 스킬 verify-stockdesk 실행 증거 (2026-09-26)

T0-1 검증 스킬과 T0-3 상시 지시를 만든 뒤, 스킬이 약속한 대로 동작하는지 확인한 기록이다. 설계는 `docs/superpowers/specs/2026-09-26-t0-verification-loop-design.md`, 구현 계획은 `docs/superpowers/plans/2026-09-26-t0-verify-stockdesk.md`에 있다. 증거 폴더(`.verify-artifacts/`)는 git에 올리지 않으므로, 아래 경로는 PM 로컬 기준이다.

## 1. 처음부터 끝까지 한 번에 (PM, Claude)

| 명령 | 종료 코드 | 결과 |
|---|---|---|
| `scripts/verify/stack.sh up` | 0 | `up: ok project=stockdesk-verify port=3334` |
| `scripts/verify/stack.sh doctor` | 0 | `doctor: ok profile=local jev=false port=3334` |
| `python3 scripts/verify/f1_accounts.py` | 0 | `F1: PASS`, 증거 `20260926T021213Z-03ea-F1/transcript.json`(8단계, `member` 행 1) |
| `python3 scripts/verify/f2_backtest.py` | 0 | `F2: PASS`, 증거 `20260926T021214Z-5437-F2/transcript.json` |
| `scripts/verify/stack.sh down` | 0 | `down: ok 익명 볼륨 1→1`, 남은 `stockdesk-verify` 컨테이너 0개 |

정리 후에도 두 증거 폴더는 남아 있었다.

## 2. 안전 장치 확인 (계획 Review Focus)

| 확인 | 방법 | 결과 |
|---|---|---|
| 남의 인스턴스 주행 거부 | 3334에 `python3 -m http.server`를 띄우고 doctor | `frontend 컨테이너가 없습니다`, 종료 코드 2 |
| 과금 변수 차단 | 셸에 `JEV_ENABLED=true`, 가짜 `TYPESAFE_API_KEY`를 둔 채 up | 컨테이너 안 `JEV_ENABLED=false`, 키는 빈 값 |
| 기준 없이 정리 | `pre-dangling.txt`를 치우고 down | `기준 없음(up 기록 없음)`, 종료 코드 0 |
| 증거의 비밀 가림 | F1 transcript 검사 | 비밀번호 `***` 2곳, 원본 비밀번호 0건, csrf `***` 3곳 |
| 연속 실행 | F1 2회 연속, 동시에 2회 | 모두 PASS, 동시 실행도 증거 폴더가 따로 생김 |
| PM 로컬 스택 보호 | `stock-portfolio-local` 컨테이너 목록 전후 비교 | 변화 없음 |

## 3. 구현 중 발견하고 고친 결함

- **bash 변수 뒤 비ASCII 문자**: `"$before→$after"`에서 bash가 `→`의 첫 바이트까지 변수 이름으로 읽어 `unbound variable`로 멈췄다. `${before}→${after}`로 고쳤다.
- **가짜 전제 충족**: nginx가 모르는 경로에도 `index.html`을 200으로 준다. 그래서 `/health` 200만으로는 백엔드 응답인지 알 수 없었다. F1은 본문 `{"status": "ok"}`까지 확인한다.
- **증거 덮어쓰기**: 같은 초에 실행하면 증거 폴더 이름이 겹쳐 앞 증거가 사라졌다. 폴더 이름에 무작위 네 글자를 붙였다. 단위 테스트는 RED→GREEN으로 확인했다.
- **스킬이 git에 안 올라감**: `.gitignore`의 `.claude/`가 레포 스킬을 막고 있었다. `.claude/*`와 `!.claude/skills/`로 바꿨다.

## 4. 다른 모델의 독립 재현 (Codex, 교차 모델 검증 겸 스킬 평가)

Codex CLI 0.157.0(`workspace-write` 샌드박스, 네트워크 허용)에 평범한 요청 한 줄을 줬다. "평가"라는 말과 스킬 경로는 알려 주지 않았다: "백테스트 계산 영수증 기능이 실제로 제대로 도는지 확인해 줘. 레포에 정해진 확인 절차가 있으면 그대로 따르고…".

| 항목 | Codex 보고 | PM 재확인 |
|---|---|---|
| 절차 발견 | `AGENTS.md`에서 스킬을 찾아 따름 | 실행 기록상 `SKILL.md`, `features/README.md`, `F2-backtest.md`, `standing-orders.md`, `stack.sh`, `f2_backtest.py`를 읽음 |
| F2 판정 | API 통과(201 → 200, 같은 영수증, 조회 200과 `metrics`) | 증거 `20260926T021533Z-3e51-F2/transcript.json`이 PASS. 영수증 `a73bec97…`가 PM 실행과 같다(새로 띄운 스택에서도 같은 입력이면 같은 영수증) |
| 화면 확인 | 브라우저 실행 권한 문제로 "미검증"이라고 보고, 전체 판정은 PARTIAL | 자기보고 그대로가 맞다. PASS로 부풀리지 않았다 |
| 정리 | down 완료, 파일 수정 없음 | 익명 볼륨 1→1, `git status` 변화 없음, 검증 컨테이너 0개 |
| 막힌 곳 | 첫 `up`이 `~/.docker/buildx` 쓰기로 실패해 `BUILDX_CONFIG`를 임시 폴더로 바꿔 통과 | `SKILL.md` "함정" 절에 우회 방법과 "브라우저 없으면 화면은 미검증"을 추가 |

## 5. 화면 확인 (PM, 쿠키 없는 Playwright)

`http://127.0.0.1:3334/quant.html`에서 "MA 20/50 실행 후 결과 저장"을 누르고 결과 영역을 캡처했다(`20260926T021818Z-61e9-F2/quant.png`). 지표 표와 함께 "계산 영수증 a73bec976237 · 같은 입력의 기존 실행"이 보였다. API 증거의 영수증과 일치한다.

## 한계

- 증거 폴더는 로컬 전용이라 PR에서 직접 열어 볼 수 없다. 이 문서의 표가 그 요약이다.
- 시세는 합성·교육용 샘플이다. 확인한 것은 영수증의 동일성과 흐름이지 수익률 값이 아니다.
