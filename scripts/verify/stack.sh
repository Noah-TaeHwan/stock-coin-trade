#!/usr/bin/env bash
# 검증 전용 스택(stockdesk-verify, 127.0.0.1:3334)을 올리고·점검하고·내린다.
# 사용법: scripts/verify/stack.sh up|doctor|down   종료 코드: 0 통과, 1 실패, 2 전제 불충족
set -euo pipefail
cd "$(dirname "$0")/../.."

PROJECT=stockdesk-verify
PORT=3334
ENV_FILE=.env.verify
ART=.verify-artifacts
HERE=$(pwd -P)
# ponytail: 검증 스택은 한 번에 한 체크아웃만 쓴다. 병렬 검증이 필요해지면 프로젝트 이름·포트를 체크아웃별로 나눈다.

# 셸 환경을 비우고 docker 연결에 필요한 변수만 넘긴다. 앱 설정 값은 .env.verify에서만 온다.
compose() {
  env -i PATH="$PATH" HOME="$HOME" \
    ${DOCKER_HOST:+DOCKER_HOST="$DOCKER_HOST"} ${DOCKER_CONTEXT:+DOCKER_CONTEXT="$DOCKER_CONTEXT"} \
    ${DOCKER_CONFIG:+DOCKER_CONFIG="$DOCKER_CONFIG"} ${BUILDX_CONFIG:+BUILDX_CONFIG="$BUILDX_CONFIG"} \
    docker compose -p "$PROJECT" --env-file "$ENV_FILE" \
    -f docker-compose.yml -f compose.portfolio.yml --profile local-db "$@"
}

dangling() { docker volume ls -qf dangling=true | wc -l | tr -d ' '; }
running() { [ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT")" ]; }
# docker compose가 컨테이너에 붙이는 working_dir 라벨 = 스택을 띄운 체크아웃 경로
owner() {
  docker ps -aq --filter "label=com.docker.compose.project=$PROJECT" | head -1 |
    xargs docker inspect -f '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' 2>/dev/null
}
mine() { [ "$(owner)" = "$HERE" ]; }

# 처음 한 번 무작위 값으로 .env.verify를 만든다(권한 600, 값은 출력하지 않음).
make_env() {
  [ -f "$ENV_FILE" ] && return 0
  python3 - "$ENV_FILE" "$PORT" <<'PY'
import os
import secrets
import sys

path, port = sys.argv[1], sys.argv[2]
values = {
    "FRONTEND_PORT": port, "MARIADB_USER": "mockinv",
    "MARIADB_PASSWORD": secrets.token_hex(24), "MARIADB_ROOT_PASSWORD": secrets.token_hex(24),
    "QUANT_DB_NAME": "quant_research", "QUANT_DB_USER": "quant", "QUANT_DB_PASSWORD": secrets.token_hex(24),
    "SECRET_KEY": secrets.token_hex(32),
}
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as out:
    out.writelines(f"{key}={value}\n" for key, value in values.items())
PY
}

service_id() {
  docker ps -aq --filter "label=com.docker.compose.project=$PROJECT" --filter "label=com.docker.compose.service=$1"
}

case "${1:-}" in
  up)
    if running && ! mine; then
      echo "up: ${PROJECT}가 다른 체크아웃($(owner))에서 쓰는 중입니다. 그쪽에서 down한 뒤 다시 실행하세요"
      exit 2
    fi
    mkdir -p "$ART"
    dangling > "$ART/pre-dangling.txt"
    make_env
    # worker는 외부 시세 사이트를 부르는 주기 작업이라 띄우지 않는다. frontend가 backend·init·DB를 끌어온다.
    compose up -d --build --wait frontend
    echo "up: ok project=$PROJECT port=$PORT"
    ;;
  doctor)
    frontend=$(docker ps -q --filter "label=com.docker.compose.project=$PROJECT" --filter "label=com.docker.compose.service=frontend")
    [ -n "$frontend" ] || { echo "doctor: $PROJECT frontend 컨테이너가 없습니다"; exit 2; }
    mine || { echo "doctor: 이 체크아웃이 띄운 스택이 아닙니다($(owner))"; exit 2; }
    published=$(docker port "$frontend" 80/tcp | head -1)
    [ "$published" = "127.0.0.1:$PORT" ] || { echo "doctor: 포트 ${PORT}가 이 프로젝트 것이 아닙니다(${published})"; exit 2; }
    curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null || { echo "doctor: /health 실패"; exit 2; }
    init=$(service_id init)
    code=$(docker inspect -f '{{.State.ExitCode}}' "$init")
    [ "$code" = 0 ] || { echo "doctor: init 종료 코드 $code"; exit 2; }
    profile=$(curl -fsS "http://127.0.0.1:$PORT/api/member/me" | python3 -c 'import json,sys; print(json.load(sys.stdin)["profile"])')
    jev=$(docker exec "$(service_id python-backend)" sh -c 'echo "${JEV_ENABLED:-unset}"')
    [ "$profile" = local ] || { echo "doctor: 프로필이 local이 아닙니다(profile=$profile)"; exit 2; }
    [ "$jev" = false ] || { echo "doctor: 과금 기능 Jev가 꺼져 있지 않습니다(jev=$jev)"; exit 2; }
    echo "doctor: ok profile=$profile jev=$jev port=$PORT"
    ;;
  down)
    if running; then
      mine || { echo "down: 이 체크아웃이 띄운 스택이 아닙니다($(owner)). 띄운 쪽에서 정리하세요"; exit 2; }
      [ -f "$ENV_FILE" ] || { echo "down: $ENV_FILE 없이는 compose로 정리할 수 없습니다"; exit 1; }
      compose down -v --remove-orphans
    fi
    after=$(dangling)
    if [ -f "$ART/pre-dangling.txt" ]; then
      before=$(cat "$ART/pre-dangling.txt")
      [ "$after" -le "$before" ] || { echo "down: 익명 볼륨이 늘었습니다 ${before}→${after}"; exit 1; }
      echo "down: ok 익명 볼륨 ${before}→${after}"
    else
      echo "down: 기준 없음(up 기록 없음), 현재 익명 볼륨 $after"
    fi
    ;;
  *)
    echo "사용법: $0 up|doctor|down"; exit 2 ;;
esac
