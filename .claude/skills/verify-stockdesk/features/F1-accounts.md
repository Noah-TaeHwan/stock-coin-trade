# F1 회원

사용자가 가입하고 메일로 인증한 뒤 로그인·로그아웃하고, 메일로 비밀번호를 재설정하고, 로그인한 채 비밀번호를 바꾼다. 탈퇴는 S1b PR E에서 더한다.

## 하위 기능

- `f1-register`: 가입하면 `202 {"status": "check_email"}`만 받는다. 이미 가입된 주소여도 같은 응답이다(가입 여부 비노출).
- `f1-verify`: 인증 전 로그인은 401. 메일의 `/member/verify.html#t=…` 토큰으로 인증하면 로그인된다. 같은 토큰은 두 번 못 쓴다.
- `f1-password-policy`: 15자 미만 비밀번호는 가입에서 400(`field: password`)으로 거절된다.
- `f1-me`: `/api/member/me`가 로그인 여부와 프로필을 알려 준다.
- `f1-logout`: 로그아웃하면 `loggedIn: false`. 로그아웃 전에 복사해 둔 쿠키도 서버 세션이 지워져 거부된다.
- `f1-logout-all`: 모든 기기 로그아웃 뒤에는 다른 기기의 세션도 로그아웃 상태다.
- `f1-login`: 같은 이메일·비밀번호로 다시 로그인한다.
- `f1-reset`: 재설정 요청은 늘 202. 메일의 `/member/reset.html#t=…`로 새 비밀번호를 정하면 옛 비밀번호는 401, 새 비밀번호는 200.
- `f1-change`: 로그인한 채 현재 비밀번호를 확인하고 바꾸면 이 기기는 로그인 상태를 유지한다.

## 사용자 경로

- 화면: `/member/register.html`, `/member/login.html`, 상단 메뉴의 로그아웃.
- API: `POST /api/member/register`, `/verify`, `/verify/resend`, `/login`, `/logout`, `/logout-all`, `/password/reset-request`, `/password/reset`, `/password/change`, `GET /api/member/me`.
- 메일: 검증 스택 Mailpit(`common.mail_link`로 읽음).

## 주행

전제 조건: `scripts/verify/stack.sh doctor`가 `ok`, 프로필 `local`.

- **전체 흐름.** 가입 → 메일 인증 → 로그인·로그아웃(복사 쿠키 거부)·모든 기기 로그아웃 → 메일 재설정 → 비밀번호 변경을 한 번에 돈다(22단계). `python3 scripts/verify/f1_accounts.py`를 실행한다. `F1: PASS`와 증거 경로가 출력되고, `member` 행이 1개다. 증거에는 토큰·비밀번호가 `***`로만 남는다.
- **화면 확인.** 쿠키 없는 Playwright로 `http://127.0.0.1:3334/member/login.html`을 연다. 이메일과 비밀번호 칸이 있고 로그인 버튼이 보인다. 캡처는 같은 증거 폴더에 `login.png`로 저장한다.

## 함정

- nginx는 모르는 경로에도 `index.html`을 200으로 돌려준다. 상태 코드만 보고 "백엔드가 응답했다"고 판단하지 말고 JSON 본문을 확인한다(`/health`는 `{"status": "ok"}`).
- public 프로필은 S1 이후 가입이 닫혀 있다(`signupOpen: false`, 가입 403). 검증 스택은 local이다.
- 세션은 서버 표(`member_session`)로 확인한다. DB가 멈추면 로그인한 사용자도 로그아웃 상태로 보인다(의도된 fail closed).
- 검증 스택은 Mailpit이 있어 **메일 인증 모드**다. 가입만으로는 로그인되지 않는다. 메일이 늦으면 `mail_link`가 15초까지 기다린다.
- 증거 가림은 키 이름(`password`·`token` 등)으로 한다. 새 단계에서 비밀 값을 적을 때는 키 이름에 그 단어를 넣는다(`current_password`).
- 이메일은 실행마다 새로 만든다(`@example.test`). 고정 주소를 쓰면 두 번째 실행에서 "이미 존재"로 실패한다.
- 로그인 제한(IP당 분당 10회)은 local 프로필에서 꺼져 있다. public에서 반복하면 429가 난다.
