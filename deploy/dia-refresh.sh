#!/bin/bash
# EcoBuilding #246 — rafraîchissement MENSUEL des DIA de Montpellier 3M.
# À lancer sur la VM ; écrit /leads/dia.json dans chaque stack qui doit
# servir le bloc (les stacks blue/green partagent data/leads du repo).
#   ssh ecobuilding 'cd ~/projects/ecobuilding && ./deploy/dia-refresh.sh'
set -eu
cd "$(dirname "$0")/.."
for c in $(podman ps --format '{{.Names}}' | grep -E '_api_1$|_sandbox-api_1$'); do
  echo "== $c"
  podman exec "$c" python -m app.dia_refresh || echo "   WARN: refresh raté sur $c"
done
