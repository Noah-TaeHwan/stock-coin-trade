#!/usr/bin/env bash
# 검증 전용 스택(stockdesk-verify, 127.0.0.1:3334)을 올리고·점검하고·내린다.
# 사용법: scripts/verify/stack.sh up|doctor|down   종료 코드: 0 통과, 1 실패, 2 전제 불충족
set -euo pipefail
cd "$(dirname "$0")/../.."

PROJECT=stockdesk-verify
PORT=3334
ENV_FILE=.env.verify
ART=.verify-artifacts

# 과금·외부 호출 변수는 셸에 있어도 검증 스택으로 넘기지 않는다.
compose() {
  env -u JEV_ENABLED -u TYPESAFE_API_KEY -u JEV_MONTHLY_BUDGET_USD -u DART_API_KEY \
    docker compose -p "$PROJECT" --env-file "$ENV_FILE" \
    -f docker-compose.yml -f compose.portfolio.yml --profile local-db "$@"
}

dangling() { docker volume ls -qf dangling=true | wc -l | tr -d ' '; }

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
    published=$(docker port "$frontend" 80/tcp | head -1)
    [ "$published" = "127.0.0.1:$PORT" ] || { echo "doctor: 포트 $PORT가 이 프로젝트 것이 아닙니다($published)"; exit 2; }
    curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null || { echo "doctor: /health 실패"; exit 2; }
    init=$(service_id init)
    code=$(docker inspect -f '{{.State.ExitCode}}' "$init")
    [ "$code" = 0 ] || { echo "doctor: init 종료 코드 $code"; exit 2; }
    profile=$(curl -fsS "http://127.0.0.1:$PORT/api/member/me" | python3 -c 'import json,sys; print(json.load(sys.stdin)["profile"])')
    jev=$(docker exec "$(service_id python-backend)" sh -c 'echo "${JEV_ENABLED:-unset}"')
    echo "doctor: ok profile=$profile jev=$jev port=$PORT"
    ;;
  down)
    if [ -f "$ENV_FILE" ]; then compose down -v --remove-orphans; else echo "down: $ENV_FILE 없음, compose 정리 생략"; fi
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
