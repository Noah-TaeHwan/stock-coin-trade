# F1 회원

사용자가 가입하고, 로그인 상태를 확인하고, 로그아웃과 재로그인을 한다. S1 계정·신뢰 기반 작업이 인증 메일·재설정·모든 기기 로그아웃·탈퇴를 이 지도에 더한다.

## 하위 기능

- `f1-register`: 가입하면 곧바로 로그인 상태가 된다(S1 뒤에는 "인증 메일 발송"으로 바뀐다).
- `f1-me`: `/api/member/me`가 로그인 여부와 프로필을 알려 준다.
- `f1-logout`: 로그아웃하면 `loggedIn: false`. 로그아웃 전에 복사해 둔 쿠키도 서버 세션이 지워져 거부된다.
- `f1-logout-all`: 모든 기기 로그아웃 뒤에는 다른 기기의 세션도 로그아웃 상태다.
- `f1-login`: 같은 이메일·비밀번호로 다시 로그인한다.

## 사용자 경로

- 화면: `/member/register.html`, `/member/login.html`, 상단 메뉴의 로그아웃.
- API: `POST /api/member/register`, `POST /api/member/login`, `POST /api/member/logout`, `POST /api/member/logout-all`, `GET /api/member/me`.

## 주행

전제 조건: `scripts/verify/stack.sh doctor`가 `ok`, 프로필 `local`.

- **전체 흐름.** 가입부터 재로그인, 복사한 쿠키 거부, 모든 기기 로그아웃까지 한 번에 돈다. `python3 scripts/verify/f1_accounts.py`를 실행한다. `F1: PASS`와 증거 경로가 출력되고, `member` 행이 1개다.
- **화면 확인.** 쿠키 없는 Playwright로 `http://127.0.0.1:3334/member/login.html`을 연다. 이메일과 비밀번호 칸이 있고 로그인 버튼이 보인다. 캡처는 같은 증거 폴더에 `login.png`로 저장한다.

## 함정

- nginx는 모르는 경로에도 `index.html`을 200으로 돌려준다. 상태 코드만 보고 "백엔드가 응답했다"고 판단하지 말고 JSON 본문을 확인한다(`/health`는 `{"status": "ok"}`).
- public 프로필은 S1 이후 가입이 닫혀 있다(`signupOpen: false`, 가입 403). 검증 스택은 local이다.
- 세션은 서버 표(`member_session`)로 확인한다. DB가 멈추면 로그인한 사용자도 로그아웃 상태로 보인다(의도된 fail closed).
- 이메일은 실행마다 새로 만든다(`@example.test`). 고정 주소를 쓰면 두 번째 실행에서 "이미 존재"로 실패한다.
- 로그인 제한(IP당 분당 10회)은 local 프로필에서 꺼져 있다. public에서 반복하면 429가 난다.
