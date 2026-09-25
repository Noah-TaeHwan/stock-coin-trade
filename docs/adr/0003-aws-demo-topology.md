# ADR-0003: AWS 공개 데모 구성 — EC2 한 대 + Compose, CloudFormation, OIDC → ECR → SSM

- 상태: 채택(준비 단계, 배포는 아직 안 함) 2026-09-25, Phase 6
- 관련: [검증 기록](../evidence/aws-demo-prep-2026-09-25.md), [운영 절차](../deploy/aws.md)

## 배경

공개 데모에 필요한 것은 네 가지다.
- 포트폴리오를 검토하는 사람이 들어와 볼 수 있을 것
- 비용이 작고 예측 가능할 것
- 비밀값과 배포 권한이 저장소·CI에 남지 않을 것
- 로컬에서 검증한 구성(`compose.public.yml`)과 같을 것

## 결정

1. **단일 EC2 + Docker Compose**
   - 로컬에서 검증한 public 스택(nginx, Flask, worker, MariaDB, PostgreSQL, Redis)을 그대로 올린다.
   - 앞단에 Caddy를 두어 자동 HTTPS를 쓴다.
   - **인스턴스 크기**: 기본은 t3.medium(4 GiB)이다.
     - 로컬 측정(2026-09-25): 요청 처리 중 약 0.35 GiB, 지식 검색 임베딩 모델을 올린 뒤 약 1.0 GiB
     - DB 성장과 이미지 교체 여유를 둔 값이다. t3.small(2 GiB)도 파라미터로 고를 수 있고, user data가 1 GiB 스왑을 만든다.
   - **데이터 보존**: `/var/lib/docker`를 별도 EBS(gp3, 암호화)에 둔다.
     - 이 볼륨은 삭제·교체 때 스냅샷을 남긴다(`DeletionPolicy/UpdateReplacePolicy: Snapshot`).
     - AMI 파라미터가 새 AMI로 풀려 인스턴스가 교체되어도 DB 볼륨은 다시 붙는다.
2. **IaC는 CloudFormation 단일 스택**(`infra/cloudformation/stockdesk.yaml`)
   - AWS 공식 도구라 상태 파일을 따로 관리하지 않는다.
   - 변경 세트(change set)를 증거로 남길 수 있다.
   - `cfn-lint`로 리전별 리소스 스키마를 검사할 수 있다.
   - Terraform은 대안으로만 기록한다.
3. **배포 경로는 GitHub Actions OIDC → ECR → S3 → SSM Run Command**
   - CI에는 AWS 키를 두지 않는다. 배포 역할은 `repo:<저장소>:environment:production` 토큰만 맡을 수 있다(GitHub OIDC 문서의 `sub`·`aud` 조건).
   - 역할 권한은 네 가지뿐이다: 두 ECR 저장소 푸시, `releases/` 업로드, 이 인스턴스에 `AWS-RunShellScript` 실행, 결과 조회.
   - SSH를 열지 않는다. 보안 그룹은 80·443만 연다. 운영자 접속은 Session Manager로 한다.
   - `deploy.sh` 순서
     1. SSM Parameter Store에서 비밀값을 읽어 0600 env 파일을 만든다.
     2. 이미지를 받는다(pull).
     3. 스택을 올린다(up).
     4. nginx `/health`를 확인한다.
     5. 실패하면 직전 릴리스로 되돌린다.
4. **IMDSv2만 허용, 홉 제한 1**
   - 비밀값은 호스트에서 env 파일로 컨테이너에 전달한다.
   - CloudWatch 로그(`awslogs`)는 호스트의 Docker 데몬이 보낸다.
   - 따라서 컨테이너는 메타데이터 서비스가 필요 없고, AWS 권장 컨테이너 설정(홉 2)을 쓸 이유가 없다.
5. **비용 가드**
   - AWS Budgets 월 예산: 실제 80%, 예상 100%에서 메일을 보낸다.
   - ECR은 이미지 20개만 남긴다(수명 주기 정책).
   - S3 릴리스는 90일, 백업은 35일 보관한다.
   - AI 비용은 앱의 초대 코드와 월 예산(ADR 없이 `research_agent.py`)이 막는다.

## 결과

- 로컬에서 검증했다([검증 기록](../evidence/aws-demo-prep-2026-09-25.md)).
  - Caddy 앞단: HTTPS, 리디렉션, 클라이언트 IP 보존
  - `deploy.sh`: 정상 배포와 자동 롤백
  - 템플릿: `cfn-lint` 통과
- 실제 AWS 배포는 Noah의 계정·도메인·비용 승인이 필요하다.
- 한 대 구성이라 인스턴스 장애 때 서비스가 멈춘다. 데모 용도로 받아들인다. 데이터는 별도 볼륨과 스냅샷 정책으로 보존한다.

## 근거(2026-09-25 조회)

- **cfn-lint 1.57.0 번들 스키마**(ap-northeast-2)
  - `AWS::EC2::Instance.MetadataOptions`(HttpTokens, HttpPutResponseHopLimit)
  - `AWS::IAM::OIDCProvider`(ThumbprintList 선택)
  - `AWS::Budgets::Budget`
  - `AWS::ECR::Repository`(ImageScanningConfiguration, LifecyclePolicy, ImageTagMutability)
- **GitHub 문서 "Configuring OpenID Connect in Amazon Web Services"**: `aud`=`sts.amazonaws.com`, `sub`=`repo:OWNER/REPO:environment:NAME`, `id-token: write`
- **Caddy `reverse_proxy` 문서 "Defaults"**: 들어온 `X-Forwarded-*`를 무시하고 `X-Forwarded-For`를 설정한다.
- **액션 커밋 SHA**: `git ls-remote`로 확인
  - aws-actions/configure-aws-credentials v6.3.0 = `e1253824…`
  - amazon-ecr-login v2.1.7 = `03f1aad4…`
- **Docker Compose v2.40.3**: 릴리스 `checksums.txt`의 linux-x86_64 sha256
- **Amazon Linux 2023 SSM 공개 파라미터**: `/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64`
