#!/bin/bash
# EcoBuilding — BREAK-GLASS workstation deploy (rule 14: normal deploys run
# through GitHub Actions, .github/workflows/staging.yml). Rsync the working
# tree to the VM and run the on-VM stack logic (deploy/stack-up.sh).
# Production stack is never touched: validate on
# https://staging.ecobuilding.confinia.io then promote.
#
# Model: two complete independent stacks from the same docker-compose.yml
#   ecobuilding-blue  (entry 127.0.0.1:13100)
#   ecobuilding-green (entry 127.0.0.1:13200)
# plus the router (caddy_server/, project ecobuilding-edge, 127.0.0.1:13000)
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
# 'debian' user: its Caddyfile forwards ecobuilding.confinia.io and
# staging.ecobuilding.confinia.io -> 127.0.0.1:13000 (our router). Managed once,
# out of band (needs sudo); this deploy does not touch it.

# Images now come from GHCR (#409): this break-glass path deploys the `latest`
# tag (built on the last push to main). The VM must have logged in once:
#   ssh ecobuilding 'podman login ghcr.io'   (a PAT with read:packages)
# To pin a specific build instead, pass its sha: ECOBUILDING_TAG=<sha> ./stack-up.sh
echo "== remote: stacks (deploy/stack-up.sh, GHCR :latest)"
ssh "$HOST" 'cd ~/projects/ecobuilding && ./deploy/stack-up.sh'

echo "== public smoke (staging)"
sleep 2
curl -fsS -m 10 https://staging.ecobuilding.confinia.io/api/v1/healthz && echo || echo "WARN: public staging check failed (main edge may be mid-churn)"
echo
echo "Version $SHA is on the CANDIDATE stack: https://staging.ecobuilding.confinia.io"
echo "Validate it, then promote (Actions 'promote' workflow, or ./deploy/promote.sh break-glass)."
