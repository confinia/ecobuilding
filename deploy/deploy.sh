#!/bin/bash
# EcoBuilding — deploy from the laptop to the VM (shared-edge pattern).
#   ./deploy/deploy.sh            rsync + build + (re)start stack + edge vhost
# Requirements: ssh alias "confinia" (~/.ssh/config), podman-compose on the VM.
set -eu

HOST=confinia
DEST='~/projects/ecobuilding'

cd "$(dirname "$0")/.."

echo "== rsync sources -> $HOST:$DEST"
rsync -az --delete \
  --exclude .git --exclude __pycache__ --exclude .venv --exclude node_modules \
  --exclude deploy/secrets.env \
  ./ "$HOST:$DEST/"

echo "== remote: secrets, podman socket, build & up"
ssh "$HOST" bash -s <<'EOF'
set -eu
cd ~/projects/ecobuilding

# Grafana admin password: generated once, kept out of git.
if [ ! -f deploy/secrets.env ]; then
  echo "GF_SECURITY_ADMIN_PASSWORD=$(openssl rand -base64 18)" > deploy/secrets.env
  chmod 600 deploy/secrets.env
  echo "   -> deploy/secrets.env generated (grafana admin password)"
fi

# Rootless podman socket for the podman-exporter.
systemctl --user is-active --quiet podman.socket || systemctl --user enable --now podman.socket

podman-compose build
podman-compose up -d

# Edge vhost: drop into the shared caddy and graceful-reload.
cp deploy/edge/ecobuilding.caddy ~/projects/confinia/deploy/sites/ecobuilding.caddy
~/projects/confinia/deploy/deploy-edge.sh
EOF

echo "== smoke checks"
sleep 3
curl -fsS https://ecobuilding.confinia.io/api/v1/healthz && echo
curl -fsS -o /dev/null -w "frontend: %{http_code}\n" https://ecobuilding.confinia.io/
curl -fsS -o /dev/null -w "grafana:  %{http_code}\n" https://ecobuilding.confinia.io/grafana/login
echo "OK — https://ecobuilding.confinia.io"
