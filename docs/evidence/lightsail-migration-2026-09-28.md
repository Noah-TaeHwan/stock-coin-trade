# EC2 → Lightsail 이전 — 2026-09-28

포트폴리오 데모를 "서비스 운영"이 아니라 "외부에서 접속만 되게" 최소 비용으로 유지하려고, EC2 두 대(stockdesk t3.small, 금융상식 랩 t3.micro)를 Lightsail 한 대로 합쳤다. 운영 방법은 [Lightsail 운영](../deploy/lightsail.md)에 있다.

## 결정

| 항목 | 이전 | 이후 |
|---|---|---|
| 서버 | EC2 t3.small(stockdesk) + t3.micro(랩), 탄력적 IP 2개, EBS 80 GB | Lightsail `small_3_0` 1대(2 GB, 60 GB, 고정 IP 포함) |
| 월 비용(서울 온디맨드 가격 API 기준 추정) | 약 $44 | $12 + 보관 스냅샷 약 $1 미만 |
| 이미지 | ECR | 서버 로컬 태그(`stockdesk/*:<SHA>`) |
| 배포 | GitHub OIDC → ECR → SSM, 자동 롤백 | 수동(`docker save`로 전송 → `compose up`) |
| 감시·백업 | Lambda 5분 감시, CloudWatch 경보 2개, 매일 S3 백업 | 없음(월 $15 계정 예산 알림만) |

- 1 GB 서버(t3.micro, Lightsail $7)는 쓰지 않았다. 이전 전 실측 메모리가 stockdesk 약 1.3 GB(백엔드 약 740 MB), 랩 약 0.33 GB였다.
- 이전 후 같은 서버의 실측: 사용 1.16 GB / 1.9 GB, 가용 약 0.75 GB, 스왑 16 MB.

## 절차와 검증

1. Lightsail 인스턴스·고정 IP·방화벽(80/443 공개, 22는 관리자 IP만) 생성, Docker 설치, 스왑 2 GB.
2. stockdesk
   - 릴리스 묶음(`releases/8b97b918….tgz`)과 이미지(마지막 배포 SHA `8b97b918769f6c49aa63304c2eabeeba53c7642e`)를 받았다. ECR 로그인 토큰은 표준 입력으로만 넘기고 로그인 정보 파일은 지웠다.
   - 비밀값은 SSM Parameter Store에서 읽어 서버 `app.env`(0600)로 바로 썼다. 값은 출력하지 않았다.
   - 옛 서버에서 이전 직전에 `backup-db.sh`로 새 백업(`backups/20260928T004659Z`)을 받아 복원했다. `compare_counts` 결과 **35개 테이블 모두 exact**(공시 7,145건, 회원 22명, 주식 주문 2,112건 등).
   - PostgreSQL 첫 복원은 실패했다. 새 컨테이너가 `database/` 초기화 스크립트로 스키마와 샘플을 먼저 만들어 `already exists`·외래 키 오류가 났고, `--clean`도 파티션 기본키 삭제에서 막혔다. `public` 스키마를 비운 뒤 `--single-transaction --exit-on-error`로 다시 넣어 해결했다.
3. 금융상식 랩
   - 앱 이미지(2.7 GB)를 옛 서버에서 새 서버로 직접 스트리밍했다(임시 키, 끝나고 삭제, 22번 임시 허용도 되돌림).
   - Mongo·Qdrant·Meilisearch 볼륨은 컨테이너를 멈춘 상태에서 옮겼다. Mongo 컬렉션 문서 수 두 서버 동일(`quiz_questions` 34, `app_metadata` 1).
   - 작업 중 스크립트 실수로 옛 랩이 약 1분 멈췄다가 다시 떴다. 데이터 영향은 없었다.
4. 외부 확인(HTTPS, Let's Encrypt)
   - `https://13-124-251-180.sslip.io/health` 200, `/`, `/member/login.html`, `/api/disclosures` 200.
   - 브라우저에서 "데모로 로그인" → `/trade/stock.html`, `/api/member/me`: `isDemo true`, `isAdmin false`, `signupOpen false`, `profile public`.
   - `https://lab.13-124-251-180.sslip.io/` 200, `/api/health` 200. 호스트 8000번은 외부에서 닫혀 있음(연결 안 됨).

## 정리한 AWS 자원

- CloudFormation `stockdesk` 스택 삭제(EC2, EIP, VPC, IAM 역할, Lambda, 경보, SNS, 예산). ECR 저장소 2개는 먼저 지웠다.
- 템플릿 정책대로 남은 것: 데이터 볼륨 스냅샷 `snap-066b099629482bb6a`, S3 `stockdesk-releasebucket-gf74rqgmybe0`(릴리스·백업, 수명 주기 만료), 로그 그룹 `/stockdesk/app`.
- 랩 EC2: 디스크 스냅샷 `snap-0b8602f7327b814b6`을 만든 뒤 인스턴스 종료, 탄력적 IP `54.116.230.120` 반납.
- 정리 후 전 리전 EC2 0대, EIP 0개, EBS 볼륨 0개. 새 계정 예산 `portfolio-monthly`($15, 실제 80%·예측 100% 메일).

## 한계

- 옛 주소 `43-201-225-127.sslip.io`는 더 이상 열리지 않는다. 이전 검증 기록의 주소는 당시 기록이라 고치지 않았다.
- GitHub Deploy·Uptime 워크플로는 지운 자원을 가리키므로 쓰지 않는다.
- 자동 백업·감시가 없다. 서버가 죽으면 알림이 오지 않는다.
- 두 스냅샷은 되돌리기용 보관분이다. 한두 주 문제가 없으면 지워도 된다.
