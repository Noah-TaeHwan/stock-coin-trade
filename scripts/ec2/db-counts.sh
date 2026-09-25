# shellcheck shell=bash
# Row counts shared by backup-db.sh and restore-check.sh (sourced, not run).
#
# Each counter prints one "<table> <count>" line per base table, sorted by table name.
export LC_ALL=C # sort and join must agree on the order

container() {
  docker ps -q -f "label=com.docker.compose.project=${COMPOSE_PROJECT:-stockdesk}" -f "label=com.docker.compose.service=$1"
}

MARIA_COUNTS="SET SESSION group_concat_max_len = 1000000;
SELECT GROUP_CONCAT(CONCAT('SELECT ''', table_name, ''', COUNT(*) FROM \`', table_name, '\`') SEPARATOR ' UNION ALL ')
  INTO @q FROM information_schema.tables WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE';
PREPARE s FROM @q; EXECUTE s;"
PG_COUNTS="SELECT table_schema || '.' || table_name, (xpath('/row/c/text()', query_to_xml(format(
  'SELECT count(*) AS c FROM %I.%I', table_schema, table_name), false, true, '')))[1]::text
  FROM information_schema.tables WHERE table_type = 'BASE TABLE'
  AND table_schema NOT IN ('pg_catalog', 'information_schema') ORDER BY 1"

# maria_counts <container> <shell command that runs the mariadb client with -N on the database>
maria_counts() { docker exec -i "$1" sh -c "$2" <<<"$MARIA_COUNTS" | sed 's/^/mariadb:/' | sort; }
# pg_counts <container>: uses the container's own POSTGRES_USER / POSTGRES_DB
pg_counts() {
  # shellcheck disable=SC2016 # expanded inside the container
  docker exec -i "$1" sh -c 'exec psql -At -F " " -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<<"$PG_COUNTS" |
    sed 's/^/postgres:/' | sort
}
# live_counts <mariadb container> <postgres container>
live_counts() {
  # shellcheck disable=SC2016 # expanded inside the container, where the credentials live
  maria_counts "$1" 'MYSQL_PWD="$MARIADB_PASSWORD" exec mariadb -u"$MARIADB_USER" -N mockinv'
  pg_counts "$2"
}

# compare_counts <restored "<table> <count>" file> <manifest "<table> <before> <after>" file>
# A table whose count did not change while it was dumped must be restored exactly; one that changed
# must land between the two counts. A table missing on either side fails.
compare_counts() {
  join -a 1 -a 2 -e MISSING -o 0,1.2,2.2,2.3 "$1" "$2" | awk '
    BEGIN { print "table restored before after result" }
    {
      lo = ($3 < $4) ? $3 : $4; hi = ($3 < $4) ? $4 : $3
      if ($2 == "MISSING" || $3 == "MISSING") result = "FAIL-missing"
      else if ($3 == $4) result = ($2 == $3) ? "exact" : "FAIL"
      else result = ($2 >= lo && $2 <= hi) ? "changed-during-dump" : "FAIL"
      print $1, $2, $3, $4, result
      if (result ~ /^FAIL/) bad = 1
    }
    END { exit bad }'
}
