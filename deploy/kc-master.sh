#!/bin/bash
# EcoBuilding — durcissement du royaume d'ADMINISTRATION Keycloak (master).
#
# Le royaume master ne sert qu'à administrer ; sa connexion était ouverte à
# l'essai de mots de passe sans limite. Verrouillage TEMPORAIRE après 10 échecs
# (attente croissante, plafonnée à 15 min, jamais définitive : un verrou
# permanent serait un déni de service offert à qui connaît le nom du compte).
#
# Comme du code, rejoué à chaque déploiement : un réglage fait à la main dans
# la console se perd au prochain import, et son absence ne se voit pas.
# Idempotent. Lancé sur la VM par stack-up.sh et sandbox.sh.
set -eu
cd "$(dirname "$0")/.."
SECRETS="${SECRETS:-deploy/secrets.env}"
. "$SECRETS"
KC="${KC_CONTAINER:-ecobuilding-auth_keycloak_1}"
KCADM="podman exec -i $KC /opt/keycloak/bin/kcadm.sh"

$KCADM config credentials --server http://localhost:8080/auth \
  --realm master --user "${ADMIN_USER:-${KC_BOOTSTRAP_ADMIN_USERNAME:-admin}}" \
  --password "$KC_BOOTSTRAP_ADMIN_PASSWORD" >/dev/null
$KCADM update realms/master \
  -s bruteForceProtected=true -s failureFactor=10 \
  -s waitIncrementSeconds=60 -s maxFailureWaitSeconds=900 \
  -s maxDeltaTimeSeconds=43200 -s permanentLockout=false
echo "kc-master: verrouillage temporaire actif sur le royaume master ($KC)"
