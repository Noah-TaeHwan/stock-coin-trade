# AWS 공개 데모 배포 절차

[ADR-0003](../adr/0003-aws-demo-topology.md)의 구성을 처음 올리는 순서다. 명령은 `ap-northeast-2`를 예로 든다. **아직 실행한 적 없다.**

## 1. 스택 만들기

```bash
aws cloudformation deploy --region ap-northeast-2 --stack-name stockdesk \
  --template-file infra/cloudformation/stockdesk.yaml --capabilities CAPABILITY_IAM \
  --parameter-overrides BudgetEmail=<메일> MonthlyBudgetUsd=30 InstanceType=t3.medium
aws cloudformation describe-stacks --stack-name stockdesk --query 'Stacks[0].Outputs'
```

- 계정에 GitHub OIDC 공급자가 이미 있으면 다음을 추가한다: `CreateGitHubOidcProvider=false ExistingGitHubOidcProviderArn=<ARN>`
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
2. Caddy는 첫 요청 때 인증서를 받는다. 80·443이 열려 있어야 한다.

## 4. GitHub

1. `.github/deploy.pending.yml`을 `.github/workflows/deploy.yml`로 옮긴다.
2. 저장소 Settings → Environments에서 `production`을 만든다. 승인자(required reviewers) 지정을 권장한다.
3. 같은 환경에 변수를 넣는다. 모두 비밀값이 아닌 식별자다.
   - `AWS_REGION`, `AWS_DEPLOY_ROLE_ARN`, `EC2_INSTANCE_ID`, `RELEASE_BUCKET`, `LOG_GROUP`: 스택 출력값
   - `SITE_ADDRESS`: 도메인
4. Actions → Deploy → Run workflow로 배포한다.

## 5. 배포 후

Session Manager로 접속해 관리자 계정과 AI 초대 코드를 만든다.

```bash
aws ssm start-session --target <InstanceId>
sudo docker compose -p stockdesk exec python-backend flask --app app create-admin
sudo docker compose -p stockdesk exec python-backend flask --app app create-invite --label <이름> --max-requests 20
```

## 되돌리기

- **자동**: `deploy.sh`는 새 릴리스의 `/health`가 150초 안에 통과하지 않으면 직전 릴리스를 다시 올린다.
- **수동**: 이전 커밋 SHA로 워크플로를 다시 실행한다. ECR 태그는 변경 불가(IMMUTABLE)다.
- **스택 삭제 시**: 데이터 볼륨은 스냅샷으로, 로그 그룹과 S3 버킷은 그대로 남는다.
