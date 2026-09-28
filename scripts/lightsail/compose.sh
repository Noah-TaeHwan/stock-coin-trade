#!/bin/bash
# Lightsail host wrapper for docker compose (installed as /opt/stockdesk/compose.sh, run as root).
#   sudo /opt/stockdesk/compose.sh up -d | ps | logs -f python-backend | exec mariadb sh
# RELEASE_DIR holds the unpacked release (compose files + docker/ configs) of IMAGE_TAG.
# app.env (0600) holds the secrets; it is never printed.
set -euo pipefail
IMAGE_TAG="${IMAGE_TAG:?set IMAGE_TAG (release commit SHA)}"
RELEASE_DIR="${RELEASE_DIR:-/opt/stockdesk/releases/${IMAGE_TAG}}"
export IMAGE_TAG
export SITE_ADDRESS="${SITE_ADDRESS:-13-124-251-180.sslip.io}"
export LAB_ADDRESS="${LAB_ADDRESS:-lab.13-124-251-180.sslip.io}"
exec docker compose --project-name stockdesk --profile local-db --project-directory "${RELEASE_DIR}" \
  --env-file /opt/stockdesk/app.env \
  -f "${RELEASE_DIR}/docker-compose.yml" -f "${RELEASE_DIR}/compose.public.yml" \
  -f "${RELEASE_DIR}/compose.edge.yml" -f "${RELEASE_DIR}/compose.lightsail.yml" "$@"
