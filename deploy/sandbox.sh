#!/bin/bash
# EcoBuilding SANDBOX (issue #90) — bring up the isolated sandbox stack and route
# its hostnames through the platform edge. Idempotent; safe to re-run.
#   ssh ecobuilding 'cd ~/projects/ecobuilding && ./deploy/sandbox.sh'
set -eu
cd "$(dirname "$0")/.."
S=sandbox_stack
HOSTHDR='Host: sandbox.ecobuilding.confinia.io'

# 1. isolated sandbox secrets. Polar values start empty — fill them once the
#    Polar sandbox organization + product exist (issue #90 / TEST_POLAR.md),
#    then re-run this script to pick them up.
if [ ! -f "$S/secrets.env" ]; then
  P=$(openssl rand -hex 24)
  cat > "$S/secrets.env" <<EOF
POSTGRES_PASSWORD=$P
KC_DB_PASSWORD=$P
KC_BOOTSTRAP_ADMIN_PASSWORD=$(openssl rand -base64 18)
# --- Polar SANDBOX (fill after creating the sandbox organization) ---
POLAR_ACCESS_TOKEN=
POLAR_ORG_ID=
POLAR_PRODUCT_ID=
POLAR_WEBHOOK_SECRET=
EOF
  echo "   generated $S/secrets.env (Polar values empty — fill to test the pro plan)"
fi
mkdir -p "$S/data/leads"

# 2. build + start the isolated stack. --force-recreate matters: podman-compose
#    1.3 rebuilds the image but keeps the RUNNING container unless forced, so
#    the sandbox silently served stale code (#152 validation caught it).
( cd "$S" && podman-compose -p ecobuilding-sandbox -f docker-compose.yml up -d --build --force-recreate )

# 3. wait for the sandbox Keycloak realm to answer (through the sandbox caddy)
echo "   waiting for sandbox Keycloak realm..."
for i in $(seq 1 72); do
  curl -fsS -m 5 -H "$HOSTHDR" \
    "http://127.0.0.1:8030/auth/realms/sandbox-ecobuilding/.well-known/openid-configuration" \
    >/dev/null 2>&1 && { echo "   realm up"; break; }
  sleep 5
done

# 4. The platform edge routes sandbox.ecobuilding.confinia.io -> :8030 IN THE
#    confinia/platform REPO (its PR #3) — never hand-edit the edge from here:
#    a platform redeploy reverts it, and a duplicate site block breaks reload.

# 5. health
sleep 3
echo "== sandbox health =="
curl -fsS -m 10 -H "$HOSTHDR" "http://127.0.0.1:8030/api/v1/healthz" && echo || echo "WARN: local api via sandbox caddy"
curl -fsS -m 20 "https://sandbox.api.ecobuilding.confinia.io/v1/healthz" && echo || echo "WARN: public api (edge may still be issuing the cert)"
echo
echo "App:  https://sandbox.ecobuilding.confinia.io   (Créer un compte -> realm sandbox-ecobuilding)"
echo "API:  https://sandbox.api.ecobuilding.confinia.io"
