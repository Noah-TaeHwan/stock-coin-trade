# 공용 데모·모바일 수정 공개 반영 — 2026-09-27

후속 작업에서 아래에 미검증으로 남겼던 보유자산 차트와 물타기 모달을 재현·수정·검증하고 PR #48로 공개 반영했다. 최신 결과는 [보유자산 후속 기록](holdings-followup-2026-09-27.md)을 따른다.

**공개 반영과 실제 데모 로그인을 확인했다.** 로그인 주소는 <https://43-201-225-127.sslip.io/member/login.html>이다. 이메일 `test@test.com`, 비밀번호 `test1234`를 직접 입력하거나 **데모로 로그인** 버튼을 사용한다. 공용 모의 거래·메모는 다른 방문자와 공유된다.

## 반영 근거

- 사용자 승인: 커밋·PR·병합·배포 후 운영 데모 계정 생성과 공개 검증까지 진행.
- [PR #46](https://github.com/Noah-TaeHwan/stock-coin-trade/pull/46): 원본 `97c3f94a367d3ec24a0b5cbbc8f541d844cfddf2`, 병합 `d300274378eca66ae119f588cc1eff610f4d64b8`.
- [PR CI](https://github.com/Noah-TaeHwan/stock-coin-trade/actions/runs/36307597024): 단위·린트·JS·의존성 검사, MariaDB/PostgreSQL 통합 검사, Compose·이미지 빌드 모두 성공. 병합 후 main CI도 성공했다.
- 배포 전 백업: `s3://stockdesk-releasebucket-gf74rqgmybe0/backups/20260927T085353Z`. MariaDB·PostgreSQL·행 수 기록 완료, SSM `93377fc7-4be4-4f24-a038-d91cee970b9f`, 종료 코드 0.
- [배포 실행](https://github.com/Noah-TaeHwan/stock-coin-trade/actions/runs/36308604405): 18:11:59 KST 시작, 18:15:01 KST 최종 성공. SSM 배포 `45bde405-57dc-43a0-accf-796ebb536458`, 종료 코드 0, 서버 현재 릴리스가 위 병합 SHA와 일치했다.
- 새 백엔드의 `GIT_SHA`를 확인한 뒤 `flask --app app create-demo` 실행: `created`, 재실행 `unchanged`. SSM `9d08ae29-2a81-4ddf-9c67-61ba5d54a00d`, 종료 코드 0. 기존 회원을 덮어쓰지 않았다.
- 배포한 프런트 7파일의 HTTPS 응답 SHA-256이 검증한 소스와 모두 일치했다.

## 공개 사이트에서 확인한 동작

Ego Browser의 작업 공간 27에서 실제 화면을 확인했다. 운영 API 검사는 별도 쿠키 저장소를 사용했으며 토큰·세션 원문은 기록하지 않았다.

| 항목 | 결과 |
|---|---|
| 익명 `/api/member/me?demo=1` | public, signupOpen false, demoReady true, loggedIn false |
| 가입 화면 390px | 가입 폼 숨김, 닫힘 안내와 데모 정보 표시, 문서폭 390px |
| 실제 데모 버튼 | 가입 안내→로그인 화면→버튼 클릭→`/trade/stock.html`, 운영 로그인 상태 확인 |
| 데모 권한 | isDemo true, isAdmin false, canUseKisAccount false |
| API 키 목록 | 정상 로그인 상태에서 403 `DEMO_ACCOUNT` |
| 공개 가입 API | 403 `SIGNUP_CLOSED` |
| 독립 API 세션 로그아웃 | 200 후 loggedIn false |
| 메인·퀀트 768px | innerWidth와 scrollWidth가 모두 768px |
| 주식 390px | 실제 로그인 후 innerWidth와 scrollWidth가 모두 390px |
| 분석 390px | 제목 겹침 0, 첫 본문 제목이 화면 안에 표시됨. 목차 높이 294px 안에서 내용 934px 스크롤 |
| 계정 설정 390px | 변경·탈퇴·전체 로그아웃 폼 숨김, 공용 계정 안내 표시, 문서폭 390px |

브라우저 검증 시작 시 이미 데모 계정으로 로그인된 상태를 발견했다. 익명 상태는 `credentials: omit` 요청과 별도 HTTP 쿠키 저장소로 확인했고, 화면에서는 데모 버튼을 직접 눌러 로그인 경로를 재확인했다. 기존 브라우저 쿠키를 전체 삭제하거나 다른 계정을 로그아웃하지 않았다.

## 증거와 한계

증거 루트: `/Users/noah/portfolios/stock-coin-trade-mobile-recovery/.verify-artifacts/publication/`.

- 배포·계정: `pr46-ci.json`, `pr46-merged.json`, `predeploy-backup-result.json`, `deploy-final.json`, `deploy-ssm-result.json`, `create-demo-result.json`.
- 공개 검증: `live-source-hashes.json`, `live-api-check.py`, `live-api-result.json`, `live-register.json`, `live-browser-login.json`, `live-mobile.json`, `live-register-390.png`, `live-login-390.png`, `live-stock-390.png`.
- 브라우저 작업 공간은 완료 후 닫았다(`ego-finished.json`). 로컬 검증 스택 정리는 [로컬 검증 기록](public-demo-2026-09-27.md)을 따른다.
- 퀀트 스크린샷 저장 중 CDP 시간 초과가 한 번 발생했다. 이미 저장한 DOM 측정값은 보존했고 같은 작업 공간에서 분석·계정 검증을 계속했다. 모든 공개 화면의 스크린샷을 확보했다고 주장하지 않는다.
- 계정 변경·삭제·유효 재설정 토큰·KIS 차단은 로컬 실제 API와 단위·통합 검사에서 검증했다. 운영에서는 파괴적인 계정 변경 시험이나 실계좌 요청을 반복하지 않았다.
- 앞선 [모바일 복구 기록](mobile-recovery-2026-09-27.md)의 보유자산 차트·닫힌 물타기 모달 미검증은 유지한다. 이번 공개 반영은 앱 전체 기능의 완료 판정이 아니다.
