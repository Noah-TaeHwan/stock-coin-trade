#!/usr/bin/env bash
# Deploy one release on the EC2 host (run as root, normally through SSM Run Command).
#
#   deploy.sh <release-dir> <image-tag>
#
# <release-dir> holds the compose files and docker/ configs of the commit being
# deployed (the CI workflow unpacks them from S3). Required environment:
#   AWS_REGION, ECR_REGISTRY, LOG_GROUP, SITE_ADDRESS
# Optional: PARAM_PATH (default /stock-coin-trade/prod), STATE_DIR (default /opt/stockdesk)
#
# Steps: secrets from SSM Parameter Store -> env file (0600) -> ECR login ->
# pull -> up -> health check through nginx. If the new release is unhealthy
# and an earlier one is recorded, that release is started again and the
# script exits non-zero.
set -euo pipefail

RELEASE_DIR="${1:?usage: deploy.sh <release-dir> <image-tag>}"
IMAGE_TAG="${2:?usage: deploy.sh <release-dir> <image-tag>}"
: "${AWS_REGION:?set AWS_REGION}"
: "${ECR_REGISTRY:?set ECR_REGISTRY}"
: "${LOG_GROUP:?set LOG_GROUP}"
: "${SITE_ADDRESS:?set SITE_ADDRESS}"
PARAM_PATH="${PARAM_PATH:-/stock-coin-trade/prod}"
STATE_DIR="${STATE_DIR:-/opt/stockdesk}"
ENV_FILE="$STATE_DIR/app.env"
export AWS_REGION ECR_REGISTRY LOG_GROUP SITE_ADDRESS IMAGE_TAG

mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"

# Parameter names become variable names: /stock-coin-trade/prod/secret_key -> SECRET_KEY.
write_env_file() {
  local tmp
  tmp="$(mktemp "$STATE_DIR/app.env.XXXXXX")"
  chmod 600 "$tmp"
  aws ssm get-parameters-by-path --region "$AWS_REGION" --path "$PARAM_PATH" --recursive --with-decryption \
    --query 'Parameters[].[Name,Value]' --output text |
    while IFS=$'\t' read -r name value; do
      key="$(basename "$name" | tr '[:lower:]-' '[:upper:]_')"
      [[ "$key" =~ ^[A-Z][A-Z0-9_]*$ ]] || { echo "skipping parameter with an invalid name: $name" >&2; continue; }
      printf '%s=%s\n' "$key" "$value" >>"$tmp"
    done
  mv "$tmp" "$ENV_FILE"
}

# The databases run on the same host; in docker-compose.yml they sit behind the local-db profile.
compose() {
  docker compose --project-name stockdesk --profile local-db --project-directory "$1" --env-file "$ENV_FILE" \
    -f "$1/docker-compose.yml" -f "$1/compose.public.yml" -f "$1/compose.edge.yml" -f "$1/compose.aws.yml" \
    "${@:2}"
}

healthy() {
  local dir="$1"
  for _ in $(seq 1 30); do
    if compose "$dir" exec -T frontend wget -q -O - http://127.0.0.1/health >/dev/null 2>&1; then
      return 0
    fi
    sleep 5
  done
  return 1
}

write_env_file
aws ecr get-login-password --region "$AWS_REGION" |
  docker login --username AWS --password-stdin "$ECR_REGISTRY" >/dev/null

compose "$RELEASE_DIR" pull --quiet
compose "$RELEASE_DIR" up -d --remove-orphans

if healthy "$RELEASE_DIR"; then
  printf '%s\n%s\n' "$RELEASE_DIR" "$IMAGE_TAG" >"$STATE_DIR/current"
  echo "deployed $IMAGE_TAG"
  exit 0
fi

echo "release $IMAGE_TAG is unhealthy" >&2
if [[ -f "$STATE_DIR/current" ]]; then
  mapfile -t previous <"$STATE_DIR/current"
  if [[ "${previous[1]:-}" != "$IMAGE_TAG" ]]; then
    echo "rolling back to ${previous[1]}" >&2
    IMAGE_TAG="${previous[1]}" compose "${previous[0]}" up -d --remove-orphans
  fi
fi
exit 1
