#!/bin/bash
# EcoBuilding — promote ON THE VM: point production at the validated CANDIDATE
# stack. Pure router flip (one config file + graceful reload); the previous
# stack keeps running untouched -> rollback.sh is instant. Called by the
# GitHub Actions 'promote' workflow (#112); promote.sh is the workstation
# break-glass wrapper.
set -eu
cd "$(dirname "$0")/.."

ACTIVE=$(cat deploy/.active 2>/dev/null || echo blue)
if [ "$ACTIVE" = blue ]; then CANDIDATE=green; PORT=8022; else CANDIDATE=blue; PORT=8021; fi

# Candidate must be healthy before taking production traffic.
curl -fsS -m 5 "http://127.0.0.1:$PORT/api/v1/healthz" >/dev/null \
  || { echo "Candidate stack ($CANDIDATE, :$PORT) unhealthy — refusing to promote"; exit 1; }

cp "caddy_server/Caddyfile.$CANDIDATE" caddy_server/Caddyfile
podman exec ecobuilding-edge_caddy_1 caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile 2>/dev/null || podman restart ecobuilding-edge_caddy_1 >/dev/null
echo "$CANDIDATE" > deploy/.active
echo "Production now served by the $CANDIDATE stack (previous: $ACTIVE, still running for rollback)."
