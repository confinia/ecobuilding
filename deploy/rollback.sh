#!/bin/bash
# EcoBuilding — roll production (slot A) back to the previous promoted version.
set -eu

HOST=confinia

ssh "$HOST" 'bash -s' <<'EOF'
set -eu
cd ~/projects/ecobuilding

PREV=$(cat deploy/.prev_prod_sha 2>/dev/null || true)
[ -n "$PREV" ] || { echo "No previous production version recorded"; exit 1; }

podman tag "ecobuilding-api:${PREV}"      ecobuilding-api:latest
podman tag "ecobuilding-frontend:${PREV}" ecobuilding-frontend:latest
podman-compose up -d --force-recreate api frontend
mv deploy/.prod_sha deploy/.prev_prod_sha.tmp 2>/dev/null || true
echo "${PREV}" > deploy/.prod_sha
mv deploy/.prev_prod_sha.tmp deploy/.prev_prod_sha 2>/dev/null || true
echo "Rolled production back to ${PREV}."
EOF

sleep 5
curl -fsS https://ecobuilding.confinia.io/api/v1/healthz && echo