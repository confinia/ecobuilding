#!/bin/bash
# EcoBuilding — deploy the current code to the STAGING slot (B) only.
# Production (slot A) is never touched: validate on the preview URL, then run
# ./deploy/promote.sh to switch prod. Requirements: ssh alias "confinia".
#
#   ./deploy/deploy.sh        rsync + build + restart staging + edge vhosts
set -eu

HOST=confinia
cd "$(dirname "$0")/.."
SHA=$(git rev-parse --short HEAD 2>/dev/null || date +%s)

echo "== rsync sources -> $HOST:~/projects/ecobuilding (version $SHA)"
rsync -az --delete \
  --exclude .git --exclude __pycache__ --exclude .venv --exclude node_modules \
  --exclude deploy/secrets.env \
  ./ "$HOST:~/projects/ecobuilding/"

# The shared edge's sites/ dir is owned by the confinia project deploy (it
# deletes foreign files): the vhost must ALSO live in the local confinia-core
# checkout so its own syncs preserve it.
if [ -d "$HOME/project/confinia/deploy/sites" ]; then
  cp deploy/edge/ecobuilding.caddy "$HOME/project/confinia/deploy/sites/ecobuilding.caddy"
fi

echo "== remote: secrets, podman socket, build, staging up, edge"
ssh "$HOST" "ECOBUILDING_SHA=$SHA" 'bash -s' <<'EOF'
set -eu
cd ~/projects/ecobuilding

if [ ! -f deploy/secrets.env ]; then
  echo "GF_SECURITY_ADMIN_PASSWORD=$(openssl rand -base64 18)" > deploy/secrets.env
  chmod 600 deploy/secrets.env
  echo "   -> deploy/secrets.env generated (grafana admin password)"
fi

systemctl --user is-active --quiet podman.socket || systemctl --user enable --now podman.socket

# Build once, remember the version for promote/rollback.
podman-compose build
podman tag ecobuilding-api:latest      "ecobuilding-api:${ECOBUILDING_SHA}"
podman tag ecobuilding-frontend:latest "ecobuilding-frontend:${ECOBUILDING_SHA}"
echo "${ECOBUILDING_SHA}" > deploy/.staging_sha

# Shared services + STAGING slot only. Slot A (api, frontend) is untouched.
podman-compose up -d otel-collector prometheus grafana podman-exporter
podman-compose up -d --force-recreate api-b frontend-b

# Edge vhosts (idempotent; survives confinia deploys via confinia-core copy).
cp deploy/edge/ecobuilding.caddy ~/projects/confinia/deploy/sites/ecobuilding.caddy
~/projects/confinia/deploy/deploy-edge.sh
EOF

echo "== staging smoke checks"
sleep 5
curl -fsS https://next.ecobuilding.confinia.io/api/v1/healthz && echo
curl -fsS -o /dev/null -w "staging frontend: %{http_code}\n" https://next.ecobuilding.confinia.io/
echo
echo "Version $SHA is on STAGING: https://next.ecobuilding.confinia.io"
echo "Validate it, then run:  ./deploy/promote.sh"
