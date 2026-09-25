#!/usr/bin/env bash
# Restore a backup into throwaway containers and compare per-table row counts with the live databases.
#
#   restore-check.sh s3://<bucket>/backups/<stamp>
#
# The live databases only receive read-only COUNT(*) queries. The throwaway containers use the same
# images as the running ones and are removed on exit. Market bots keep trading after the backup, so a
# live table may have grown; the check fails on a missing table or a restored count above the live one.
# Required environment: AWS_REGION. Optional: COMPOSE_PROJECT (default stockdesk).
set -euo pipefail

PREFIX="${1:?usage: restore-check.sh s3://<bucket>/backups/<stamp>}"
: "${AWS_REGION:?set AWS_REGION}"

container() {
  docker ps -q -f "label=com.docker.compose.project=${COMPOSE_PROJECT:-stockdesk}" -f "label=com.docker.compose.service=$1"
}
live_maria="$(container mariadb)"
live_pg="$(container postgres)"
tmp_maria="restore-check-maria-$$"
tmp_pg="restore-check-pg-$$"
work="$(mktemp -d)"
cleanup() { docker rm -f "$tmp_maria" "$tmp_pg" >/dev/null 2>&1 || true; rm -rf "$work"; }
trap cleanup EXIT

# File by file: the host role may read backups/* objects but not list the bucket.
for file in mariadb-mockinv.sql.gz postgres-quant.dump; do
  aws s3 cp --region "$AWS_REGION" --only-show-errors "${PREFIX%/}/$file" "$work/$file"
done
docker run -d --name "$tmp_maria" -e MARIADB_ROOT_PASSWORD=restore-check -e MARIADB_DATABASE=mockinv \
  "$(docker inspect -f '{{.Config.Image}}' "$live_maria")" >/dev/null
docker run -d --name "$tmp_pg" -e POSTGRES_PASSWORD=restore-check -e POSTGRES_DB=quant \
  "$(docker inspect -f '{{.Config.Image}}' "$live_pg")" >/dev/null
for _ in $(seq 1 60); do
  if docker exec "$tmp_maria" healthcheck.sh --connect --innodb_initialized >/dev/null 2>&1 &&
    docker exec "$tmp_pg" pg_isready -U postgres -d quant >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

start=$SECONDS
gunzip -c "$work/mariadb-mockinv.sql.gz" | docker exec -i "$tmp_maria" mariadb -uroot -prestore-check mockinv
docker exec -i "$tmp_pg" pg_restore -U postgres -d quant --no-owner --no-privileges <"$work/postgres-quant.dump"
echo "restored in $((SECONDS - start))s ($(du -sh "$work" | cut -f1) of dumps)"

# One "<table> <count>" line per base table.
MARIA_COUNTS="SET SESSION group_concat_max_len = 1000000;
SELECT GROUP_CONCAT(CONCAT('SELECT ''', table_name, ''', COUNT(*) FROM \`', table_name, '\`') SEPARATOR ' UNION ALL ')
  INTO @q FROM information_schema.tables WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE';
PREPARE s FROM @q; EXECUTE s;"
PG_COUNTS="SELECT table_schema || '.' || table_name, (xpath('/row/c/text()', query_to_xml(format(
  'SELECT count(*) AS c FROM %I.%I', table_schema, table_name), false, true, '')))[1]::text
  FROM information_schema.tables WHERE table_type = 'BASE TABLE'
  AND table_schema NOT IN ('pg_catalog', 'information_schema') ORDER BY 1"
maria_counts() { docker exec -i "$1" sh -c "$2" <<<"$MARIA_COUNTS" | sort; }
pg_counts() { docker exec "$1" psql -At -F ' ' -U "$2" -d "$3" -c "$PG_COUNTS" | sort; }

compare() { # compare <name> <restored file> <live file>
  echo "== $1 (table restored live)"
  join -a 2 -e MISSING -o 0,1.2,2.2 "$2" "$3" | awk '
    { print; if ($2 == "MISSING" || $2 + 0 > $3 + 0) bad = 1 }
    END { exit bad }'
}
maria_counts "$tmp_maria" 'exec mariadb -uroot -prestore-check -N mockinv' >"$work/maria.restored"
# shellcheck disable=SC2016 # expanded inside the container, where the credentials live
maria_counts "$live_maria" 'MYSQL_PWD="$MARIADB_PASSWORD" exec mariadb -u"$MARIADB_USER" -N mockinv' >"$work/maria.live"
pg_counts "$tmp_pg" postgres quant >"$work/pg.restored"
pg_counts "$live_pg" "$(docker exec "$live_pg" printenv POSTGRES_USER)" \
  "$(docker exec "$live_pg" printenv POSTGRES_DB)" >"$work/pg.live"

status=0
compare mariadb "$work/maria.restored" "$work/maria.live" || status=1
compare postgres "$work/pg.restored" "$work/pg.live" || status=1
if [[ $status -eq 0 ]]; then echo "restore check passed"; else echo "restore check FAILED" >&2; fi
exit "$status"
