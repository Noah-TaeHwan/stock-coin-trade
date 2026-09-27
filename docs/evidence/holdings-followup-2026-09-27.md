# 보유자산 차트·물타기 모달 후속 검증 — 2026-09-27

## 목표와 기준

사용자가 남은 두 미검증 항목을 마무리하도록 요청했다. 기준은 `27924ed`(제품 PR #46 + 운영 기록 PR #47), 작업 위치는 `/Users/noah/portfolios/stock-coin-trade-holdings-followup`, 브랜치는 `fix/holdings-followup`이다.

1. 임시 검증 계정에 실제 모의 보유 데이터를 만든 뒤 보유자산 차트의 렌더링과 데이터 일치를 확인한다.
2. 물타기 모달을 실제로 열고 4개 비율 버튼의 값·계산·모바일 조작을 확인한다.
3. 재현된 문제만 수정하고 독립 리뷰·재검증 후 필요한 공개 반영을 수행한다.

운영 공용 데모의 거래 데이터와 기존 기록은 보존한다. 검증은 별도 `stockdesk-verify`에서 수행하고 PM 소유 3333 스택에는 접근하지 않는다. [앞선 기록](public-demo-release-2026-09-27.md)의 미검증을 근거 없이 통과로 바꾸지 않는다.

## 재현한 원인과 수정

| 원인 | 수정 |
|---|---|
| 인증 후 모의 주식을 실제 보유한 상태에서도 Highcharts CDN이 403을 반환해 차트가 생성되지 않음 | 동일 11.1.0 공식 npm 배포 JS를 원본 그대로 자체 호스팅. tarball SHA-512와 파일 SHA-256 대조, 원본 헤더·출처 보존 |
| 현금 초과 수량 입력 후 MAX로 정상화해도 남는 현금이 빨강으로 남음 | 정상 상태의 색을 명시해 이전 inline 색상이 남지 않게 함 |
| 요약은 현금·코인만 합산하고 주식·대체자산을 빠뜨림. WebSocket 갱신도 같은 누락을 반복 | 이미 조회한 각 자산의 평가액·원가를 재사용해 요약 6지표와 차트가 같은 전체 합계를 사용 |
| 공개 환경에는 없는 `/api/trade/hold`를 먼저 요청하고 404에서 초기화 중단 | 기존 `/me.profile`·`asset`으로 공개 환경에서는 현금·주식만 조회. 로컬 환경은 전체 자산 유지 |
| 공개 분석 API가 남아 있는 코인·대체자산까지 합산하면 요약과 범위가 달라짐 | 공개 분석에서 해당 DB 조회·외부 시세 호출·대체자산 수집을 생략. 기존 분석 탭은 유지 |
| 합산 구현의 초기 HTTP 대기가 WebSocket 시작을 늦출 수 있음 | 두 경로가 같은 평가액 맵을 사용하고 WebSocket을 먼저 시작. 늦은 HTTP는 이미 수신한 tick을 덮지 않음 |

가격·포지션 조회 실패는 0으로 간주하지 않고 미확정으로 표시한다. 차트는 최초 생성 후 데이터를 갱신하며, 미확정 전환 시 이전 차트를 제거한다. 새 서버 API·설정·패키지 의존성은 추가하지 않았다.

`tests/policy/test_guards.py`는 정확한 vendor 파일 한 개의 SHA-256이 고정값과 일치할 때만 원본 외부 라이브러리로 구분한다. 디렉터리 전체 예외와 기존 G1 baseline 확대는 하지 않았다. 다른 앱 코드의 `innerHTML` 제한은 유지된다.

## 데이터와 검증 구분

기존 F1 방식으로 새 일반 회원을 가입·메일 인증·로그인하고 모의주문 API로 005930 3주를 매수한 뒤 잔고·보유를 다시 조회했다. 물타기 모달의 손실 조건을 만들기 위해 **본인 검증 계정의** 원가·현금·해당 주문만 일관되게 조정한 격리 DB fixture를 사용했다. 실제 시장 손실이 발생했다고 주장하지 않는다. 각 실행 후 임시 회원을 삭제해 DB 잔여 0을 확인했다.

- `run/`: 실제 로그인·매수 후 차트 라이브러리 403 재현.
- `baseline-loss/`: 390·768·1280px에서 4버튼×3폭 계산은 일치, 초과→MAX 후 경고색 잔류 재현.
- `after-source/`: 라이브러리·색상 수정 확인. 당시 요약 oracle은 코인 전용 API라 전체 자산 정확성의 통과 근거로 사용하지 않는다.
- `final-after/`: 주식 평가액을 별도 oracle로 넣어 요약 누락을 FAIL로 재현. 기존 결과를 덮어쓰지 않았다.
- `after-aggregate/`: 실제 API 주식 3주에 대해 현금 99,774,010 + 주식 평가액 221,556 = 총자산 99,995,566, 원가 225,990, 손익 -4,434와 UI·비중 차트 일치. 3개 차트와 실제 주식 탭·섹터 차트 스크롤, 모달 12회 클릭·색상 복원·잔고 불변 확인.
- 혼합 자산·부분 시세·공개 프로필·응답 순서 검사는 브라우저 응답/소켓 fixture다. 실제 서버의 주식 거래 검증과 구분한다.
- `after-mixed-v2/`: 현금·주식·대체자산·코인 합계와 실시간 tick 이후 합계 일치, 일부 시세 누락 시 미확정 표시. 최종 `hold_crypto.js` 제공 해시 `583b9515…` 기준 exit 0.
- `after-mixed-race-gated/`: HTTP 응답을 명시적 Promise gate로 보류한 상태(응답 수 0)에서 WebSocket 값 표시. gate를 연 뒤 오래된 HTTP 응답이 최신 tick을 덮지 않음을 확인, exit 0.
- 공개 프런트 fixture는 local 서버의 프로필 메타데이터만 바꾸므로 실제 public 분석 API의 자산 필터를 입증하지 못한다. 공개 서버 필터는 신규 단위 검사와 이후 운영 검증으로 구분한다.
- `after-public-browser-only/`: 무계정 브라우저 합성 응답에서 현금·주식 요약/차트, 미지원 API·Upbit 요청 0, 분석 탭 사용 가능을 확인, exit 0. 운영 계정·운영 서버 데이터를 모사한 시험은 아니다.
- 공개 fixture 준비 중 시세 조회 시간 초과를 관측했다. 도구 오류문에 포함된 임시 세션 값은 마스킹했고 해당 회원 삭제·DB 잔여 0을 확인했다. 실패 사실과 경로는 보존했으며, 제품 오류로 판정하지 않았다.

## 실행 검사

작업 디렉터리는 위 worktree다. 실행 증거는 `.verify-artifacts/holdings-followup/` 아래에 있다.

- `docker run --rm -v "$PWD":/repo -w /repo sct-test:dev python -m pytest -q -m 'not integration'`: exit 0, **522 passed, 1 skipped, 91 deselected, 4 subtests passed** (`full-unit-final.log`). 네트워크 전용 1건과 통합 표시 91건은 이 실행에 포함하지 않았다.
- `tests/policy` 14 passed. 신규 공개·로컬 분석 회귀 2 passed. `ruff check .`, CI 범위 `ruff format --check`, 수정 JS와 vendor의 `node --check`, `git diff --check` 통과.
- 리더는 `check.cjs leader-after`를 별도 임시 회원으로 실행해 exit 0을 확인하고, 후속 합산 수정의 실제 화면·수치 원본도 직접 대조했다.
- 독립 reviewer가 vendor 출처·정확한 정책 예외·합산·공개 프로필·초기 시세 경계를 검토했고, 지적한 두 경계를 교정한 최종 소스에서 새 차단 오류는 발견하지 못했다. 리뷰는 실행 검증과 구분한다.
- 최종 프런트 4개와 백엔드 `members.py`의 로컬/제공 파일 SHA-256 일치(`final-source-hashes.json`). 전체 명령·종료 코드는 `commands.tsv`, 판단과 중간 실패는 `decisions.tsv`에 있다.
- 검증 전용 스택 `down` exit 0, 컨테이너 0, 익명 볼륨 1→1. `.env.verify`와 원본 증거는 보존했다.

## 최종 상태

**남아 있던 보유자산 차트·물타기 모달 검증을 완료하고 수정 사항을 공개 반영했다.** 이전 단계의 실패·부분 판정은 위에 보존했다.

### 공개 반영

- [PR #48](https://github.com/Noah-TaeHwan/stock-coin-trade/pull/48): 원본 `94b0ae4c75d7ea20d6f29b0fdde1f8b6719dd10d`, 병합 `8b97b918769f6c49aa63304c2eabeeba53c7642e`.
- [필수 CI 3개](https://github.com/Noah-TaeHwan/stock-coin-trade/actions/runs/36311656976): 단위·린트·JS·의존성, MariaDB/PostgreSQL 통합, Compose·이미지 빌드 모두 성공.
- 배포 전 DB 백업: `s3://stockdesk-releasebucket-gf74rqgmybe0/backups/20260927T101047Z`. SSM `14b56b6b-b513-4d0f-a71a-9bf00551c1be`, Success/exit 0.
- [배포 실행](https://github.com/Noah-TaeHwan/stock-coin-trade/actions/runs/36311817216): 19:12:56 KST 시작, 19:16:08 KST 최종 성공. 배포 SSM `3f4bc5db-e276-444f-a270-edb5c91eca79`, exit 0, 위 병합 SHA 적용.
- 공개 프런트 4개 파일(hold HTML, 요약 JS, 주식 JS, vendor)의 HTTPS SHA-256이 최종 소스와 모두 일치했다.

### 실제 운영 확인

Ego Browser 작업 공간 29와 별도 쿠키의 공용 데모 세션으로 확인했다. 공용 데모의 주문·현금·포지션은 변경하지 않았다.

| 항목 | 결과 |
|---|---|
| 배포 전 실제 보유 화면 | 차트 SVG 없음, 현금·총자산 `-` |
| 배포 후 390·768px | Highcharts 11.1.0, 차트 SVG 생성, 문서폭이 요청 폭과 일치 |
| 현재 공용 데모 | 주식 0건, 현금·총자산 100,000,000원, 주식 평가액 0원, 비중 KRW 100% |
| 실제 분석 API | allocation이 현금·주식 2항목이며 totalAsset이 현금+주식 평가액과 일치 |
| 공개 미지원 탭 | 코인·대체자산 탭 숨김 |
| 별도 API 세션 | 데모 로그인 후 읽기 검증, 자체 세션 로그아웃 200 |
| 브라우저 정리 | 작업 공간 완료 후 닫음. 기존 데모 쿠키·다른 세션은 보존 |

운영 공용 데모는 빈 주식 포지션으로 확인했다. 보유 주식이 있는 합산·물타기 손실 계산은 위 격리 검증 계정의 실제 모의 매수/명시적 손실 fixture에서 확인했고, 운영에는 같은 바이트를 제공한다. 운영 데이터에 시험 주문을 넣었다고 주장하지 않는다.

운영 PNG 캡처는 Ego의 `Page.captureScreenshot` 시간 초과와 native viewport 캡처 오류로 저장하지 못했다. 실제 DOM·SVG·차트 series·API·가로폭 원본은 보존했고, 로컬 검증 PNG는 리더가 직접 확인했다. 캡처 복구 진단 중 도구의 viewport가 195×422로 바뀐 관측은 `live-chart-layout.json`에 별도로 남겼으며, 앞선 390·768px 측정과 혼합하지 않는다.

운영 증거는 이 worktree의 `.verify-artifacts/publication/`에 있다: `backup-result.json`, `pr48-merged.json`, `pr48-ci.json`, `deploy-final.json`, `deploy-ssm-result.json`, `live-api-result.json`, `live-before.json`, `live-holdings.json`, `live-holdings-snapshot.txt`, `live-source-hashes.json`, `live-chart-layout.json`, `ego-finished.json`.
