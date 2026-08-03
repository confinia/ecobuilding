#!/bin/bash
# EcoBuilding — rollback: point production back at the other (previous) stack.
# Same operation as promote, without the health gate excuse — but we still
# refuse to route prod to a dead stack.
set -eu

HOST=ecobuilding

ssh "$HOST" 'bash -s' <<'EOF'
set -eu
cd ~/projects/ecobuilding

ACTIVE=$(cat deploy/.active 2>/dev/null || echo blue)
if [ "$ACTIVE" = blue ]; then TARGET=green; PORT=8022; else TARGET=blue; PORT=8021; fi

curl -fsS -m 5 "http://127.0.0.1:$PORT/api/v1/healthz" >/dev/null \
  || { echo "Target stack ($TARGET, :$PORT) is not healthy — cannot roll back to it"; exit 1; }

cp "caddy_server/Caddyfile.$TARGET" caddy_server/Caddyfile
podman exec ecobuilding-edge_caddy_1 caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile 2>/dev/null || podman restart ecobuilding-edge_caddy_1 >/dev/null
echo "$TARGET" > deploy/.active
echo "Production rolled back to the $TARGET stack."
EOF

sleep 2
curl -fsS -m 10 https://ecobuilding.confinia.io/api/v1/healthz && echo