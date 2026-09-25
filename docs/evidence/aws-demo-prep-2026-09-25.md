# AWS 공개 데모 준비(IaC·HTTPS 앞단·배포·롤백) 검증 — 2026-09-25

- 대상 브랜치: `claude/wonderful-faraday-826uz8`(Phase 4 위에 쌓음)
- 포트폴리오 계획 Phase 6의 준비 단계다.
- **AWS에는 아무것도 만들거나 호출하지 않았다.** 계정·도메인·비용 승인은 Noah의 몫이다. 모든 검증은 로컬 Docker와 정적 검사로 했다.
- 설계 결정은 [ADR-0003](../adr/0003-aws-demo-topology.md), 실행 순서는 [배포 절차](../deploy/aws.md)에 있다.

## 만든 것

| 파일 | 내용 |
|---|---|
| `infra/cloudformation/stockdesk.yaml` | 아래 네 묶음 |
| `docker/Caddyfile`, `compose.edge.yml` | Caddy 2.11.4 자동 HTTPS. nginx는 호스트 포트를 열지 않는다 |
| `docker/real-ip.{none,edge}.conf` | nginx가 Caddy 뒤에서 클라이언트 IP를 복원한다. 복원하지 않으면 IP별 요청 제한이 모든 방문자를 하나로 센다 |
| `compose.aws.yml` | ECR 이미지(소스 빌드 없음)와 모든 서비스의 `awslogs` 로그 |
| `scripts/ec2/deploy.sh` | SSM 비밀값 → 0600 env 파일 → ECR 로그인 → pull → up → nginx `/health` → 실패 시 직전 릴리스로 롤백 |
| `.github/deploy.pending.yml` | 배포 워크플로(수동 실행, `production` 환경). 이 세션은 워크플로 파일을 푸시할 수 없어 `.github/workflows/` 밖에 두었다 |
| `tests/unit/test_deploy_infra.py` | 템플릿·오버레이 보안 속성과 `deploy.sh` 로직(가짜 `aws`·`docker`)을 CI에서 검사 |

**`stockdesk.yaml`의 구성**
- **네트워크**: VPC 한 개, 퍼블릭 서브넷 한 개, 보안 그룹. 보안 그룹은 80·443(TCP), 443(UDP, HTTP/3)만 열고 SSH는 열지 않는다.
- **호스트**: EC2(AL2023, IMDSv2 필수, 홉 제한 1), 암호화 gp3 루트 디스크, 탄력적 IP
  - `/var/lib/docker`는 별도 암호화 데이터 볼륨에 둔다. 삭제·교체 때 스냅샷을 남긴다.
  - user data가 Docker, Compose v2.40.3(sha256 검증), 1 GiB 스왑을 설치한다.
- **저장·로그·비용**
  - ECR 2개: 푸시 시 스캔, 태그 변경 불가, 최근 20개 유지
  - S3 버킷: 비공개, TLS만 허용, 버전 관리, 릴리스 90일·백업 35일 보관
  - CloudWatch 로그 그룹: 보존 기간 설정, 스택 삭제 시 보존
  - AWS Budgets: 실제 80%, 예상 100%에서 메일
- **배포 권한**: GitHub OIDC 공급자(선택)와 배포 역할
  - 역할을 맡을 수 있는 토큰: `sub = repo:<저장소>:environment:<환경>`, `aud = sts.amazonaws.com`
  - 권한: 두 ECR 저장소 푸시, `releases/` 업로드, 이 인스턴스에서 `AWS-RunShellScript` 실행과 결과 조회

## 근거(2026-09-25 조회)

- **cfn-lint 1.57.0**(PyPI 최신) 번들 리소스 스키마
  - `AWS::EC2::Instance`에 `MetadataOptions`(HttpTokens, HttpPutResponseHopLimit)가 있다.
  - `AWS::IAM::OIDCProvider`의 `ThumbprintList`는 필수가 아니다.
  - `AWS::ECR::Repository`에 `ImageScanningConfiguration`, `LifecyclePolicy`, `ImageTagMutability`가 있다.
  - `AWS::Budgets::Budget` 속성을 확인했다.
- **GitHub 문서**(docs.github.com, OIDC in AWS)
  - 신뢰 조건 예시: `StringEquals` `aud` = `sts.amazonaws.com`, `sub` = `repo:OWNER/REPO:environment:NAME`
  - 워크플로에 `id-token: write`가 필요하다.
- **Caddy 문서**(Context7 `/websites/caddyserver`, `reverse_proxy` "Defaults"): 들어온 `X-Forwarded-*`를 무시하고 `X-Forwarded-For`를 설정한다.
- **버전·해시**(`git ls-remote`)
  - Caddy 최신 v2.11.4, 이미지 `caddy:2.11.4-alpine`의 `caddy version` 출력으로 확인
  - Docker Compose v2.40.3, 릴리스 `checksums.txt`의 linux-x86_64 sha256
  - aws-actions/configure-aws-credentials v6.3.0 → `e1253824e5c1…`
  - aws-actions/amazon-ecr-login v2.1.7 → `03f1aad4c6c7…`(annotated tag의 커밋)
- **인스턴스 크기**: 로컬 public 스택 실측(`docker stats`). 컨테이너 합계 약 346 MiB, 지식 검색 임베딩을 올린 뒤 약 1012 MiB(백엔드 786 MiB)

## 결과

| 항목 | 방법 | 결과 |
|---|---|---|
| 템플릿 | `cfn-lint --include-checks I --regions ap-northeast-2 us-east-1` | 오류·경고·정보 0 |
| user data | 템플릿에서 추출해 `shellcheck` | 통과 |
| 배포 스크립트 | `shellcheck scripts/ec2/deploy.sh` | 통과 |
| 워크플로 | `actionlint` 1.7.12(shellcheck 연동) | 통과 |
| HTTPS 앞단 | public + edge 스택을 로컬에서 기동(`SITE_ADDRESS=localhost`, Caddy 내부 CA) | 아래 |
| 배포·롤백 | 로컬 레지스트리(registry:2)와 가짜 `aws`로 실제 `deploy.sh` 실행 | 아래 |
| CI용 테스트 | `tests/unit/test_deploy_infra.py` | 9개 통과, 25회 반복 모두 통과 |
| 전체 | `ruff check .`, `pytest`(통합 포함) | 301개 통과, 네트워크 테스트 1개 건너뜀 |

**HTTPS 앞단**
- HTTPS `/health`가 200(HTTP/2)이다.
- HTTP는 308로 HTTPS로 넘어간다.
- 보안 헤더가 유지되고, 응답에 `via: 1.1 Caddy`가 붙는다.
- nginx 접근 로그의 클라이언트가 실제 클라이언트(172.18.0.1)다. Caddy(172.18.0.8)가 아니다.
- 요청에 넣은 `X-Forwarded-For: 6.6.6.6`은 무시됐다.
- 대조 실험: real-ip 스니펫을 빼고 nginx를 다시 띄우면 로그 클라이언트가 Caddy IP로 바뀐다. 이 상태에서는 IP별 제한이 모든 방문자에게 공유된다.

**배포·롤백**
- `good` 릴리스를 배포하면 7개 서비스가 올라온다. HTTPS 헬스 200, `current` 기록, env 파일 권한 600을 확인했다.
- 백엔드가 즉시 종료하는 `bad` 릴리스를 배포했다.
  - 150초 헬스 확인이 실패한다.
  - "rolling back to good" 후 종료 코드 1로 끝난다.
  - 백엔드·워커·프런트가 `good` 이미지로 돌아오고 HTTPS 헬스가 200이다.
- 이 실행에서 버그 하나를 찾아 고쳤다. DB 서비스가 `local-db` 프로필에 있어 `deploy.sh`가 스택을 만들지 못했다(`depends on undefined service "postgres"`). `--profile local-db`를 추가했다.

**CI 테스트 9개가 확인하는 것**
- 80·443만 열려 있다.
- IMDSv2와 디스크 암호화, 데이터 볼륨 스냅샷 정책
- 배포 역할이 한 저장소의 한 환경에만 묶여 있고, IAM·EC2·와일드카드 권한이 없다.
- 버킷이 비공개이고 TLS만 허용한다.
- edge 오버레이가 nginx 포트를 닫고 Caddy 버전을 고정한다.
- aws 오버레이가 ECR 이미지만 쓰고 모든 서비스 로그를 보낸다.
- `deploy.sh`
  - 파라미터 이름을 변수 이름으로 바꾸고, 잘못된 이름은 건너뛰고, 값의 `=`를 보존한다. env 파일은 600이다.
  - 실패 시 직전 릴리스로 롤백한다.
  - 첫 배포가 실패하면 되돌릴 릴리스를 만들어 내지 않는다.

**변형 테스트**: 한 곳씩 틀리게 바꾸고 테스트가 실패하는지 확인했다. 확인 후 모두 되돌렸다.

| 바꾼 것 | 결과 |
|---|---|
| 롤백 제거 | 1개 실패 |
| env 파일 644 | 1개 실패 |
| SSH(22) 개방 | 1개 실패 |
| IMDSv1 허용 | 1개 실패 |
| 모든 브랜치가 배포 역할 사용 | 1개 실패 |
| DB 프로필 누락 | 1개 실패 |
| 데이터 볼륨 스냅샷 없이 삭제 | 1개 실패 |

처음 작성한 가짜 `docker`는 `--password-stdin`을 읽지 않았다. 그래서 `pipefail`에서 SIGPIPE(141)가 간헐적으로 나 테스트가 흔들렸다. 실제 CLI처럼 표준 입력을 읽게 고친 뒤 25회 연속 통과했다.

## 달라진 동작

- `compose.public.yml`이 빈 real-ip 스니펫을 nginx에 마운트한다. 앞단 프록시가 없는 기존 동작은 그대로다.
- `scripts/ec2/deploy.sh`가 새 흐름으로 바뀌었다. 인자로 릴리스 디렉터리와 태그를 받고, 필수 환경변수가 늘었다. 예전 `docker-compose.prod.yml`은 레거시로 표시했다.

## 검증하지 못한 것

- **실제 AWS 배포 전체**: 스택 생성, SSM Run Command, CloudWatch 전송, Budgets 알림, Let's Encrypt 인증서 발급
- **실제 AWS에서만 확인되는 동작**
  - OIDC 신뢰 조건이 실제로 동작하는지
  - Nitro 인스턴스에서 데이터 볼륨의 NVMe 시리얼이 볼륨 ID와 맞는지
  - 인스턴스 교체 후 볼륨이 다시 붙는지
- **비용**: 월 비용을 공식 가격으로 계산하지 않았다. Pricing Calculator로 확인해야 한다.
  - 항목: EC2 t3.medium, EBS gp3 20+30 GiB, 탄력적 IP, CloudWatch Logs, ECR·S3 저장, 데이터 전송
- **DB 백업·복구 리허설**(계획의 should 항목): 아직 만들지 않았다. S3 `backups/` 경로와 권한만 준비했다.
- **워크플로 자체**: 파일이 `.github/workflows/` 밖에 있어 GitHub에서 실행되지 않는다. Noah가 옮겨야 한다.
