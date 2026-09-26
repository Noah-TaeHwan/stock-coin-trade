# S1a 계정 핵심(가입 닫기·서버 세션·비밀번호 정책) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**
- 공개 가입을 메일 준비 전까지 구조적으로 닫는다.
- 로그아웃하면 서버에서도 즉시 무효가 되는 세션을 만든다.
- 비밀번호는 NIST SP 800-63B-4 기준으로 검사하고, 잘라서 검증하지 않게 저장한다.

**Architecture:**
- 설정(`settings.py`)이 가입 가능 여부를 계산한다. public은 SMTP와 https 기준 URL이 모두 있어야 가입이 열린다.
- 세션은 새 모듈 `member_sessions.py`가 맡는다. MariaDB 표에 토큰의 SHA-256 해시만 저장하고, `before_request` 훅이 쿠키의 `member_id`·`sid` 쌍을 검증한다. 기존 `session.get("member_id")` 62곳은 그대로 둔다.
- 비밀번호는 새 모듈 `passwords.py`가 맡는다.

**Tech Stack:** Flask, SQLAlchemy Core(text), MariaDB 11.4, bcrypt, Flask-Limiter 4.1.1, pytest, 검증 스킬 `verify-stockdesk`.

**Spec:** `docs/superpowers/specs/2026-09-26-s1-account-trust-design.md` §①~③(현재 상태·위협 모델 포함). S1b(메일·개인정보·화면)는 별도 계획이다.

## Global Constraints

- **비밀번호**: NFKC로 정규화한 뒤 15자 이상 64자 이하. 조합 규칙은 없고, 차단 목록과 **전체 일치**만 거절한다. 절대 자르지 않는다. 해시 형식은 `"s2$" + bcrypt(base64(sha256(NFKC(pw))))`.
- **세션**
  - 유휴 7일, 발급 30일이 지나면 만료. `last_seen_at`은 1시간이 지났을 때만 갱신한다.
  - DB 조회가 실패하면 로그아웃으로 처리한다(fail closed).
  - DB에는 토큰의 해시만 저장한다.
- **가입 게이트**: public에서는 `SMTP_HOST`와 `https://`로 시작하는 `PUBLIC_BASE_URL`이 모두 있어야 가입이 열린다. public은 `SESSION_COOKIE_SECURE=true`가 아니면 기동을 거부한다.
- **로그인 제한**: IP 기준 분당 10회(IPv6는 /64 단위). 이메일 기준으로는 **실패(401)만** 세어 시간당 30회.
- **코드 규칙**: 한국어 docstring. 새 의존성은 없다. 차단 목록은 데이터 파일이며 출처와 라이선스를 적는다.
- **검증**
  - 단위 테스트: `docker run --rm -v "$PWD":/repo -w /repo sct-test:dev python -m pytest -q …`
  - 통합 테스트: `scripts/verify/stack.sh itest …`(Task 0에서 만듦)
  - 앱 확인: 검증 스킬 F1
- **PR 단위**: PR A(Task 0·1, 계획 문서 포함) → 공개 배포 → PR B(Task 2) → PR C(Task 3·4). 각 PR은 main 보호에 따라 CI 3개가 통과해야 머지된다.

## Review Focus

1. 옛 서명 쿠키(`sid` 없음)를 가진 방문자가 배포 직후 500이 아니라 로그아웃 상태를 봐야 한다. → Task 2 단위 테스트.
2. 가입 직후 세션 발급이 회원 행 커밋 전에 일어나면 FK 대기나 실패가 생긴다. 세션 발급은 트랜잭션 밖에서 한다. → Task 2 통합 테스트(가입 후 `/me` loggedIn).
3. 로그인한 테스트가 만든 `member_session` 행 때문에 기존 통합 테스트의 회원 삭제 도우미가 FK로 실패하면 안 된다. → Task 2 Step 7.
4. 한글 긴 비밀번호의 끝 글자만 달라도 다르게 판정해야 한다(잘림 금지). → Task 3 단위 테스트.
5. 성공한 로그인은 이메일 기준 제한에 세지 않아야 한다(정상 사용자 잠금 방지). → Task 3 통합 테스트.

---

### Task 0: 로컬 통합 테스트 도구 `stack.sh itest`

**Files:**
- Modify: `scripts/verify/stack.sh`(case에 `itest` 추가)
- Modify: `.claude/skills/verify-stockdesk/SKILL.md`(Helpers 표에 한 줄)

**Interfaces:**
- Produces: `scripts/verify/stack.sh itest [pytest 인자…]`. 이 체크아웃이 띄운 검증 스택의 MariaDB·PostgreSQL로 `pytest -m integration`을 돌린다. 비밀 값은 argv가 아니라 환경변수로 넘긴다.

- [ ] **Step 1: `itest` 추가**(`down)` 분기 앞)

```bash
  itest)
    mine || { echo "itest: 이 체크아웃이 띄운 검증 스택이 없습니다. 먼저 up 하세요"; exit 2; }
    shift
    set -a; . "./$ENV_FILE"; set +a
    # 비밀 값은 docker 인자에 넣지 않고 -e 이름만 넘긴다(ps에 값이 보이지 않게).
    DB_USER="$MARIADB_USER" DB_PASSWORD="$MARIADB_PASSWORD" \
    QUANT_DATABASE_URL="postgresql+psycopg://${QUANT_DB_USER}:${QUANT_DB_PASSWORD}@postgres:5432/${QUANT_DB_NAME}" \
      docker run --rm --network "${PROJECT}_internal" -v "$HERE":/repo -w /repo \
        -e RUN_INTEGRATION=1 -e DB_HOST=mariadb -e DB_PORT=3306 -e DB_NAME=mockinv \
        -e DB_USER -e DB_PASSWORD -e QUANT_DATABASE_URL \
        sct-test:dev python -m pytest -q -m integration "$@"
    ;;
```

사용법 주석 줄을 `up|doctor|itest|down`으로 바꾼다.

- [ ] **Step 2: 기준 실행**

Run: `scripts/verify/stack.sh up && scripts/verify/stack.sh itest tests/integration/test_member_accounts.py; echo "exit=$?"`
Expected: 기존 통합 테스트가 통과하고 `exit=0`이다. 실패하면 도구 문제인지 기존 테스트 문제인지 구분해 기록한다.

- [ ] **Step 3: SKILL.md Helpers에 한 줄 추가**

`| \`scripts/verify/stack.sh itest [pytest 인자]\` | 검증 스택 DB로 통합 테스트 |`

- [ ] **Step 4: Commit** — `feat: 검증 스택 DB로 통합 테스트를 돌리는 itest를 추가한다`

---

### Task 1: 공개 가입을 구조로 닫기 (PR A)

**Files:**
- Modify: `python-stock-backend/settings.py`(필드 3개, `from_env`, public 검사, `flask_config`)
- Modify: `python-stock-backend/members.py`(`me`, `register` 앞머리)
- Modify: `frontend/member/register.html`(닫힘 안내)
- Test: `tests/unit/test_settings.py`(수정·추가), `tests/unit/test_signup_gate.py`(신규)

**Interfaces:**
- Produces:
  - `Settings.signup_enabled: bool = True`, `Settings.smtp_host: str = ""`, `Settings.public_base_url: str = ""`
  - `app.config["SIGNUP_ENABLED"]`, `app.config["PUBLIC_BASE_URL"]`
  - `/api/member/me` 응답의 `signupOpen: bool`
  - 가입이 닫혔을 때 `POST /api/member/register` → 403 `{"error": "SIGNUP_CLOSED", "message": …}`

- [ ] **Step 1: 실패하는 테스트**

`tests/unit/test_settings.py`:
- `PUBLIC_OK`에 `"SESSION_COOKIE_SECURE": "true"`를 넣는다.
- 파일 끝에 추가한다.

```python
def test_public_profile_refuses_insecure_session_cookie():
    with pytest.raises(SettingsError, match="SESSION_COOKIE_SECURE"):
        Settings.from_env({**PUBLIC_OK, "SESSION_COOKIE_SECURE": "false"})


def test_public_signup_stays_closed_until_mail_is_configured():
    assert Settings.from_env(PUBLIC_OK).signup_enabled is False
    ready = {**PUBLIC_OK, "SMTP_HOST": "smtp.example.test", "PUBLIC_BASE_URL": "https://desk.example.test/"}
    settings = Settings.from_env(ready)
    assert settings.signup_enabled is True
    assert settings.public_base_url == "https://desk.example.test"


def test_public_refuses_forcing_signup_open_without_mail():
    with pytest.raises(SettingsError, match="SIGNUP_ENABLED"):
        Settings.from_env({**PUBLIC_OK, "SIGNUP_ENABLED": "true"})


def test_local_signup_is_open_by_default():
    assert Settings.from_env({"APP_PROFILE": "local"}).signup_enabled is True
```

`tests/unit/test_signup_gate.py`:

```python
"""메일이 준비되기 전 공개 배포의 가입 차단과 화면 안내 신호."""

from app import create_app
from settings import Settings

CLOSED = Settings(profile="public", secret_key="p" * 40, session_cookie_secure=True,
                  admin_email="owner@example.com", ratelimit_enabled=True, signup_enabled=False)


def _client(settings):
    application = create_app(settings)
    application.config.update(TESTING=True)
    return application.test_client()


def test_closed_signup_refuses_registration_before_touching_the_database():
    response = _client(CLOSED).post("/api/member/register", json={
        "username": "가입", "email": "a@example.test", "password": "x" * 20, "password2": "x" * 20})
    assert response.status_code == 403
    assert response.get_json()["error"] == "SIGNUP_CLOSED"


def test_me_tells_the_page_whether_signup_is_open(client):
    assert client.get("/api/member/me").get_json()["signupOpen"] is True
    assert _client(CLOSED).get("/api/member/me").get_json()["signupOpen"] is False
```

- [ ] **Step 2: 실패 확인**

Run: `docker run --rm -v "$PWD":/repo -w /repo sct-test:dev python -m pytest -q tests/unit/test_settings.py tests/unit/test_signup_gate.py`
Expected: 새 테스트들이 FAIL이다(`signup_enabled` 속성 없음, `signupOpen` 키 없음, SESSION_COOKIE_SECURE 미검사).

- [ ] **Step 3: `settings.py` 구현**
  - 데이터클래스 필드(`dart_api_key` 아래):

```python
    # 가입을 받을지. public은 인증 메일이 필요하므로 SMTP_HOST와 https PUBLIC_BASE_URL이 있어야만 열린다.
    signup_enabled: bool = True
    smtp_host: str = ""
    # 메일 속 링크의 기준 주소. 요청의 Host 헤더로 링크를 만들지 않는다(재설정 링크 변조 방지).
    public_base_url: str = ""
```

  - `from_env`에서 `if profile == "public":` 앞에 추가:

```python
        smtp_host = (env.get("SMTP_HOST") or "").strip()
        public_base_url = (env.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
        mail_ready = bool(smtp_host) and public_base_url.startswith("https://")
        signup_default = "true" if profile == "local" or mail_ready else "false"
        signup_enabled = (env.get("SIGNUP_ENABLED") or signup_default).strip().lower() == "true"
```

  - public `problems`에 추가:

```python
            if env.get("SESSION_COOKIE_SECURE", "false").strip().lower() != "true":
                problems.append("SESSION_COOKIE_SECURE must be true")
            if signup_enabled and not mail_ready:
                problems.append("SIGNUP_ENABLED needs SMTP_HOST and an https:// PUBLIC_BASE_URL")
```

  - `cls(...)`에 `signup_enabled=signup_enabled, smtp_host=smtp_host, public_base_url=public_base_url,`를 추가한다.
  - `flask_config`에 `"SIGNUP_ENABLED": self.signup_enabled, "PUBLIC_BASE_URL": self.public_base_url,`를 추가한다.

- [ ] **Step 4: `members.py` 구현**
  - `me()`는 세 응답이 공통 필드를 같이 쓰게 바꾼다.

```python
@member_bp.get("/me")
def me():
    member_id = session.get("member_id")
    # profile은 이 배포가 등록하지 않은 화면을 메뉴에서 숨기는 데, signupOpen은 가입 화면 안내에 쓴다.
    base = {"csrfToken": csrf_token(), "profile": current_app.config.get("APP_PROFILE", "local"),
            "signupOpen": bool(current_app.config.get("SIGNUP_ENABLED", True))}
    if not member_id:
        return jsonify({"loggedIn": False, **base})
    with session_scope() as db:
        member = db.get(Member, member_id)
        if not member:
            return jsonify({"loggedIn": False, **base})
        return jsonify({
            "loggedIn": True, "username": member.username, "asset": member.asset,
            "isAdmin": is_admin_member(member_id, db), "canUseKisAccount": can_use_kis_account(member_id, db),
            **base,
        })
```

  - `register()`의 첫 줄(`body = …` 앞):

```python
    if not current_app.config.get("SIGNUP_ENABLED", True):
        return jsonify({"error": "SIGNUP_CLOSED", "message": "공개 베타 준비 중이라 가입을 잠시 닫았습니다."}), 403
```

- [ ] **Step 5: 가입 화면 안내**

`frontend/member/register.html`의 인라인 스크립트 끝(`</script>` 앞)에 추가한다.

```js
apiFetch('/api/member/me').then(res => res.json()).then(me => {
  if (me.signupOpen !== false) return;
  const el = document.getElementById('globalError');
  el.textContent = '공개 베타 준비 중이라 지금은 가입을 받지 않습니다.';
  el.style.display = 'block';
  document.getElementById('submitBtn').disabled = true;
}).catch(() => {});
```

- [ ] **Step 6: 통과 확인**

Run: `docker run --rm -v "$PWD":/repo -w /repo sct-test:dev python -m pytest -q -m "not integration"`
Expected: 전체 통과. 기존 public 테스트 중 `PUBLIC_OK`나 `SESSION_COOKIE_SECURE`에 기대던 것이 깨지면 테스트 데이터에 `SESSION_COOKIE_SECURE=true`를 넣는다(코드 쪽 기준은 낮추지 않는다).

- [ ] **Step 7: 앱 확인** — `scripts/verify/stack.sh up`, `doctor`, `python3 scripts/verify/f1_accounts.py`가 PASS인지 확인한다(local은 가입이 열려 있어야 함). `curl -s http://127.0.0.1:3334/api/member/me`에 `"signupOpen": true`가 있는지 본다.

- [ ] **Step 8: Commit** — `feat: 공개 배포는 메일 준비 전까지 가입을 구조로 닫는다`

- [ ] **Step 9: PR A → CI → 머지 → 공개 배포 → 확인**
  - `gh workflow run deploy.yml -R Noah-TaeHwan/stock-coin-trade`. 워크플로 입력은 파일로 확인한다.
  - 배포 뒤 SSM으로 서버 안에서 Caddy 호스트에 `--resolve`로 확인한다.
    - `/health` 200
    - `/api/member/me`에 `"signupOpen": false`
    - `POST /api/member/register`(Origin 헤더 포함)가 403 `SIGNUP_CLOSED`
  - 결과는 `docs/evidence/s1-account-core-2026-09-26.md`에 적는다.

---

### Task 2: 서버 세션 표와 확인 훅 (PR B)

**Files:**
- Create: `python-stock-backend/member_sessions.py`
- Modify:
  - `python-stock-backend/app.py`(훅 등록)
  - `python-stock-backend/members.py`(login·register·logout, `logout-all` 신규)
  - `python-stock-backend/bootstrap.py`(`create_tables`)
  - `python-stock-backend/scheduler.py`(정리 작업)
  - `database/db.sql`, `database/SCHEMA.md`
  - `tests/unit/test_scheduler_worker.py`(작업 집합)
  - 통합 테스트 도우미 3곳
- Test: `tests/unit/test_member_sessions.py`, `tests/integration/test_member_sessions.py`

**Interfaces:**
- Produces(`member_sessions`):
  - `token_hash(token: str) -> str`
  - `ensure_session_table() -> None`
  - `start(member_id: int) -> None`: 세션을 비우고 새 토큰을 발급한다. 반드시 회원 행이 커밋된 뒤에 부른다.
  - `validate() -> None`: before_request 훅
  - `end() -> None`, `end_all(member_id: int) -> None`, `purge_expired() -> int`
  - 상수 `IDLE`, `ABSOLUTE`, `TOUCH`
- Produces(API): `POST /api/member/logout-all` → 200 `{"success": true}`, 로그인 안 했으면 401.

- [ ] **Step 1: 실패하는 단위 테스트** `tests/unit/test_member_sessions.py`

```python
"""서버 세션 확인 훅: 옛 쿠키, 저장소 장애, 토큰 해시."""

from sqlalchemy.exc import SQLAlchemyError

import member_sessions


def test_old_cookie_without_a_server_session_is_dropped(client):
    with client.session_transaction() as s:
        s["member_id"] = 7
    assert client.get("/api/member/me").get_json()["loggedIn"] is False


def test_session_store_failure_logs_the_visitor_out(client, monkeypatch):
    class Broken:
        def begin(self):
            raise SQLAlchemyError("session store down")

    monkeypatch.setattr(member_sessions, "engine", Broken())
    with client.session_transaction() as s:
        s["member_id"], s["sid"] = 7, "token"
    assert client.get("/api/member/me").get_json()["loggedIn"] is False


def test_only_a_hash_of_the_token_is_kept():
    digest = member_sessions.token_hash("abc")
    assert digest != "abc" and len(digest) == 64
```

Run: `docker run --rm -v "$PWD":/repo -w /repo sct-test:dev python -m pytest -q tests/unit/test_member_sessions.py`
Expected: FAIL. `member_sessions` 모듈이 없고, 첫 테스트는 DB 접근 오류가 난다.

- [ ] **Step 2: `member_sessions.py` 구현**

```python
"""서버 세션: 서명 쿠키의 (member_id, sid)를 MariaDB 표로 검증한다(설계: S1 스펙 ②).

로그아웃하면 행을 지워 복사된 쿠키도 즉시 무효가 된다. DB에는 토큰의 SHA-256만 둔다.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from flask import session
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from db import engine

IDLE = timedelta(days=7)
ABSOLUTE = timedelta(days=30)
TOUCH = timedelta(hours=1)

SESSION_TABLE = """CREATE TABLE IF NOT EXISTS member_session (
  token_hash CHAR(64) PRIMARY KEY,
  member_id BIGINT NOT NULL,
  created_at DATETIME NOT NULL,
  last_seen_at DATETIME NOT NULL,
  KEY idx_member_session_member (member_id),
  CONSTRAINT fk_member_session_member FOREIGN KEY (member_id) REFERENCES member(member_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""


def token_hash(token: str) -> str:
    """세션 토큰의 SHA-256 16진수. @param token 원본 토큰 @returns 64자 해시"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    """DB에 쓰는 UTC 시각(시간대 정보 없음)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def ensure_session_table() -> None:
    """member_session 표를 만든다(멱등)."""
    with engine.begin() as conn:
        conn.execute(text(SESSION_TABLE))


def start(member_id: int) -> None:
    """세션 고정을 막고 새 서버 세션을 발급한다. 회원 행이 커밋된 뒤에 부른다.

    @param member_id 로그인한 회원 ID
    """
    session.clear()
    token, now = secrets.token_urlsafe(32), _now()
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO member_session (token_hash, member_id, created_at, last_seen_at) "
                          "VALUES (:h, :m, :now, :now)"), {"h": token_hash(token), "m": member_id, "now": now})
    session["member_id"], session["sid"], session.permanent = member_id, token, True


def validate() -> None:
    """요청마다 쿠키의 세션이 서버에 살아 있는지 본다. 아니면 쿠키 세션을 비운다(fail closed)."""
    member_id, token = session.get("member_id"), session.get("sid")
    if member_id is None:
        return
    if not token:
        session.clear()
        return
    digest, now = token_hash(token), _now()
    try:
        with engine.begin() as conn:
            row = conn.execute(text("SELECT member_id, created_at, last_seen_at FROM member_session "
                                    "WHERE token_hash = :h"), {"h": digest}).mappings().first()
            expired = row is None or now - row["last_seen_at"] > IDLE or now - row["created_at"] > ABSOLUTE
            if expired or row["member_id"] != member_id:
                if row is not None:
                    conn.execute(text("DELETE FROM member_session WHERE token_hash = :h"), {"h": digest})
                session.clear()
            elif now - row["last_seen_at"] > TOUCH:
                conn.execute(text("UPDATE member_session SET last_seen_at = :now WHERE token_hash = :h"),
                             {"now": now, "h": digest})
    except SQLAlchemyError:
        session.clear()


def end() -> None:
    """현재 세션만 끝낸다(로그아웃)."""
    token = session.get("sid")
    if token:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM member_session WHERE token_hash = :h"), {"h": token_hash(token)})
    session.clear()


def end_all(member_id: int) -> None:
    """회원의 모든 세션을 끝낸다(모든 기기 로그아웃, 비밀번호 변경·재설정, 탈퇴). @param member_id 회원 ID"""
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM member_session WHERE member_id = :m"), {"m": member_id})


def purge_expired() -> int:
    """만료된 세션 행을 지운다(worker가 매일 실행). @returns 지운 행 수"""
    now = _now()
    with engine.begin() as conn:
        return conn.execute(text("DELETE FROM member_session WHERE last_seen_at < :idle OR created_at < :absolute"),
                            {"idle": now - IDLE, "absolute": now - ABSOLUTE}).rowcount
```

- [ ] **Step 3: 연결**
  - `app.py`: `import member_sessions`를 추가하고, `app.before_request(_reject_cross_site_requests)` **앞**에 `app.before_request(member_sessions.validate)`를 넣는다.
  - `bootstrap.py`: `from member_sessions import ensure_session_table`, `create_tables()`에서 `ensure_member_tables()` 다음 줄에 `ensure_session_table()`.
  - `scheduler.py` `build_scheduler`의 `run_bot_trading_round` 등록 아래:

```python
    from member_sessions import purge_expired

    scheduler.add_job(purge_expired, CronTrigger(hour=3, minute=0, timezone="Asia/Seoul"), id="member_session_purge")
```

  - `tests/unit/test_scheduler_worker.py`의 작업 집합 기대값에 `"purge_expired"`를 더한다(트리거 03:00 KST 단언 한 줄 포함).
  - `database/db.sql` 끝에 `SESSION_TABLE`과 같은 DDL, `database/SCHEMA.md`에 `member_session` 절(열, 만료 규칙, 원본 토큰 미저장)을 추가한다.

- [ ] **Step 4: `members.py` 연결**
  - `import member_sessions`
  - `login()`: 인증에 성공하면 `member_id, username, asset`을 지역 변수로 꺼내 `with`를 빠져나온 뒤 `member_sessions.start(member_id)`를 부르고 `{"username", "asset"}`를 반환한다. 기존 `session.clear()`·`session[...]`·`session.permanent` 세 줄은 지운다.
  - `register()`: `db.flush()` 성공 뒤 `member_id = member.member_id`, `with`를 빠져나온 뒤 `member_sessions.start(member_id)` → `{"username": username}`. 트랜잭션 안에서 세션을 발급하면 FK 대기가 생긴다(Review Focus 2).
  - `logout()`: `member_sessions.end()` 후 `{"success": True}`.
  - 신규:

```python
@member_bp.post("/logout-all")
def logout_all():
    """이 회원의 모든 기기 세션을 끝낸다(현재 기기 포함)."""
    member_id = session.get("member_id")
    if not member_id:
        return jsonify({"error": "UNAUTHORIZED", "message": "로그인이 필요합니다."}), 401
    member_sessions.end_all(member_id)
    session.clear()
    return jsonify({"success": True})
```

- [ ] **Step 5: 단위 테스트 통과**

Run: `docker run --rm -v "$PWD":/repo -w /repo sct-test:dev python -m pytest -q -m "not integration"`
Expected: 전체 통과(새 3개 포함).

- [ ] **Step 6: 통합 테스트 작성** `tests/integration/test_member_sessions.py`

```python
"""서버 세션이 로그아웃·모든 기기 로그아웃·만료·조작 쿠키를 서버에서 끊는다."""

import uuid

import pytest
from sqlalchemy import text

import bootstrap
import db
import member_sessions
from app import create_app
from settings import Settings

pytestmark = pytest.mark.integration
PASSWORD = "long-enough-passphrase-for-tests"


@pytest.fixture(scope="module", autouse=True)
def tables():
    bootstrap.create_tables()


def _client():
    application = create_app(Settings(profile="local", secret_key="k" * 40, session_cookie_secure=False))
    application.config.update(TESTING=True)
    return application.test_client()


@pytest.fixture
def email():
    address = f"sess-{uuid.uuid4().hex[:10]}@example.test"
    signup = _client().post("/api/member/register", json={
        "username": "세션", "email": address, "password": PASSWORD, "password2": PASSWORD})
    assert signup.status_code == 200
    yield address
    with db.engine.begin() as conn:
        member_id = conn.execute(text("SELECT member_id FROM member WHERE email = :e"), {"e": address}).scalar()
        for table in ("member_session", "member"):
            conn.execute(text(f"DELETE FROM {table} WHERE member_id = :id"), {"id": member_id})


def _login(address):
    client = _client()
    assert client.post("/api/member/login", json={"email": address, "password": PASSWORD}).status_code == 200
    return client


def test_signup_starts_a_session_after_the_member_row_is_committed(email):
    client = _login(email)
    assert client.get("/api/member/me").get_json()["loggedIn"] is True


def test_the_server_keeps_only_a_hash_of_the_session_token(email):
    client = _login(email)
    with client.session_transaction() as s:
        raw = s["sid"]
    with db.engine.connect() as conn:
        hashed = conn.execute(text("SELECT COUNT(*) FROM member_session WHERE token_hash = :h"),
                              {"h": member_sessions.token_hash(raw)}).scalar()
        plain = conn.execute(text("SELECT COUNT(*) FROM member_session WHERE token_hash = :t"), {"t": raw}).scalar()
    assert (hashed, plain) == (1, 0)


def test_a_copied_cookie_stops_working_after_logout(email):
    client = _login(email)
    copied = client.get_cookie("session").value
    assert client.post("/api/member/logout").status_code == 200
    thief = _client()
    thief.set_cookie("session", copied)
    assert thief.get("/api/member/me").get_json()["loggedIn"] is False


def test_logout_all_ends_every_device(email):
    phone, laptop = _login(email), _login(email)
    assert laptop.post("/api/member/logout-all").status_code == 200
    assert phone.get("/api/member/me").get_json()["loggedIn"] is False


def test_a_cookie_pointing_at_another_member_is_rejected(email):
    client = _login(email)
    with client.session_transaction() as s:
        s["member_id"] = s["member_id"] + 1
    assert client.get("/api/member/me").get_json()["loggedIn"] is False


def test_idle_sessions_expire_and_their_rows_are_removed(email):
    client = _login(email)
    with client.session_transaction() as s:
        digest = member_sessions.token_hash(s["sid"])
    with db.engine.begin() as conn:
        conn.execute(text("UPDATE member_session SET last_seen_at = last_seen_at - INTERVAL 8 DAY "
                          "WHERE token_hash = :h"), {"h": digest})
    assert client.get("/api/member/me").get_json()["loggedIn"] is False
    with db.engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM member_session WHERE token_hash = :h"),
                            {"h": digest}).scalar() == 0


def test_purge_removes_expired_rows_and_keeps_live_ones(email):
    live = _login(email)
    old = _login(email)
    with old.session_transaction() as s:
        old_digest = member_sessions.token_hash(s["sid"])
    with db.engine.begin() as conn:
        conn.execute(text("UPDATE member_session SET created_at = created_at - INTERVAL 31 DAY "
                          "WHERE token_hash = :h"), {"h": old_digest})
    assert member_sessions.purge_expired() >= 1
    assert live.get("/api/member/me").get_json()["loggedIn"] is True
```

Run: `scripts/verify/stack.sh up && scripts/verify/stack.sh itest tests/integration/test_member_sessions.py`
Expected: 7 passed. 세션 코드를 잠시 되돌리면(예: `end()`가 행을 지우지 않게) `test_a_copied_cookie_stops_working_after_logout`이 실패하는 것을 한 번 확인한다(테스트가 진짜로 잡는지).

- [ ] **Step 7: 기존 통합 테스트 도우미 (Review Focus 3)**

`tests/integration/test_member_accounts.py`, `test_stock_order_race.py`, `test_deskmcp_end_to_end.py`의 `for table in (…)` 목록에서 `"member"` 바로 앞에 `"member_session"`을 넣는다.

Run: `scripts/verify/stack.sh itest`
Expected: 전체 통합 테스트 통과.

- [ ] **Step 8: F1 확장** — `scripts/verify/common.py`의 `Client`에 쿠키 복제를 추가하고, F1에 "로그아웃 뒤 복사한 쿠키 거부"와 "모든 기기 로그아웃" 단계를 넣는다.

```python
    def clone(self) -> Client:
        """같은 쿠키를 가진 새 클라이언트(복사된 쿠키 재사용 시험용)."""
        twin = Client(self.base)
        for cookie in self._jar:
            twin._jar.set_cookie(copy.copy(cookie))
        return twin
```

  - `__init__`에서 `self._jar = http.cookiejar.CookieJar()`를 만들어 opener에 넘긴다. 파일 머리에 `import copy`.
  - `f1_accounts.py`의 로그아웃 단계 바로 앞에 `stolen = client.clone()`을 두고, 로그아웃 뒤 `stolen`의 `/me`가 `loggedIn: False`인지 확인한다. 증거 단계 이름은 `me-with-copied-cookie`.
  - 마지막에 두 번째 로그인 클라이언트를 만들고 `POST /api/member/logout-all` 뒤 그 클라이언트의 `/me`가 False인지 확인한다.

Run: `python3 scripts/verify/f1_accounts.py` → `F1: PASS`

- [ ] **Step 9: Commit·PR B·CI·머지** — `feat: 서버 세션 표로 로그아웃·모든 기기 로그아웃을 서버에서 끊는다`

---

### Task 3: 비밀번호 정책·해시 형식·로그인 강화 (PR C)

**Files:**
- Create: `python-stock-backend/passwords.py`, `python-stock-backend/data/common-passwords-15plus.txt`, `python-stock-backend/data/COMMON-PASSWORDS-NOTICE.md`
- Modify:
  - `members.py`: 가입 검사, 로그인. `_hash_password`와 `_check_password`는 삭제
  - `bootstrap.py`: `create_admin`
  - `extensions.py`: IPv6 /64 키
  - `accounts.py`: 주석 한 줄
- Test: `tests/unit/test_passwords.py`, `tests/integration/test_member_sessions.py`(추가), `tests/integration/test_member_accounts.py`(관리자 비밀번호)

**Interfaces:**
- Produces(`passwords`):
  - `MIN_LENGTH=15`, `MAX_LENGTH=64`, `PREFIX="s2$"`
  - `normalize(pw) -> str`
  - `problem(pw, *, email="", nickname="") -> str | None`: 한국어 사용자 메시지
  - `hash_password(pw) -> str`
  - `verify(pw, stored) -> bool`
  - `needs_rehash(stored) -> bool`
  - `dummy_hash() -> str`
- Produces(`extensions`): `client_key() -> str`

- [ ] **Step 1: 차단 목록 데이터**
  - 출처: SecLists(MIT)의 `Passwords/Common-Credentials/10-million-password-list-top-1000000.txt`
  - `curl -fsSL`로 스크래치 폴더에 받는다(레포에 원본을 두지 않는다).
  - NFKC 정규화와 소문자화를 한 뒤 **15자 이상 64자 이하**만 남긴다. 중복을 제거하고 정렬해 `python-stock-backend/data/common-passwords-15plus.txt`에 쓴다.
  - 줄 수와 크기를 기록한다.
  - `COMMON-PASSWORDS-NOTICE.md`에 출처 URL, 커밋 SHA, MIT 고지, 필터 조건, 생성 명령을 적는다.
  - Dockerfile이 `python-stock-backend/data/`를 이미지에 넣는지 확인한다(`docker/` 백엔드 Dockerfile의 COPY 범위).

- [ ] **Step 2: 실패하는 단위 테스트** `tests/unit/test_passwords.py`

```python
"""비밀번호 정책(NIST SP 800-63B-4 §3.1.1.2)과 잘림 없는 해시."""

import bcrypt

import passwords
from accounts import UNUSABLE_PASSWORD

GOOD = "quiet river finds the sea"


def test_length_bounds_are_15_to_64_characters():
    assert passwords.problem("quiet river fi") is not None
    assert passwords.problem("quiet river fin") is None
    assert passwords.problem("a" * 30 + "b" * 34) is None
    assert passwords.problem("a" * 30 + "b" * 35) is not None


def test_listed_repeated_and_personal_passwords_are_refused():
    listed = next(line for line in passwords.BLOCKLIST.read_text(encoding="utf-8").splitlines() if line.strip())
    assert passwords.problem(listed) is not None
    assert passwords.problem("ㅋ" * 20) is not None
    assert passwords.problem("minsu-long-password-here", email="minsu@example.test") is not None
    assert passwords.problem("hello my nick is 주식왕", nickname="주식왕") is not None


def test_long_korean_passwords_are_never_truncated():
    base = "봄비 오는 날 공시를 읽고 차트를 천천히 본다 " * 2
    stored = passwords.hash_password(base + "가")
    assert passwords.verify(base + "가", stored) is True
    assert passwords.verify(base + "나", stored) is False


def test_nfkc_equivalent_input_verifies():
    stored = passwords.hash_password(GOOD)
    assert passwords.verify("ｑｕｉｅｔ ｒｉｖｅｒ ｆｉｎｄｓ ｔｈｅ ｓｅａ", stored) is True


def test_legacy_bcrypt_hashes_still_verify_and_ask_for_rehash():
    legacy = bcrypt.hashpw(GOOD.encode(), bcrypt.gensalt()).decode()
    assert passwords.verify(GOOD, legacy) is True
    assert passwords.needs_rehash(legacy) is True
    assert passwords.needs_rehash(passwords.hash_password(GOOD)) is False
    assert passwords.verify(GOOD, UNUSABLE_PASSWORD) is False
    assert passwords.needs_rehash(UNUSABLE_PASSWORD) is False


def test_ipv6_clients_share_a_limit_per_64_block(app):
    from extensions import client_key

    with app.test_request_context(environ_base={"REMOTE_ADDR": "2001:db8:1:2:aaaa::1"}):
        first = client_key()
    with app.test_request_context(environ_base={"REMOTE_ADDR": "2001:db8:1:2:bbbb::9"}):
        second = client_key()
    with app.test_request_context(environ_base={"REMOTE_ADDR": "203.0.113.7"}):
        v4 = client_key()
    assert first == second == "2001:db8:1:2::/64" and v4 == "203.0.113.7"
```

Run: `docker run --rm -v "$PWD":/repo -w /repo sct-test:dev python -m pytest -q tests/unit/test_passwords.py`
Expected: FAIL(`passwords` 모듈 없음).

- [ ] **Step 3: `passwords.py` 구현**

```python
"""비밀번호 정책과 해시(NIST SP 800-63B-4 §3.1.1.2, 2026-09-26 원문 확인).

- NFKC 정규화 후 15~64자, 조합 규칙 없음, 흔한·유출 비밀번호 목록과 전체 일치 거절.
- 저장 형식 "s2$" + bcrypt(base64(sha256(NFKC(비밀번호)))): bcrypt의 72바이트 한계로 뒷부분이 잘리지 않는다.
- 옛 형식($2b$…)은 그대로 검증하고, 로그인에 성공하면 새 형식으로 다시 저장한다(needs_rehash).
"""

from __future__ import annotations

import base64
import functools
import hashlib
import unicodedata
from pathlib import Path

import bcrypt

MIN_LENGTH, MAX_LENGTH = 15, 64
PREFIX = "s2$"
SERVICE_WORDS = ("stockdesk", "tradingdesk")
BLOCKLIST = Path(__file__).with_name("data") / "common-passwords-15plus.txt"


def normalize(password: str) -> str:
    """입력 방식 차이(전각·조합형)를 없앤다. @param password 원문 @returns NFKC 정규화 문자열"""
    return unicodedata.normalize("NFKC", password)


@functools.lru_cache(maxsize=1)
def _blocklist() -> frozenset[str]:
    """차단 목록(소문자). 처음 쓸 때 한 번 읽는다."""
    return frozenset(line.strip() for line in BLOCKLIST.read_text(encoding="utf-8").splitlines() if line.strip())


def problem(password: str, *, email: str = "", nickname: str = "") -> str | None:
    """정책 위반이면 사용자에게 보여 줄 한국어 메시지, 통과면 None.

    @param password 새 비밀번호 @param email 가입 이메일 @param nickname 닉네임
    @returns 위반 메시지 또는 None
    """
    value = normalize(password)
    if len(value) < MIN_LENGTH:
        return f"비밀번호는 {MIN_LENGTH}자 이상이어야 합니다. 문장처럼 길게 만들어 보세요."
    if len(value) > MAX_LENGTH:
        return f"비밀번호는 {MAX_LENGTH}자 이하여야 합니다."
    lowered = value.lower()
    if len(set(lowered)) == 1:
        return "같은 글자만 반복한 비밀번호는 쓸 수 없습니다."
    if lowered in _blocklist():
        return "널리 알려진 비밀번호라 쓸 수 없습니다."
    for word in (email.split("@", 1)[0].lower(), normalize(nickname).lower(), *SERVICE_WORDS):
        if len(word) >= 3 and word in lowered:
            return "이메일·닉네임·서비스 이름이 들어간 비밀번호는 쓸 수 없습니다."
    return None


def _prehash(password: str) -> bytes:
    """bcrypt 입력을 44바이트로 고정한다(잘림 방지)."""
    return base64.b64encode(hashlib.sha256(normalize(password).encode("utf-8")).digest())


def hash_password(password: str) -> str:
    """저장용 해시. @param password 새 비밀번호 @returns "s2$..." 문자열"""
    return PREFIX + bcrypt.hashpw(_prehash(password), bcrypt.gensalt()).decode("ascii")


def verify(password: str, stored: str | None) -> bool:
    """저장된 해시와 비교한다. bcrypt가 아닌 값(UNUSABLE_PASSWORD 등)은 항상 False.

    @param password 입력 비밀번호 @param stored 저장된 해시 @returns 일치 여부
    """
    if not stored:
        return False
    try:
        if stored.startswith(PREFIX):
            return bcrypt.checkpw(_prehash(password), stored[len(PREFIX):].encode("ascii"))
        return bcrypt.checkpw(password.encode("utf-8"), stored.encode("utf-8"))
    except ValueError:
        return False


def needs_rehash(stored: str | None) -> bool:
    """옛 bcrypt 형식이면 True. @param stored 저장된 해시 @returns 새 형식으로 바꿔야 하는지"""
    return bool(stored) and stored.startswith("$2")


@functools.lru_cache(maxsize=1)
def dummy_hash() -> str:
    """없는 계정도 bcrypt를 한 번 돌려 응답 시간을 맞추는 데 쓰는 해시."""
    return hash_password("timing-equaliser-not-a-real-password")
```

`extensions.py`:

```python
"""Flask extensions shared by blueprints and bound in create_app()."""

import ipaddress

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


def client_key() -> str:
    """IP 기준 제한 키. IPv6는 /64로 묶어 주소를 바꿔 가며 우회하지 못하게 한다. @returns 제한 키"""
    address = get_remote_address()
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return address
    return str(ipaddress.ip_network(f"{ip}/64", strict=False)) if ip.version == 6 else address


# Storage and the on/off switch come from app.config (RATELIMIT_STORAGE_URI,
# RATELIMIT_ENABLED), set by Settings.flask_config().
limiter = Limiter(key_func=client_key)
```

- [ ] **Step 4: 가입·로그인·관리자 연결**
  - `members.py`: `import passwords`. `_hash_password`와 `_check_password`를 삭제한다.
  - `register()`: `password2` 비교 다음 줄에 추가하고, 회원 생성은 `password=passwords.hash_password(password)`로 한다.

```python
    weak = passwords.problem(password, email=email, nickname=username)
    if weak:
        return jsonify({"field": "password", "error": weak}), 400
```

  - `login()`:

```python
def _login_email_key() -> str:
    """이메일 기준 제한 키(실패만 센다). @returns "login:<소문자 이메일>" """
    body = request.get_json(silent=True) or {}
    return "login:" + str(body.get("email") or "").strip().lower()


@member_bp.post("/login")
@limiter.limit("10 per minute")
@limiter.limit("30 per hour", key_func=_login_email_key, deduct_when=lambda response: response.status_code == 401)
def login():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip()
    password = body.get("password") or ""
    if not email or not password:
        return jsonify({"error": "이메일과 비밀번호를 입력해주세요."}), 400

    with session_scope() as db:
        member = db.query(Member).filter(Member.email == email).first()
        # 없는 계정도 bcrypt를 한 번 돌려 응답 시간으로 가입 여부가 드러나지 않게 한다.
        matched = passwords.verify(password, member.password if member else passwords.dummy_hash())
        if not (member and matched and can_sign_in(member.email, current_app.config["APP_PROFILE"])):
            return jsonify({"error": "아이디 또는 비밀번호가 맞지 않습니다."}), 401
        if passwords.needs_rehash(member.password):
            member.password = passwords.hash_password(password)
        member_id, username, asset = member.member_id, member.username, member.asset
    member_sessions.start(member_id)
    return jsonify({"username": username, "asset": asset})
```

  - `bootstrap.create_admin`
    - `MIN_ADMIN_PASSWORD_LENGTH`와 그 검사를 지운다.
    - 대신 `weak = passwords.problem(password, email=email)`로 검사하고, 걸리면 `ValueError(weak)`를 던진다.
    - 해시는 `passwords.hash_password(password)`로 만든다.
    - "updated"이면 `with` 밖에서 `member_sessions.end_all(member_id)`를 부른다(재설정한 관리자의 기존 세션 종료).
  - `accounts.py` 8행 주석의 `members._check_password`를 `passwords.verify`로 바꾼다.

- [ ] **Step 5: 단위 테스트 통과**

Run: `docker run --rm -v "$PWD":/repo -w /repo sct-test:dev python -m pytest -q -m "not integration"`
Expected: 전체 통과. `test_create_admin_command_reports_validation_errors`가 12자 기준 문구에 기대면 15자 기준 메시지로 기대값을 고친다(기준 자체는 낮추지 않는다).

- [ ] **Step 6: 통합 테스트 추가**

`tests/integration/test_member_sessions.py` 끝에 추가한다.

```python
def test_short_passwords_are_refused_at_signup():
    response = _client().post("/api/member/register", json={
        "username": "짧음", "email": f"short-{uuid.uuid4().hex[:8]}@example.test",
        "password": "fourteen-chars", "password2": "fourteen-chars"})
    assert response.status_code == 400 and response.get_json()["field"] == "password"


def test_legacy_hashes_are_upgraded_on_login(email):
    import bcrypt

    with db.engine.begin() as conn:
        conn.execute(text("UPDATE member SET password = :p WHERE email = :e"),
                     {"p": bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt()).decode(), "e": email})
    _login(email)
    with db.engine.connect() as conn:
        stored = conn.execute(text("SELECT password FROM member WHERE email = :e"), {"e": email}).scalar()
    assert stored.startswith("s2$")


def test_email_limit_counts_only_failures(email):
    application = create_app(Settings(profile="local", secret_key="k" * 40, session_cookie_secure=False,
                                      ratelimit_enabled=True))
    application.config.update(TESTING=True)
    client = application.test_client()

    def attempt(password, i):
        return client.post("/api/member/login", json={"email": email, "password": password},
                           environ_base={"REMOTE_ADDR": f"198.51.100.{i}"}).status_code

    assert [attempt(PASSWORD, i) for i in range(3)] == [200] * 3
    statuses = [attempt("wrong-password-xyz", 10 + i) for i in range(31)]
    assert statuses[:30] == [401] * 30 and statuses[30] == 429
```

(요청마다 `REMOTE_ADDR`을 바꿔 IP 제한(분당 10회)이 먼저 걸리지 않게 한다.)

`tests/integration/test_member_accounts.py`의 `test_create_admin_makes_an_account_that_can_sign_in_and_is_admin`이 쓰는 비밀번호가 15자 미만이거나 차단 목록에 걸리면, 테스트 값을 `"admin-passphrase-for-tests"` 계열로 바꾼다.

Run: `scripts/verify/stack.sh itest`
Expected: 전체 통과.

- [ ] **Step 7: Commit** — `feat: 비밀번호를 NIST 기준(15자·차단 목록·잘림 없음)으로 검사하고 로그인을 강화한다`

---

### Task 4: F1 확장, PR C, 증거

- [ ] **Step 1: F1 비밀번호 정책 단계**
  - `f1_accounts.py`의 가입 앞에 14자 비밀번호로 가입을 시도한다. 400이고 `field == "password"`인지 확인한다.
  - 정상 비밀번호는 `"verify-" + secrets.token_hex(8)`(23자)로 두어 15자 기준을 만족시킨다.

Run: `scripts/verify/stack.sh up && scripts/verify/stack.sh doctor && python3 scripts/verify/f1_accounts.py && python3 scripts/verify/f2_backtest.py && scripts/verify/stack.sh down`
Expected: 모두 PASS, 익명 볼륨 수 불변.

- [ ] **Step 2: 로그인 소요 시간 실측(스펙 ⑥ 성능)**
  - 로컬 검증 스택에서 `curl -w '%{time_total}'`로 로그인 10회를 측정해 중앙값을 기록한다.
  - 공개 서버 측정은 S1b의 배포 확인 때 한다(가입이 닫혀 있어 계정을 만들 수 없다).

- [ ] **Step 3: 교차 모델 보안 검토(T0-4)**
  - PR B와 PR C의 diff를 Codex 읽기 전용(`codex exec -s read-only`)으로 검토한다. 스펙 위협 모델 표를 기준으로 삼는다.
  - `ecc:security-reviewer`로도 한 번 검토한다.
  - 높음 이상 지적은 재현 테스트부터 쓰고 고친다.

- [ ] **Step 4: 증거 문서** — `docs/evidence/s1-account-core-2026-09-26.md`에 각 PR의 테스트·검증 스킬·배포 확인·검토 결과를 표로 남긴다.

- [ ] **Step 5: PR C → CI → 머지 → 공개 배포**
  - 배포한 뒤 SSM으로 다음을 확인한다: `/health` 200, `signupOpen: false`, 옛 쿠키로 `/api/member/me` 요청 시 로그아웃 상태.
