#!/bin/bash
# EcoBuilding — bring the stacks up ON THE VM from ~/projects/ecobuilding.
# Extracted from deploy.sh (#112) so the GitHub Actions runner (which already
# runs on the VM as the ecobuilding user) calls it directly; deploy.sh remains
# the workstation break-glass wrapper (rsync + ssh into this script).
# Deploys the CANDIDATE stack; production is never touched (rule 3).
set -eu
cd "$(dirname "$0")/.."

if [ ! -f deploy/secrets.env ]; then
  echo "GF_SECURITY_ADMIN_PASSWORD=$(openssl rand -base64 18)" > deploy/secrets.env
  chmod 600 deploy/secrets.env
  echo "   -> deploy/secrets.env generated (grafana admin password)"
fi
systemctl --user is-active --quiet podman.socket || systemctl --user enable --now podman.socket

# Shared east-west network (#173) — idempotent.
podman network exists ecobuilding-internal || podman network create ecobuilding-internal

# secrets.env is shell-sourced: every line must be KEY=single-token (no spaces,
# no quotes). Fail fast with LINE NUMBERS ONLY — never echo values (a malformed
# SMTP_PASSWORD once aborted mid-deploy and leaked a fragment to the terminal).
BAD=$(grep -vnE '^([A-Za-z_][A-Za-z_0-9]*=[^ "'"'"']*|#.*)$|^$' deploy/secrets.env | cut -d: -f1 | tr '\n' ' ')
[ -z "$BAD" ] || { echo "ERROR: deploy/secrets.env malformed at line(s): $BAD (values must be single tokens, no spaces/quotes)"; exit 1; }

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
# Client URIs replayed from the bootstrap JSON (import never updates a live realm).
./deploy/kc-client.sh || echo "   WARN: kc-client failed (client URIs unchanged)"

# Shared monitoring (promote-proof): prometheus + grafana + podman-exporter.
# CREATE-ONLY from the pipeline: host-network containers (re)created under the
# Actions runner's systemd session come up with a broken netns — the process
# binds inside the container but no listener appears on the host (observed
# 2026-08-11: grafana IPv6-only, prometheus invisible on :9095 → 4h metrics
# outage). Until understood, config changes to this stack are applied from an
# interactive ssh session only.
if podman container exists ecobuilding-monitoring_grafana_1 2>/dev/null; then
  echo "   monitoring stack present — left untouched (recreate via ssh only; runner netns issue)"
else
  ( cd monitoring_stack && podman-compose -p ecobuilding-monitoring -f docker-compose.yml up -d )
fi
# Host-listener sanity: monitoring must actually be reachable from the host.
for p in 13040 13050; do
  curl -fsS -m 3 -o /dev/null "http://127.0.0.1:$p/" 2>/dev/null \
    || echo "   WARN: no host listener on :$p (monitoring degraded — recreate via ssh)"
done

# Retention on the building-view log (#349/#354): twelve months, as the privacy
# policy states. Done here rather than by a timer of its own — deploys are
# frequent, the table is small, and a promise nobody enforces is not a promise.
podman exec ecobuilding-bdnb_bdnb-db_1 psql -U bdnb -d bdnb -qc \
  "DELETE FROM vues.vue_batiment WHERE ts < now() - interval '12 months';" 2>/dev/null \
  || echo "   (view-log retention skipped: bdnb database not up)"

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

# Purge du cache PDF à CHAQUE déploiement (#382). La clé de cache ne porte pas
# la version du code : une fiche mise en cache AVANT un changement de format
# (ex. la refonte de couverture) continuerait d'être servie telle quelle. On
# vide les PDF et leurs sidecars .nom — ils se régénèrent à la première demande,
# avec le code à jour. Cache partagé blue/green (./data/tiles:/tiles).
rm -f data/tiles/pdf/*.pdf data/tiles/pdf/*.nom 2>/dev/null || true
echo "   cache PDF purgé (fiches régénérées à la demande, code à jour)"

# Router: config must match .active; start or reload.
# (podman-compose 1.3 fails to open "-f subdir/file" — run from inside the dir)
cp "caddy_server/Caddyfile.$ACTIVE" caddy_server/Caddyfile
( cd caddy_server && podman-compose -p ecobuilding-edge -f docker-compose.yml up -d ) || true
# Admin moved 2030 -> 13090 (1PESI): a reload posts to the address in the NEW
# config, so try it, then the OLD one for the one-time transition, then restart.
podman exec ecobuilding-edge_caddy_1 caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile 2>/dev/null \
  || podman exec ecobuilding-edge_caddy_1 caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile --address localhost:2030 2>/dev/null \
  || podman restart ecobuilding-edge_caddy_1 >/dev/null

# Upstream (platform) edge is managed separately under the 'debian' user (it
# runs platform_caddy_1 and needs sudo): both ecobuilding.confinia.io and
# staging.ecobuilding.confinia.io are routed there to 127.0.0.1:13000. This
# script runs as the unprivileged 'ecobuilding' user and does NOT touch it.

# Hard health gate on the candidate, via its local entry port. The api can
# take >3s to start (uvicorn + otel init): retry instead of racing it.
if [ "$CANDIDATE" = blue ]; then PORT=13100; else PORT=13200; fi   # 1PESI (#173)
for i in $(seq 1 12); do
  curl -fsS -m 10 "http://127.0.0.1:$PORT/api/v1/healthz" >/dev/null 2>&1 \
    && { echo "   candidate $CANDIDATE healthy on :$PORT"; exit 0; }
  sleep 5
done
echo "ERROR: candidate $CANDIDATE never became healthy on :$PORT"
exit 1
