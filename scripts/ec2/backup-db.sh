#!/usr/bin/env bash
# Back up the demo databases to S3 (run as root on the EC2 host, normally through SSM Run Command).
#
#   backup-db.sh <bucket>
#
# Dumps MariaDB (mockinv) and PostgreSQL (quant) from the running `stockdesk` containers and writes
# counts.tsv: every table's row count right before and right after the dumps. restore-check.sh uses it
# to demand an exact match for tables that did not change meanwhile. Nothing is uploaded unless every
# step succeeded, and counts.tsv goes last, so an interrupted upload is never taken for a backup.
# Credentials stay inside the containers; nothing secret is passed on a command line. The bucket's
# lifecycle rule deletes backups/ objects after 35 days.
# Required environment: AWS_REGION. Optional: COMPOSE_PROJECT (default stockdesk).
set -euo pipefail

BUCKET="${1:?usage: backup-db.sh <bucket>}"
: "${AWS_REGION:?set AWS_REGION}"
# shellcheck source=db-counts.sh source-path=SCRIPTDIR
source "$(dirname "$0")/db-counts.sh"

maria="$(container mariadb)"
pg="$(container postgres)"
[[ -n "$maria" && -n "$pg" ]] || { echo "database containers are not running" >&2; exit 1; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

live_counts "$maria" "$pg" >"$work/before"
docker exec "$maria" sh -c \
  'MYSQL_PWD="$MARIADB_PASSWORD" exec mariadb-dump -u"$MARIADB_USER" --single-transaction --no-tablespaces mockinv' |
  gzip >"$work/mariadb-mockinv.sql.gz"
docker exec "$pg" sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' >"$work/postgres-quant.dump"
live_counts "$maria" "$pg" >"$work/after"
join -a 1 -a 2 -e MISSING -o 0,1.2,2.2 "$work/before" "$work/after" >"$work/counts.tsv"

dest="s3://$BUCKET/backups/$(date -u +%Y%m%dT%H%M%SZ)"
for file in mariadb-mockinv.sql.gz postgres-quant.dump counts.tsv; do
  aws s3 cp --region "$AWS_REGION" --only-show-errors "$work/$file" "$dest/$file"
done
echo "backed up to $dest"
ls -l "$work"
