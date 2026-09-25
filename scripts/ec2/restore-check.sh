#!/usr/bin/env bash
# Restore a backup into throwaway containers and check every table's row count against the backup's
# counts.tsv (written by backup-db.sh).
#
#   restore-check.sh s3://<bucket>/backups/<stamp>
#
# A table that did not change while it was dumped must be restored exactly; one that changed must land
# between its before/after counts. The live databases are not queried at all. The throwaway
# containers use the same images as the running ones and are removed on exit together with their
# volumes, which hold a copy of production data.
# Required environment: AWS_REGION. Optional: COMPOSE_PROJECT (default stockdesk).
set -euo pipefail

PREFIX="${1:?usage: restore-check.sh s3://<bucket>/backups/<stamp>}"
: "${AWS_REGION:?set AWS_REGION}"
# shellcheck source=db-counts.sh source-path=SCRIPTDIR
source "$(dirname "$0")/db-counts.sh"

live_maria="$(container mariadb)"
live_pg="$(container postgres)"
[[ -n "$live_maria" && -n "$live_pg" ]] || { echo "database containers are not running" >&2; exit 1; }
tmp_maria="restore-check-maria-$$"
tmp_pg="restore-check-pg-$$"
work="$(mktemp -d)"
cleanup() { docker rm -fv "$tmp_maria" "$tmp_pg" >/dev/null 2>&1 || true; rm -rf "$work"; }
trap cleanup EXIT

# File by file: the host role may read backups/* objects but not list the bucket. A backup without
# counts.tsv was interrupted before it finished uploading.
for file in mariadb-mockinv.sql.gz postgres-quant.dump counts.tsv; do
  aws s3 cp --region "$AWS_REGION" --only-show-errors "${PREFIX%/}/$file" "$work/$file"
done
docker run -d --name "$tmp_maria" -e MARIADB_ROOT_PASSWORD=restore-check -e MARIADB_DATABASE=mockinv \
  "$(docker inspect -f '{{.Config.Image}}' "$live_maria")" >/dev/null
docker run -d --name "$tmp_pg" -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=restore-check -e POSTGRES_DB=quant \
  "$(docker inspect -f '{{.Config.Image}}' "$live_pg")" >/dev/null
ready=0
for _ in $(seq 1 60); do
  # pg_isready also answers for the entrypoint's temporary init server, so wait for its "complete" line.
  if docker exec "$tmp_maria" healthcheck.sh --connect --innodb_initialized >/dev/null 2>&1 &&
    docker logs "$tmp_pg" 2>&1 | grep -q 'PostgreSQL init process complete' &&
    docker exec "$tmp_pg" pg_isready -U postgres -d quant >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
[[ $ready -eq 1 ]] || { echo "throwaway databases did not become ready within 120s" >&2; exit 1; }

start=$SECONDS
gunzip -c "$work/mariadb-mockinv.sql.gz" | docker exec -i "$tmp_maria" mariadb -uroot -prestore-check mockinv
docker exec -i "$tmp_pg" pg_restore -U postgres -d quant --no-owner --no-privileges <"$work/postgres-quant.dump"
echo "restored in $((SECONDS - start))s ($(du -sh "$work" | cut -f1) incl. counts)"

{
  maria_counts "$tmp_maria" 'exec mariadb -uroot -prestore-check -N mockinv'
  pg_counts "$tmp_pg"
} | sort >"$work/restored"
if compare_counts "$work/restored" "$work/counts.tsv"; then
  echo "restore check passed"
else
  echo "restore check FAILED" >&2
  exit 1
fi
