#!/usr/bin/env bash
set -euo pipefail

# EC2 인스턴스의 저장소 루트에서 실행한다. 소스에서 빌드하지 않고
# ECR_REGISTRY와 IMAGE_TAG가 가리키는 이미지를 당겨와 실행한다.
: "${ECR_REGISTRY:?Set ECR_REGISTRY to your ECR registry}"
: "${IMAGE_TAG:?Set IMAGE_TAG to a pushed ECR image tag}"
REGION="${AWS_REGION:-ap-northeast-2}"
aws ecr get-login-password --region "$REGION" | \
  docker login --username AWS --password-stdin "$ECR_REGISTRY"

docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --no-build --remove-orphans
docker compose ps
