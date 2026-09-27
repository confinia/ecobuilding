#!/bin/bash
# EcoBuilding — thème de connexion du royaume, comme du code (#475).
#
# `--import-realm` ne met JAMAIS à jour un royaume existant : poser loginTheme
# dans le JSON ne suffit que pour une base neuve. On rejoue donc la valeur du
# JSON sur le royaume vivant, comme kc-client.sh le fait pour les URI (#136).
# Idempotent. Lancé sur la VM par stack-up.sh et sandbox.sh.
#
# Production par défaut ; le bac à sable l'appelle avec son royaume :
#   REALM=sandbox-ecobuilding KC_CONTAINER=ecobuilding-sandbox_sandbox-keycloak_1 \
#   SECRETS=sandbox_stack/secrets.env ADMIN_USER=ci-admin \
#   REALM_JSON=sandbox_stack/realm-sandbox-ecobuilding.json ./deploy/kc-theme.sh
set -eu
cd "$(dirname "$0")/.."
REALM="${REALM:-confinia}"
SECRETS="${SECRETS:-deploy/secrets.env}"
REALM_JSON="${REALM_JSON:-auth_stack/realm-confinia.json}"
. "$SECRETS"

THEME=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("loginTheme") or "")' "$REALM_JSON")
if [ -z "$THEME" ]; then
  echo "kc-theme: pas de loginTheme dans $REALM_JSON — royaume $REALM inchangé"
  exit 0
fi

KC="${KC_CONTAINER:-ecobuilding-auth_keycloak_1}"
KCADM="podman exec -i $KC /opt/keycloak/bin/kcadm.sh"

# Le thème doit EXISTER dans le conteneur avant qu'on le désigne : un royaume
# pointé vers un thème absent affiche une page d'erreur à la place de la
# connexion — plus personne n'entre.
if ! podman exec "$KC" test -f "/opt/keycloak/themes/$THEME/login/theme.properties"; then
  echo "kc-theme: thème $THEME absent de $KC — royaume $REALM laissé sur son thème actuel"
  exit 1
fi

$KCADM config credentials --server http://localhost:8080/auth \
  --realm master --user "${ADMIN_USER:-${KC_BOOTSTRAP_ADMIN_USERNAME:-admin}}" \
  --password "$KC_BOOTSTRAP_ADMIN_PASSWORD" >/dev/null
$KCADM update "realms/$REALM" -s "loginTheme=$THEME"
echo "kc-theme: royaume $REALM -> thème de connexion $THEME"
