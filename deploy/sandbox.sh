#!/bin/bash
# EcoBuilding SANDBOX (issue #90) — bring up the isolated sandbox stack and route
# its hostnames through the platform edge. Idempotent; safe to re-run.
#   ssh ecobuilding 'cd ~/projects/ecobuilding && ./deploy/sandbox.sh'
set -eu
cd "$(dirname "$0")/.."
S=sandbox_stack

# Images are built off the VM and pulled from GHCR (#409) — never built here.
# ECOBUILDING_TAG is the deploying commit's sha (set by the workflow); `latest`
# is the break-glass default (needs a prior `podman login ghcr.io`).
export ECOBUILDING_TAG="${ECOBUILDING_TAG:-latest}"
for img in api frontend; do
  podman pull -q "ghcr.io/confinia/ecobuilding-$img:$ECOBUILDING_TAG" >/dev/null \
    || { echo "ERROR: cannot pull ecobuilding-$img:$ECOBUILDING_TAG (login to ghcr.io first for the manual path)"; exit 1; }
done

podman network exists ecobuilding-internal || podman network create ecobuilding-internal   # (#173)
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

# 2. start the isolated stack from the pulled GHCR images (#409). --force-recreate
#    matters: podman-compose 1.3 keeps the RUNNING container unless forced, so the
#    sandbox silently served the previous image (#152 validation caught it).
( cd "$S" && podman-compose -p ecobuilding-sandbox -f docker-compose.yml up -d --force-recreate )

# Purge du cache PDF à chaque déploiement sandbox (#382) : la clé de cache ne
# porte pas la version du code, donc une fiche mise en cache avant un changement
# de format serait servie telle quelle (déjà vu en test #376). On vide les PDF ;
# ils se régénèrent à la première demande, avec le code à jour.
rm -f "$S"/data/tiles/pdf/*.pdf "$S"/data/tiles/pdf/*.nom 2>/dev/null || true
echo "   cache PDF sandbox purgé"

# 3. wait for the sandbox Keycloak realm to answer (through the sandbox caddy)
echo "   waiting for sandbox Keycloak realm..."
for i in $(seq 1 72); do
  curl -fsS -m 5 -H "$HOSTHDR" \
    "http://127.0.0.1:13400/auth/realms/sandbox-ecobuilding/.well-known/openid-configuration" \
    >/dev/null 2>&1 && { echo "   realm up"; break; }
  sleep 5
done

# 4. The platform edge routes sandbox.ecobuilding.confinia.io -> :13400 IN THE
#    confinia/platform REPO (its PR #3) — never hand-edit the edge from here:
#    a platform redeploy reverts it, and a duplicate site block breaks reload.

# 4b. Realm email as code for the SANDBOX realm too (#229): without it,
#     « mot de passe oublié » and the verification mail fail with
#     « Erreur lors de l'envoi du courriel ».
REALM=sandbox-ecobuilding \
  KC_CONTAINER=ecobuilding-sandbox_sandbox-keycloak_1 \
  SECRETS="$PWD/sandbox_stack/secrets.env" \
  ADMIN_USER="${E2E_ADMIN_USER:-ci-admin}" \
  ./deploy/kc-smtp.sh || echo "   WARN: sandbox realm email unchanged"

# 5. health
sleep 3
echo "== sandbox health =="
curl -fsS -m 10 -H "$HOSTHDR" "http://127.0.0.1:13400/api/v1/healthz" && echo || echo "WARN: local api via sandbox caddy"
curl -fsS -m 20 "https://sandbox.api.ecobuilding.confinia.io/v1/healthz" && echo || echo "WARN: public api (edge may still be issuing the cert)"
echo
echo "App:  https://sandbox.ecobuilding.confinia.io   (Créer un compte -> realm sandbox-ecobuilding)"
echo "API:  https://sandbox.api.ecobuilding.confinia.io"
