#!/bin/bash
# EcoBuilding — deploy the current code to the CANDIDATE stack (the one NOT
# serving production). Production stack is never touched: validate on
# https://next.ecobuilding.confinia.io then run ./deploy/promote.sh.
#
# Model: two complete independent stacks from the same docker-compose.yml
#   ecobuilding-blue  (entry 127.0.0.1:8021)
#   ecobuilding-green (entry 127.0.0.1:8022)
# plus the router (caddy_server/, project ecobuilding-edge, 127.0.0.1:8020)
# which maps prod/next hostnames to the stacks. State: deploy/.active on VM.
set -eu

HOST=confinia
cd "$(dirname "$0")/.."
SHA=$(git rev-parse --short HEAD 2>/dev/null || echo dev)

echo "== rsync sources -> $HOST:~/projects/ecobuilding (version $SHA)"
rsync -az --delete \
  --exclude .git --exclude __pycache__ --exclude .venv --exclude node_modules \
  --exclude deploy/secrets.env --exclude deploy/.active \
  --exclude caddy_server/Caddyfile \
  ./ "$HOST:~/projects/ecobuilding/"

# Upstream edge = platform repo (github.com/confinia/platform): its Caddyfile
# already forwards ecobuilding.confinia.io -> 127.0.0.1:8020 (our router).
# Only next. may be missing; ensured idempotently on the VM below.

echo "== remote: stacks"
ssh "$HOST" 'bash -s' <<'EOF'
set -eu
cd ~/projects/ecobuilding

if [ ! -f deploy/secrets.env ]; then
  echo "GF_SECURITY_ADMIN_PASSWORD=$(openssl rand -base64 18)" > deploy/secrets.env
  chmod 600 deploy/secrets.env
  echo "   -> deploy/secrets.env generated (grafana admin password)"
fi
systemctl --user is-active --quiet podman.socket || systemctl --user enable --now podman.socket

ACTIVE=$(cat deploy/.active 2>/dev/null || echo blue)
echo "$ACTIVE" > deploy/.active
if [ "$ACTIVE" = blue ]; then CANDIDATE=green; else CANDIDATE=blue; fi
echo "   active stack: $ACTIVE — deploying to candidate: $CANDIDATE"

# One-time cleanup of the legacy single-stack deployment (ecobuilding_*).
LEGACY=$(podman ps -a --format '{{.Names}}' | grep -E '^ecobuilding_' || true)
[ -n "$LEGACY" ] && { echo "   removing legacy containers"; echo "$LEGACY" | xargs podman rm -f >/dev/null; }

# Ensure the ACTIVE stack exists/runs (no rebuild, no recreate).
podman-compose -p "ecobuilding-$ACTIVE" -f docker-compose.yml -f "deploy/$ACTIVE.override.yml" up -d

# Build fresh images and fully recreate the CANDIDATE stack.
podman-compose -p "ecobuilding-$CANDIDATE" -f docker-compose.yml -f "deploy/$CANDIDATE.override.yml" build
podman-compose -p "ecobuilding-$CANDIDATE" -f docker-compose.yml -f "deploy/$CANDIDATE.override.yml" up -d --force-recreate

# Router: config must match .active; start or reload.
cp "caddy_server/Caddyfile.$ACTIVE" caddy_server/Caddyfile
podman-compose -p ecobuilding-edge -f caddy_server/docker-compose.yml up -d
podman exec ecobuilding-edge_caddy_1 caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile 2>/dev/null || true

# Upstream (platform) edge: prod host is already routed to 8020 by the
# platform Caddyfile; ensure next. is too (idempotent append + reload).
if ! grep -q "next.ecobuilding.confinia.io" ~/projects/platform/caddy/Caddyfile 2>/dev/null; then
  printf '\n# next.ecobuilding — staging du routeur ecobuilding (ajout auto par le deploy ecobuilding)\nnext.ecobuilding.confinia.io {\n\treverse_proxy 127.0.0.1:8020\n}\n' >> ~/projects/platform/caddy/Caddyfile
  podman exec platform_caddy_1 caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile 2>/dev/null \
    || echo "   WARN: platform edge reload failed — next. will load on its next reload"
fi

# Hard health gate on the candidate, via its local entry port.
if [ "$CANDIDATE" = blue ]; then PORT=8021; else PORT=8022; fi
sleep 3
curl -fsS -m 10 "http://127.0.0.1:$PORT/api/v1/healthz" >/dev/null && echo "   candidate $CANDIDATE healthy on :$PORT"
EOF

echo "== public smoke (staging)"
sleep 2
curl -fsS -m 10 https://next.ecobuilding.confinia.io/api/v1/healthz && echo || echo "WARN: public staging check failed (main edge may be mid-churn)"
echo
echo "Version $SHA is on the CANDIDATE stack: https://next.ecobuilding.confinia.io"
echo "Validate it, then run:  ./deploy/promote.sh"
