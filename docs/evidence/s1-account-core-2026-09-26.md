# S1a 계정 핵심 검증 기록 (2026-09-26)

S1 계정·신뢰 기반의 앞부분(가입 닫기·서버 세션·비밀번호 정책)을 구현하고 확인한 기록이다. 설계는 `docs/superpowers/specs/2026-09-26-s1-account-trust-design.md`, 구현 계획은 `docs/superpowers/plans/2026-09-26-s1a-account-core.md`에 있다. 증거 폴더(`.verify-artifacts/`)는 git에 올리지 않으므로 경로는 PM 로컬 기준이다.

## 1. PR별 결과

| PR | 내용 | 단위 | 통합(`stack.sh itest`) | 검증 스킬 | CI |
|---|---|---|---|---|---|
| #25 A | `itest` 도구, 공개 가입 게이트, `SESSION_COOKIE_SECURE` 강제 | 411 passed | 55 passed | F1 PASS(`signupOpen: true`, local) | 3개 통과, 머지 `443854f` |
| #26 B | 서버 세션 표, 로그아웃·모든 기기 로그아웃 | 414 passed | 62 passed(새 7) | F1 PASS(복사 쿠키 거부·모든 기기 로그아웃 단계 추가) | 3개 통과 |
| C | 비밀번호 정책·해시 형식·로그인 제한, 교차 검토 반영 | 420 passed | 67 passed(새 5) | F1·F2 PASS(짧은 비밀번호 거절 단계 추가) | — |

## 2. 공개 배포 확인 (PR A, 배포 실행 36222221070, `443854f`)

SSM Run Command로 서버 안에서 Caddy 호스트를 `--resolve`로 불렀다.

| 확인 | 결과 |
|---|---|
| `/health` | 200 |
| `GET /api/member/me` | `loggedIn: false`, `profile: public`, `signupOpen: false` |
| `POST /api/member/register`(Origin 포함) | 403 `SIGNUP_CLOSED` |

배포 전에 SSM 파라미터 이름만 조회해 `SESSION_COOKIE_SECURE`를 덮어쓰는 값이 없음을 확인했다(`compose.public.yml` 기본값 true). 새 기동 검사로 공개 서버가 멈출 위험이 없었다.

## 3. 테스트가 진짜로 잡는지 (돌연변이 확인)

| 일부러 넣은 결함 | 잡은 테스트 | 원복 |
|---|---|---|
| `member_sessions.end()`가 행을 지우지 않음 | `test_a_copied_cookie_stops_working_after_logout` 실패 | 백업에서 복원, `if token:` 확인 |
| 로그인 이메일 제한에서 `deduct_when` 제거(성공도 셈) | `test_email_limit_counts_only_failures` 실패 | 백업에서 복원, `deduct_when` 1곳 확인 |
| 이메일 제한 키를 입력 문자열로 되돌림(변형 주소 우회) | `test_accent_and_case_variants_share_one_email_limit` 실패 | 백업에서 복원 |

## 4. 로그인 소요 시간 (스펙 ⑥ 성능, 응답 시간 균등화)

검증 스택(M1 Pro, Docker, gunicorn)에서 같은 계정으로 각 10회.

| 경우 | 상태 | 중앙값 | 최소~최대 |
|---|---|---|---|
| 성공 | 200 | 253ms | 248~341ms |
| 틀린 비밀번호 | 401 | 254ms | 250~314ms |
| 없는 계정 | 401 | 255ms | 251~596ms |

- 세 경우의 중앙값 차이가 2ms라 응답 시간으로 가입 여부를 가려내기 어렵다.
- 없는 계정의 최대 596ms는 워커별 첫 호출에서 더미 해시를 만드는 시간이었다. 교차 검토(L1) 뒤 모듈을 불러올 때 미리 만들게 고쳤다.
  재기동 직후 없는 계정부터 10회 재측정: 중앙값 252ms, 최대 265ms. 같은 회차의 성공은 250ms, 틀린 비밀번호는 252ms였다.
- 공개 서버(t3.small) 측정은 가입이 열린 뒤 S1b 배포 확인 때 한다. 지금은 공개 서버에 계정을 만들 수 없다. 미검증.

## 5. 계획과 달라진 점

- public 가입은 메일 설정만으로 열리지 않고 `SIGNUP_ENABLED=true`도 필요하다(6절 Codex H1, 스펙 ①보다 엄격).
- 가입 게이트 변수 세 개(`SIGNUP_ENABLED`, `SMTP_HOST`, `PUBLIC_BASE_URL`)를 `compose.public.yml`이 넘기게 했다. 환경변수를 명시 목록으로 넘기므로, 이것이 없으면 나중에 가입을 열 수 없다.
- (되돌림) 세션 확인 훅을 교차 사이트 차단 뒤에 뒀다가, 6절 Codex L2 지적으로 원래 계획 순서(앞)로 되돌렸다.
- 가입 직후 세션 테스트는 가입한 클라이언트 그대로 `/me`를 확인한다. 계획 초안은 다시 로그인한 클라이언트로 확인해서, 가입 경로를 증명하지 못했다.
- 가입 요청의 비밀번호 정책 검사는 이메일 검사 **뒤**에 둔다(필드 순서, 기존 예약 이메일 테스트 유지).
- `create-admin`은 12자 규칙 대신 같은 정책(15자 등)을 쓴다. 테스트 기대 문구를 바꿨고, 기준을 낮추지는 않았다.
- 백엔드 이미지가 `*.py`만 복사하고 있어서 `python-stock-backend/data/`를 넣게 했다. 검증 스택 컨테이너 안에서 목록 파일이 있는지 확인했다.
- 차단 목록 원본은 SecLists가 `10-million-password-list-*`를 지우고 같은 내용의 `xato-net-10-million-passwords-1000000.txt`로 합쳤기 때문에, 그 파일(커밋 `c205c36`)을 썼다.

## 6. 교차 모델 보안 검토 (T0-4)

PR B와 C의 diff(main 대비)를 작성자(Claude)와 다른 두 검토자에게 읽기 전용으로 맡겼다.

**ecc:security-reviewer**: high 이상 0건.
- 단위 테스트 전체와 통합 18개, F1을 직접 돌렸다.
- Flask-Limiter 4.1.1 소스로 `deduct_when`을 확인했다(응답 뒤에만 차감).
- 절차 위반이 1건 있었다. 금지 조건을 어기고 PyPI에서 공개 패키지를 받았다. 비밀 값은 노출되지 않았고, 에이전트가 스스로 보고했다.

**Codex(`codex exec -s read-only`)**: high 3, medium 1, low 2. 정적 검토만 했다.

| 출처 | 심각도 | 지적 | 판정·조치 | 확인 |
|---|---|---|---|---|
| Codex | high | public은 SMTP·https 주소만 있으면 가입이 저절로 열린다. 메일 인증 흐름(S1b) 전이면 남의 이메일로 가입해 선점할 수 있다 | 타당. 메일 설정과 `SIGNUP_ENABLED=true`를 **모두** 갖춰야 열리게 했다. S1b가 "인증 전 로그인 거부"를 넣은 뒤에 연다 | `test_public_signup_opens_only_when_asked_and_mail_is_configured` |
| Codex | high | 회원 이메일 열이 `utf8_general_ci`라 `jose`와 `JOSÉ`가 같은 계정이다. 제한 키는 소문자화만 해서 변형 주소마다 한도가 따로 생긴다 | 타당. 검증 스택 MariaDB에서 `'jose@x' = 'JOSÉ@x'`가 1임을 확인했다. 있는 계정이면 저장된 이메일로 키를 만들게 했다 | `test_accent_and_case_variants_share_one_email_limit`, 돌연변이 확인 |
| Codex | high | `create-admin`이 비밀번호 변경과 세션 폐기를 따로 커밋한다 | 타당. 같은 트랜잭션에서 `member_session`도 지우게 했다 | `test_create_admin_…`에 재설정 뒤 기존 세션이 로그아웃되는지 추가 |
| Codex | medium | 공격자가 대상 이메일로 30번 실패하면 본인 로그인도 한 시간 안에 429가 된다 | 계정 단위 제한에 따르는 알려진 대가라 받아들인다. NIST 800-63B-4는 실패 100회 이하의 제한을 요구한다. S1b의 "이메일로 로그인 링크"나 재설정이 완화책이다. 공개 가입은 아직 닫혀 있다 | 수용(기록) |
| Codex | low | 더미 해시를 첫 요청 때 만들어, 재기동 직후 한 번 응답 시간이 튄다 | 타당. 모듈을 불러올 때 만든다 | 4절 재측정 |
| Codex | low | 교차 사이트 차단이 먼저 403을 주면, 오류 기록이 검증되지 않은 쿠키의 회원 ID를 남긴다 | 타당. 세션 확인 훅을 교차 사이트 차단 **앞**으로 되돌렸다(원래 계획 순서) | 단위·통합 전체 통과 |
| ecc | low | `::ffff:1.2.3.4` 형태면 모든 IPv4가 `::/64` 한 버킷이 된다 | 타당. IPv4로 바꿔 키를 만든다 | `test_ipv6_clients_share_a_limit_per_64_block`에 추가 |
| ecc | low | `create-admin`이 닉네임을 정책 검사에 넘기지 않는다 | 타당. `nickname=username`을 넘긴다 | 단위 통과 |
| ecc | 정보 | 이미 있는 이메일로 가입하면 400을 주어 가입 여부가 드러난다 | 알고 있음. 스펙 §③대로 S1b(메일 흐름)에서 같은 응답으로 바꾼다 | S1b |

5절의 "세션 확인 훅을 교차 사이트 차단 뒤에 둔다"는 이 검토로 되돌렸다.
