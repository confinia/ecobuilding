#!/bin/bash
# EcoBuilding — promote the version validated on staging (slot B) to
# PRODUCTION (slot A). Records the previous prod version for rollback.sh.
set -eu

HOST=confinia
cd "$(dirname "$0")/.."

ssh "$HOST" 'bash -s' <<'EOF'
set -eu
cd ~/projects/ecobuilding

STAGING_SHA=$(cat deploy/.staging_sha 2>/dev/null || true)
[ -n "$STAGING_SHA" ] || { echo "No staged version (deploy/.staging_sha missing) — run deploy.sh first"; exit 1; }

# Staging must be healthy before it may take production traffic.
curl -fsS -m 5 http://127.0.0.1:8110/v1/healthz >/dev/null || { echo "Staging API unhealthy — refusing to promote"; exit 1; }

# Remember what prod runs right now (for rollback).
PROD_SHA=$(cat deploy/.prod_sha 2>/dev/null || echo "")
[ -n "$PROD_SHA" ] && echo "$PROD_SHA" > deploy/.prev_prod_sha

# Point :latest at the validated image and recreate slot A.
podman tag "ecobuilding-api:${STAGING_SHA}"      ecobuilding-api:latest
podman tag "ecobuilding-frontend:${STAGING_SHA}" ecobuilding-frontend:latest
podman-compose up -d --force-recreate api frontend
echo "${STAGING_SHA}" > deploy/.prod_sha
echo "Promoted ${STAGING_SHA} to production."
EOF

echo "== production smoke checks"
sleep 5
curl -fsS https://ecobuilding.confinia.io/api/v1/healthz && echo
curl -fsS -o /dev/null -w "prod frontend: %{http_code}\n" https://ecobuilding.confinia.io/
echo "OK — https://ecobuilding.confinia.io"
