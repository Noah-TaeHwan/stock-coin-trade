# 정비: nginx·주문·모델·백업 — 2026-09-26

Phase 0~7 이후 남은 후속 과제 다섯 가지를 처리한 기록이다. PR #14(nginx), #15(주문), #16(모델), 이 문서의 PR(백업)로 나눴다.

## 1. 백엔드만 재생성해도 502가 나지 않게 (PR #14)

- **문제**: nginx가 `python-backend` 주소를 시작할 때 한 번만 풀어 두었다. 백엔드 컨테이너만 새로 만들어 IP가 바뀌면 frontend를 재시작하기 전까지 `/api`·`/openapi`·`/health`가 모두 502였다.
- **수정**: `resolver 127.0.0.11 valid=10s` + `proxy_pass http://$backend`(로컬·공개 설정 모두).

| 단계 (로컬 스택) | `/health` | `/api/quant/sources` |
|---|---|---|
| 수정 전: 기존 IP(.5)를 임시 컨테이너로 점유 → 백엔드 재생성(.7) | 502 | 502 |
| 수정 후: 다시 IP 이동(.7 → .5), frontend 재시작 없음 | 200 | 200 |

- AWS: 재배포 뒤 실행 중인 nginx 설정(`nginx -T`)에 resolver와 `$backend`가 들어간 것을 SSM으로 확인했다. 운영 중인 공개 데모에서 백엔드를 일부러 재생성하는 시험은 하지 않았다(짧은 중단을 만들기 때문, 로컬 재현으로 갈음).

## 2. 코인 전량 매도 자릿수, 주식 주문 시뮬레이션 기록 (PR #15)

- 코인 보유 수량은 매수 때 소수 8자리로 저장되는데, 매도 요청 수량은 그대로 비교했다. 보유 `0.12345679`에 `0.123456794`로 전량 매도하면 "매도 가능 개수 초과"로 거절됐다. 체결과 미리보기 모두 요청 수량을 8자리로 맞춘다. 기존 `== 0` 비교는 저장값이 이미 8자리라 안전했다.
- `stock_order.simulated` 열 추가. 새 DB는 `db.sql`, 기존 DB는 `init-db`의 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`.

| 확인 | 결과 |
|---|---|
| 새 단위 테스트 | 수정 전 4개 실패 → 수정 후 통과 |
| **옛** `db.sql`로 만든 MariaDB 11.4 | 열 없음 → `create_tables()` 뒤 `simulated tinyint(1) NOT NULL DEFAULT 0`, 통합 테스트 12개 통과 |
| AWS 재배포 후 운영 DB | `simulated tinyint(1) NO 0` (SSM 조회) |

## 3. AI 리서치 에이전트 기본 모델 → Claude Opus 5.5 (PR #16)

- 이전 기록에서 "`claude-opus-5`가 현재 ID 목록에 없다"고 한 것은 틀렸다. 레거시지만 사용 가능한 모델이다. 후속인 `claude-opus-5-5`가 더 싸서($4/$20 per MTok, Opus 5는 $5/$25) 바꿨다.
- Opus 5.5는 기본 effort가 `medium`이라 이전 기본값 `high`를 명시했다. 요청 형태(adaptive thinking, 어시스턴트 content 그대로 되돌림, 강제 `tool_choice` 없음)는 그대로 호환된다.
- 공개 데모 `/api/agent/status` → `{"enabled": false, "model": "claude-opus-5-5"}`. 실제 API 호출은 하지 않았다(AI 기능 꺼짐, 미검증).

## 4. 재배포 (Deploy 실행 `36154908909`, 커밋 `c01d8a7`)

| 확인 | 결과 |
|---|---|
| 배포 워크플로 | success |
| `/health`, 화면 6개(`/`, `/login.html`, `/quant.html`, `/arbitrage.html`, `/trade/stock.html`, `/research-agent.html`), `/api/quant/sources`, `/api/agent/status` | 모두 200 |
| 같은 백테스트 두 번(`005930`, `ma2050`) | 201 → 200, 같은 receiptId `a73bec97…` |
| 컨테이너 | 7개 실행 중(DB 2개 healthy) |

## 5. DB 백업과 복구 리허설 (이 PR)

- `scripts/ec2/backup-db.sh`: 덤프 직전·직후 테이블별 행 수를 세고(`counts.tsv`), MariaDB(`mariadb-dump --single-transaction`)와 PostgreSQL(`pg_dump -Fc`)을 임시 폴더에 덤프한다. **모든 단계가 성공해야** `s3://<ReleaseBucket>/backups/<UTC>/`에 올리고, `counts.tsv`를 맨 마지막에 올려 완료 표지로 쓴다. 비밀번호는 컨테이너 안의 환경변수에서만 쓴다.
- `scripts/ec2/restore-check.sh`: 같은 이미지의 임시 컨테이너에 복구하고 행 수를 `counts.tsv`와 대조한다. 덤프 중 바뀌지 않은 테이블은 **정확히 일치**해야 하고, 바뀐 테이블은 전후 값 사이여야 한다. `counts.tsv`가 없으면(업로드 중단) 거절한다. 임시 컨테이너는 볼륨까지(`rm -fv`) 지운다. 실DB는 조회하지 않는다.
- `scripts/ec2/db-counts.sh`: 두 스크립트가 함께 쓰는 행 수 세기·비교 함수.
- 배포 묶음에 `scripts/ec2` 전체를 싣도록 워크플로를 고쳤다(전에는 `deploy.sh`만 실렸다).

| 리허설 | 결과 |
|---|---|
| 단위 테스트(가짜 docker·aws) | 덤프 실패 시 S3 호출 0회, 성공 시 덤프 2개 → `counts.tsv` 순서로 업로드. 비교 판정 6가지(정확 일치·빈 복구·덤프 중 변동·범위 밖·누락·추가 테이블) |
| AWS 1차 | 백업 성공, **복구 확인 실패**: 호스트 역할에 `s3:ListBucket`이 없어 `--recursive` 다운로드가 막혔고 `--quiet`가 오류를 숨겼다 → 권한은 그대로 두고 파일 이름으로 받기, `--only-show-errors` |
| AWS 2차 | 통과했지만 독립 검증(Reality Checker)에서 결함 2건 발견: ① 임시 DB 볼륨(운영 DB 사본 163 MB + 47 MB)이 호스트에 남음 ② 판정이 "복구본 ≤ 실DB"라 빈 복구본도 통과할 수 있었음 → 남은 볼륨을 ID로 지우고(로컬 2개, AWS 2개) 위 설계로 고쳤다 |
| 로컬 스택(Amazon Linux 2023 컨테이너) | 30개 테이블 모두 `exact`, 볼륨 수 8 → 8, 임시 컨테이너 0 |
| AWS 3차 | 덤프 11 KB + 74 KB, MariaDB 18개·PostgreSQL 12개 테이블 **모두 `exact`**, 복구 1초·전체 13초, 볼륨 수 5 → 5(떨어진 볼륨 0), 임시 컨테이너 0, 메모리 사용 767 MiB / 1,909 MiB |

- AWS 1·2차 백업(`backups/20260925T154152Z`, `…154225Z`)에는 `counts.tsv`가 없어 새 확인 스크립트가 거절한다. 35일 수명 주기로 지워진다.

## 하지 않은 것

- 정기 백업(타이머): `deploy.sh`나 스택 변경이 필요해 따로 제안한다.
- 운영 DB에 실제로 되살리는 연습(서비스 중단 필요). 절차는 [배포 절차](../deploy/aws.md) 6절.
