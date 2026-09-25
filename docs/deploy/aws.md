# AWS 공개 데모 배포 절차

[ADR-0003](../adr/0003-aws-demo-topology.md)의 구성을 처음 올리는 순서다. 명령은 `ap-northeast-2`를 예로 든다.

## 1. 스택 만들기

```bash
aws cloudformation deploy --region ap-northeast-2 --stack-name stockdesk \
  --template-file infra/cloudformation/stockdesk.yaml --capabilities CAPABILITY_IAM \
  --parameter-overrides BudgetEmail=<메일> MonthlyBudgetUsd=35 InstanceType=t3.small
aws cloudformation describe-stacks --stack-name stockdesk --query 'Stacks[0].Outputs'
```

- 계정에 GitHub OIDC 공급자가 이미 있으면 다음을 추가한다: `CreateGitHubOidcProvider=false ExistingGitHubOidcProviderArn=<ARN>`
- 예산은 인스턴스 크기에 맞춘다. 서울 온디맨드 기준(2026-09-25 가격 API) t3.small은 EBS 50 GiB·공인 IPv4를 더해 월 약 $28, t3.medium은 약 $46이다. t3.medium이면 `MonthlyBudgetUsd=50`으로 올린다.
- 적용 전에 변경 내용을 보려면 `--no-execute-changeset`으로 변경 세트만 만든다.

## 2. 비밀값(SSM Parameter Store, SecureString)

파라미터 이름의 마지막 부분이 환경변수 이름이 된다. 예: `/stock-coin-trade/prod/secret-key` → `SECRET_KEY`

| 이름 | 내용 |
|---|---|
| `secret-key` | 32자 이상 무작위 값 |
| `admin-email` | 관리자 주소(`admin@admin.com` 불가) |
| `mariadb-user`, `mariadb-password`, `mariadb-root-password` | MariaDB 계정 |
| `quant-db-name`, `quant-db-user`, `quant-db-password` | PostgreSQL 계정 |
| `anthropic-api-key` | AI 리서치를 켤 때만 |
| `ai-enabled`, `ai-monthly-budget-usd`, `ai-invite-pepper` | AI를 켤 때: `true`, 월 예산(USD), 32자 이상 무작위 값 |

```bash
aws ssm put-parameter --type SecureString --name /stock-coin-trade/prod/secret-key --value "$(openssl rand -base64 48)"
```

## 3. 도메인

1. 스택 출력 `PublicIp`로 A 레코드를 만든다.
   - 도메인이 없으면 `SITE_ADDRESS`에 `<IP의 점을 대시로>.sslip.io`(예: `3-35-1-2.sslip.io`)를 쓴다. 이 이름은 그 IP로 풀리므로 A 레코드 없이 Caddy가 인증서를 받는다. 나중에 도메인을 사면 변수만 바꾸고 다시 배포한다.
2. Caddy는 첫 요청 때 인증서를 받는다. 80·443이 열려 있어야 한다.

## 4. GitHub

워크플로는 `.github/workflows/deploy.yml`이고 수동 실행(`workflow_dispatch`)만 받는다.

1. 저장소 Settings → Environments에서 `production`을 만든다. 승인자(required reviewers) 지정은 선택이다.
2. 같은 환경에 변수를 넣는다. 모두 비밀값이 아닌 식별자다.
   - `AWS_REGION`, `AWS_DEPLOY_ROLE_ARN`, `EC2_INSTANCE_ID`, `RELEASE_BUCKET`, `LOG_GROUP`: 스택 출력값
   - `SITE_ADDRESS`: 도메인
3. Actions → Deploy → Run workflow로 배포한다.

## 5. 배포 후

Session Manager로 접속해 관리자 계정과 AI 초대 코드를 만든다.

```bash
aws ssm start-session --target <InstanceId>
sudo docker compose -p stockdesk exec python-backend flask --app app create-admin
sudo docker compose -p stockdesk exec python-backend flask --app app create-invite --label <이름> --max-requests 20
```

## 6. DB 백업과 복구 확인

`scripts/ec2/`의 두 스크립트는 릴리스 묶음에 함께 실려 호스트의 `/opt/stockdesk/releases/<sha>/scripts/ec2/`에 있다. SSM Run Command나 Session Manager에서 root로 실행한다.

```bash
export AWS_REGION=ap-northeast-2
# 두 DB를 덤프하고 덤프 전후 행 수(counts.tsv)를 기록한다. 모두 성공해야 s3://<ReleaseBucket>/backups/<UTC 시각>/에 올린다(35일 뒤 자동 삭제)
bash scripts/ec2/backup-db.sh <ReleaseBucket>
# 임시 컨테이너(같은 이미지)에 복구하고 테이블별 행 수를 백업의 counts.tsv와 대조한다(덤프 중 안 바뀐 테이블은 정확히 일치)
bash scripts/ec2/restore-check.sh s3://<ReleaseBucket>/backups/<UTC 시각>
```

- 호스트 역할은 `backups/*`의 객체 읽기·쓰기만 가능하고 버킷 목록은 볼 수 없다. 그래서 복구 확인은 파일 이름으로 하나씩 받는다.
- `counts.tsv`는 맨 마지막에 올라간다. 이 파일이 없는 백업은 업로드가 중간에 끊긴 것이므로 쓰지 않는다.
- 복구 확인용 임시 컨테이너와 볼륨(운영 DB 사본)은 끝나면 지운다. 남았는지 보려면 `docker volume ls -qf dangling=true`.
- 실제로 되살릴 때는 서비스를 멈춘 뒤 같은 덤프를 `mariadb`/`pg_restore --clean`으로 운영 컨테이너에 넣는다. 리허설 기록: [정비 2026-09-26](../evidence/maintenance-2026-09-26.md).
- 정기 실행(타이머)은 아직 없다. 필요하면 `deploy.sh`에서 systemd 타이머를 설치하는 방식으로 추가한다.

## 되돌리기

- **자동**: `deploy.sh`는 새 릴리스의 `/health`가 150초 안에 통과하지 않으면 직전 릴리스를 다시 올린다.
- **수동**: 이전 커밋 SHA로 워크플로를 다시 실행한다. ECR 태그는 변경 불가(IMMUTABLE)다.
- **스택 삭제 시**: 데이터 볼륨은 스냅샷으로, 로그 그룹과 S3 버킷은 그대로 남는다.
