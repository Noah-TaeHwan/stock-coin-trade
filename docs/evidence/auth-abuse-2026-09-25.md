# 인증·권한·남용 제한 검증 — 2026-09-25

- 대상 브랜치: `claude/wonderful-faraday-826uz8`(PR 1-1 주문 정합성 위에 쌓음)
- 포트폴리오 계획 Phase 1의 두 번째 묶음(1-2)이다.

## 고친 문제

| 문제 | 이전 동작 | 근거 |
|---|---|---|
| 관리자 선점 | `admin@admin.com`으로 먼저 가입한 사람이 관리자가 된다. 그 계정을 만드는 코드는 없다. | `members.py` 가입, `authz.py` |
| 관리자 판정 두 벌 | `authz`는 환경변수·소문자 비교, 오류 분석 화면은 하드코딩 주소·정확 비교 | `error_analysis.py` |
| 이메일 중복 | `member.email`에 UNIQUE가 없어, 가입 확인과 삽입 사이에 같은 주소가 두 번 들어갈 수 있다. | `database/db.sql`의 `member` |
| 시스템 계정 로그인 | 봇 20개(`system-bot-account`)와 샘플 30개(`123456`)의 비밀번호가 코드에 있고, 일반 로그인으로 들어갈 수 있다. | `market_bots.py`, `demo_seed.py` |
| 사용자명으로 데이터 덮어쓰기 | 가나다·바바바 시드가 사용자명으로 계정을 찾아 자산을 덮어쓴다. 누구나 그 이름으로 가입할 수 있다. | `demo_seed.py` |
| 남용 | 로그인·가입·오류 수집·키 발급·AI 분석에 제한이 없다. API 키는 개수 제한이 없어 키 단위 요청 제한도 우회된다. | 각 라우트 |
| CSRF | 세션 쿠키로 인증하는 쓰기 요청 대부분에 출처 검사가 없다(KIS 실습 4개만 토큰 검사). | `security.py` |
| 예외 원문 노출 | DB·네트워크 예외 문자열을 그대로 응답한다(호스트명, SQL 등). | `app.py`, `quant.py`, `ai_sheet.py`, `ai.py` |
| 중첩 세션 | `/api/member/me` 안에서 `authz`가 새 `session_scope`를 열어 바깥 트랜잭션을 커밋·해제한다. | `members.py` → `authz.py` |

## 바꾼 것

- **설정(`settings.py`)**
  - `ADMIN_EMAIL`, `RATELIMIT_ENABLED`, `RATELIMIT_STORAGE_URI`, `TRUSTED_PROXY_COUNT`를 추가했다.
  - public은 다음이면 기동하지 않는다: 관리자 주소가 없거나 `admin@admin.com`, 레이트 리밋이 꺼짐, 저장소가 `memory://`.
  - local은 레이트 리밋이 기본으로 꺼져 있다. 교실에서 한 IP 뒤의 여러 학생이 막히지 않게 하기 위해서다.
- **관리자**
  - 판정은 `authz.is_admin_member` 하나로 합쳤다. 설정의 주소와 소문자로 비교한다.
  - public에서는 관리자 주소로 가입할 수 없다. 관리자 계정은 `flask --app app create-admin`으로 만든다(12자 이상, 있으면 비밀번호 재설정).
- **계정**
  - 멱등 DDL로 `uq_member_email`을 추가했다. 기존 중복이 있으면 초기화를 실패시키고 목록을 알린다.
  - 가입 경쟁으로 인덱스가 거부하면 500 대신 400을 돌려준다.
  - 시스템 도메인(`@sample-investor.local`, `@system-bot.local`)으로는 가입할 수 없다.
  - 봇은 bcrypt 해시가 아닌 값(`!unusable`)을 쓴다. 예전 비밀번호로 만든 기존 봇도 `seed-demo`가 바꾼다.
  - 로그인은 봇을 항상 거부하고, 샘플 계정은 public에서 거부한다.
  - `DEMO_SEED_ENABLED`의 기본값은 public에서 꺼짐이다. 가나다·바바바 시드는 public에서 실행하지 않는다.
- **남용 제한(Flask-Limiter 4.1.1)**
  - 로그인 분당 10, 가입 시간당 5, 오류 수집 분당 30, 키 발급 시간당 10, AI 분석 분당 10.
  - 활성 API 키는 회원당 5개까지다(모든 프로필).
  - 429 응답은 JSON이고 오류 로그 테이블에 쓰지 않는다. 기록하면 제한에 걸린 요청마다 DB 쓰기가 일어나기 때문이다.
  - nginx 뒤의 실제 클라이언트 IP는 `ProxyFix(x_for=TRUSTED_PROXY_COUNT)`로 복원한다. Compose는 1을 넘긴다.
- **CSRF**: 전역 검사를 두었다(OWASP CSRF Cheat Sheet의 Fetch Metadata + Origin 방식).
  - 비안전 메서드만 검사한다. `Sec-Fetch-Site`가 있으면 `same-origin`·`none`만 허용한다. local은 다른 포트의 개발 프런트를 위해 `same-site`도 허용한다.
  - 헤더가 없으면 `Origin`의 호스트가 요청 호스트와 같아야 한다.
  - 두 헤더가 모두 없으면 브라우저 요청이 아니므로 통과시킨다.
  - `/openapi/*`는 Bearer 키 인증이라 제외한다.
- **오류 응답**
  - 광범위한 예외·DB 예외는 고정 문구와 `requestId`만 돌려주고, 원문은 서버 로그에 요청 ID와 함께 남긴다.
  - 모든 응답에 `X-Request-ID` 헤더를 붙인다.
- **AI 분석**
  - 로그인을 필수로 하고, 문맥 길이를 8,000자로 제한했다.
  - 화면은 401·429일 때 안내 문구를 보여 준다.
  - 이 경로는 Phase 4에서 공식 SDK로 전부 교체한다.
- **화면**: 로그인·가입 화면은 응답의 `message`를 먼저 표시한다(429·403 안내).

## 의존성

- 추가한 패키지: `Flask-Limiter[redis]==4.1.1`
  - PyPI 기준 최신, MIT 라이선스, Python 3.10 이상 지원, 취약점 보고 없음(2026-09-25 조회).
  - 사용 방법은 공식 문서(Context7 `/alisaifee/flask-limiter`)로 확인했다: `init_app`, `RATELIMIT_STORAGE_URI`, 429 오류 처리기. 문서는 memory 저장소가 프로세스마다 따로라 운영에 주의하라고 한다.
- lock 재생성 결과는 추가만 있었고, 기존 패키지 버전은 바뀌지 않았다.
  - 추가된 패키지: `flask-limiter`, `limits` 5.8.0, `redis` 7.4.1, `ordered-set`, `deprecated`, `wrapt`, `async-timeout`
- pip-audit(추적 목록 적용): `No known vulnerabilities found, 51 ignored`로 새 취약점이 없었다.

## 결과

| 항목 | 방법 | 결과 |
|---|---|---|
| 단위 테스트 | `pytest tests/unit` | 86개 통과. 새 파일 `test_security_controls.py`, `test_settings.py` 확장 |
| 테스트가 실제로 잡는지 | CSRF 검사 끄기 / 오류 응답에 예외 원문 넣기 / 봇 로그인 허용으로 바꾼 코드 | 각각 5개·1개·2개 실패로 검출. 되돌린 뒤 통과 |
| MariaDB·PostgreSQL 통합 | MariaDB 11.4 + PostgreSQL 16 컨테이너, `pytest -m integration` | 14개 통과. 새 파일 `test_member_accounts.py` 7개 포함 |
| lint | `ruff check .`, 포맷 검사 | 통과 |
| Compose | CI의 `config --quiet` 3종 | 통과 |

통합 테스트가 확인한 것:
- `uq_member_email`이 UNIQUE이고, 대소문자만 다른 주소도 거부한다(테이블 collation이 대소문자를 구분하지 않음).
- 예전 비밀번호 해시를 가진 봇을 `seed-demo`가 `!unusable`로 바꾸고, 그 비밀번호로 로그인하면 401이다.
- 샘플 계정은 local에서 로그인 200, public에서 401이다.
- 활성 키는 5개까지(6번째는 400)이고, 하나를 폐기하면 다시 발급된다.
- `create_admin`으로 만든 계정이 public에서 로그인되고, `/api/member/me`의 `isAdmin`이 true, `/api/admin/me`가 200이다.

## 달라진 동작

- **local(기본)**
  - 봇 계정 로그인이 막힌다.
  - 시스템 도메인으로 가입할 수 없다.
  - 활성 API 키는 5개까지다.
  - 다른 사이트에서 보낸 쓰기 요청은 403이다.
  - 예외 원문 대신 고정 문구와 요청 ID가 나온다.
  - AI 분석은 로그인이 필요하다.
  - 레이트 리밋은 꺼져 있다.
- **public**: 위 항목에 더해 다음이 적용된다.
  - 레이트 리밋이 켜진다.
  - 샘플 계정 로그인이 막히고, 샘플·가나다·바바바 시드는 실행하지 않는다.
  - 관리자 주소로 가입할 수 없고, 관리자는 CLI로 만든다.
- 오류 로그의 `request_meta`에 `requestId`가 추가된다.

## 검증하지 못한 것

- Redis 저장소로 여러 gunicorn worker에서 제한이 공유되는지. Redis 서비스는 공개용 Compose(PR 1-4)에서 추가하고 그때 확인한다.
- 실제 브라우저가 보내는 `Sec-Fetch-Site`로 전체 화면을 점검하는 것. 테스트는 헤더를 직접 넣어 확인했다. 화면은 nginx가 같은 출처로 API를 프록시하므로 `same-origin`이 된다.
- 로컬 Compose 전체 스택 재기동. 이미지 빌드는 CI의 docker 작업이 확인한다.
