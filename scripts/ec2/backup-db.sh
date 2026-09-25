#!/usr/bin/env bash
# Back up the demo databases to S3 (run as root on the EC2 host, normally through SSM Run Command).
#
#   backup-db.sh <bucket>
#
# Dumps MariaDB (mockinv) and PostgreSQL (quant) from the running `stockdesk` containers into a
# temporary directory and uploads only after both dumps succeeded, so a failed dump never leaves a
# partial object that looks like a backup. Credentials stay inside the containers (their own
# environment); nothing secret is passed on a command line. The bucket's lifecycle rule deletes
# backups/ objects after 35 days. Check a backup with restore-check.sh.
# Required environment: AWS_REGION. Optional: COMPOSE_PROJECT (default stockdesk).
set -euo pipefail

BUCKET="${1:?usage: backup-db.sh <bucket>}"
: "${AWS_REGION:?set AWS_REGION}"

container() {
  docker ps -q -f "label=com.docker.compose.project=${COMPOSE_PROJECT:-stockdesk}" -f "label=com.docker.compose.service=$1"
}
maria="$(container mariadb)"
pg="$(container postgres)"
[[ -n "$maria" && -n "$pg" ]] || { echo "database containers are not running" >&2; exit 1; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

docker exec "$maria" sh -c \
  'MYSQL_PWD="$MARIADB_PASSWORD" exec mariadb-dump -u"$MARIADB_USER" --single-transaction --no-tablespaces mockinv' |
  gzip >"$work/mariadb-mockinv.sql.gz"
docker exec "$pg" sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' >"$work/postgres-quant.dump"

dest="s3://$BUCKET/backups/$(date -u +%Y%m%dT%H%M%SZ)"
aws s3 cp --region "$AWS_REGION" --recursive --only-show-errors "$work" "$dest"
echo "backed up to $dest"
ls -l "$work"
