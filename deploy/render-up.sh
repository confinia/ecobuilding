#!/usr/bin/env bash
# Pile de RENDU (partagée, hors bleu/vert) : recréer le conteneur, puis
# VÉRIFIER avant de rendre la main — un rendu cassé touche prod ET sandbox.
# Le premier cliché après démarrage réchauffe Chromium (~80 s mesurés) : on
# attend le gardien de chaleur (#337) plutôt que de tirer à froid nous-mêmes.
set -euo pipefail
cd "$(dirname "$0")/../render_stack"
# Image construite hors VM et tirée de GHCR (#409) — plus de build ici.
export ECOBUILDING_TAG="${ECOBUILDING_TAG:-latest}"
podman pull -q "ghcr.io/confinia/ecobuilding-render:$ECOBUILDING_TAG" >/dev/null \
  || { echo "render: échec du pull ghcr.io/confinia/ecobuilding-render:$ECOBUILDING_TAG"; exit 1; }
podman-compose -p ecobuilding-render up -d --force-recreate
for i in $(seq 1 30); do
  podman exec ecobuilding-render_render_1 sh -c 'curl -sf -m 3 http://127.0.0.1:8040/healthz' >/dev/null 2>&1 && break
  sleep 2
done
podman exec ecobuilding-render_render_1 sh -c 'curl -sf -m 3 http://127.0.0.1:8040/healthz' >/dev/null \
  || { echo "render: healthz KO"; podman logs --since 3m ecobuilding-render_render_1 | tail -20; exit 1; }
# Cliché réel : 200 attendu une fois Chromium chaud (≤ 150 s).
for i in $(seq 1 30); do
  if podman logs --since 5m ecobuilding-render_render_1 2>&1 | grep -q "chauffe: 200"; then
    echo "render: chauffé ($(podman logs --since 5m ecobuilding-render_render_1 2>&1 | grep -o 'chauffe: 200 en [0-9]* ms' | tail -1))"
    exit 0
  fi
  if podman logs --since 5m ecobuilding-render_render_1 2>&1 | grep -q "chauffe: 500\|shot failed"; then
    echo "render: le cliché de chauffe a ÉCHOUÉ"; podman logs --since 5m ecobuilding-render_render_1 | tail -20; exit 1
  fi
  sleep 5
done
echo "render: pas de cliché de chauffe en 150 s"; exit 1
