#!/bin/bash
# EcoBuilding — deploy the current code to the CANDIDATE stack (the one NOT
# serving production). Production stack is never touched: validate on
# https://staging.ecobuilding.confinia.io then run ./deploy/promote.sh.
#
# Model: two complete independent stacks from the same docker-compose.yml
#   ecobuilding-blue  (entry 127.0.0.1:8021)
#   ecobuilding-green (entry 127.0.0.1:8022)
# plus the router (caddy_server/, project ecobuilding-edge, 127.0.0.1:8020)
# which maps prod/staging hostnames to the stacks. State: deploy/.active on VM.
set -eu

HOST=ecobuilding
cd "$(dirname "$0")/.."
SHA=$(git rev-parse --short HEAD 2>/dev/null || echo dev)

echo "== rsync sources -> $HOST:~/projects/ecobuilding (version $SHA)"
rsync -az --delete \
  --exclude .git --exclude __pycache__ --exclude .venv --exclude node_modules \
  --exclude deploy/secrets.env --exclude deploy/.active \
  --exclude caddy_server/Caddyfile --exclude data/ \
  ./ "$HOST:~/projects/ecobuilding/"

# Upstream edge = platform repo (github.com/confinia/platform), run by the
# 'debian' user: its Caddyfile forwards both ecobuilding.confinia.io and
# staging.ecobuilding.confinia.io -> 127.0.0.1:8020 (our router). Managed once,
# out of band (needs sudo); this deploy does not touch it.

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

# Export the secrets so compose files can substitute ${SMTP_*} etc. (#128).
set -a; . deploy/secrets.env; set +a

# Persistent lead storage (offer page), outside git/rsync.
mkdir -p data/leads

# GeoIP db (country-only): reuse the confinia project's copy if not present.
mkdir -p data/geoip
if [ ! -f data/geoip/dbip-country-lite.mmdb ]; then
  cp ~/projects/confinia/data/geoip/dbip-country-lite.mmdb data/geoip/ 2>/dev/null \
    || echo "   WARN: GeoIP db not found — visitor countries will be 'unknown'"
fi

ACTIVE=$(cat deploy/.active 2>/dev/null || echo blue)
echo "$ACTIVE" > deploy/.active
if [ "$ACTIVE" = blue ]; then CANDIDATE=green; else CANDIDATE=blue; fi
echo "   active stack: $ACTIVE — deploying to candidate: $CANDIDATE"

# One-time cleanup of the legacy single-stack deployment (ecobuilding_*).
LEGACY=$(podman ps -a --format '{{.Names}}' | grep -E '^ecobuilding_' || true)
[ -n "$LEGACY" ] && { echo "   removing legacy containers"; echo "$LEGACY" | xargs podman rm -f >/dev/null; }

# Shared identity (Keycloak + postgres), outside blue/green like monitoring.
if ! grep -q KC_DB_PASSWORD deploy/secrets.env; then P=$(openssl rand -hex 24); echo "KC_DB_PASSWORD=$P" >> deploy/secrets.env; echo "POSTGRES_PASSWORD=$P" >> deploy/secrets.env; fi
grep -q KC_BOOTSTRAP_ADMIN_PASSWORD deploy/secrets.env || echo "KC_BOOTSTRAP_ADMIN_PASSWORD=$(openssl rand -base64 18)" >> deploy/secrets.env
( cd auth_stack && podman-compose -p ecobuilding-auth -f docker-compose.yml up -d )
# Realm email (SMTP + verify-email) as code — idempotent, skips if no creds (#128).
./deploy/kc-smtp.sh || echo "   WARN: kc-smtp failed (realm email unchanged)"

# Shared monitoring (promote-proof): prometheus + grafana + podman-exporter.
( cd monitoring_stack && podman-compose -p ecobuilding-monitoring -f docker-compose.yml up -d )

# Remove per-stack monitoring leftovers from the pre-shared-monitoring layout.
for c in grafana prometheus podman-exporter; do
  podman rm -f "ecobuilding-blue_${c}_1" "ecobuilding-green_${c}_1" 2>/dev/null || true
done

# ZERO-DOWNTIME RULE: never touch the ACTIVE stack. Bootstrap it only if it
# does not exist at all; config changes reach it on the NEXT promote cycle.
if ! podman container exists "ecobuilding-${ACTIVE}_api_1" 2>/dev/null; then
  echo "   bootstrap: active stack $ACTIVE absent — creating"
  podman-compose -p "ecobuilding-$ACTIVE" -f docker-compose.yml -f "deploy/$ACTIVE.override.yml" up -d
else
  echo "   active stack $ACTIVE left untouched"
fi

# Build fresh images and fully recreate the CANDIDATE stack.
podman-compose -p "ecobuilding-$CANDIDATE" -f docker-compose.yml -f "deploy/$CANDIDATE.override.yml" build
podman-compose -p "ecobuilding-$CANDIDATE" -f docker-compose.yml -f "deploy/$CANDIDATE.override.yml" up -d --force-recreate

# Router: config must match .active; start or reload.
# (podman-compose 1.3 fails to open "-f subdir/file" — run from inside the dir)
cp "caddy_server/Caddyfile.$ACTIVE" caddy_server/Caddyfile
( cd caddy_server && podman-compose -p ecobuilding-edge -f docker-compose.yml up -d )
# Graceful reload (admin 127.0.0.1:2030); restart only as fallback for the
# one-time transition from an admin-off config.
podman exec ecobuilding-edge_caddy_1 caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile 2>/dev/null \
  || podman restart ecobuilding-edge_caddy_1 >/dev/null

# Upstream (platform) edge is managed separately under the 'debian' user (it
# runs platform_caddy_1 and needs sudo): both ecobuilding.confinia.io and
# staging.ecobuilding.confinia.io are routed there to 127.0.0.1:8020. This
# deploy runs as the unprivileged 'ecobuilding' user and does NOT touch it.

# Hard health gate on the candidate, via its local entry port.
if [ "$CANDIDATE" = blue ]; then PORT=8021; else PORT=8022; fi
sleep 3
curl -fsS -m 10 "http://127.0.0.1:$PORT/api/v1/healthz" >/dev/null && echo "   candidate $CANDIDATE healthy on :$PORT"
EOF

echo "== public smoke (staging)"
sleep 2
curl -fsS -m 10 https://staging.ecobuilding.confinia.io/api/v1/healthz && echo || echo "WARN: public staging check failed (main edge may be mid-churn)"
echo
echo "Version $SHA is on the CANDIDATE stack: https://staging.ecobuilding.confinia.io"
echo "Validate it, then run:  ./deploy/promote.sh"
