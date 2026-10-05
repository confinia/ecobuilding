#!/bin/bash
# EcoBuilding — connexion par clé d'accès (passkey), comme du code (#372).
#
# Depuis Keycloak 26.4, la clé d'accès se propose DANS le formulaire
# identifiant/mot de passe standard : un réglage de royaume, aucun changement
# du parcours de connexion « browser », que partagent les utilisateurs de
# l'app. Le mot de passe reste ; la clé d'accès est une option de plus.
#
# Deux réglages, idempotents :
#   1. webAuthnPolicyPasswordlessPasskeysEnabled=true (politique WebAuthn sans
#      mot de passe) : l'option apparaît sur la page de connexion ;
#   2. l'action « enregistrer une clé d'accès » ACTIVÉE mais PAS par défaut :
#      personne n'y est forcé, chacun l'ajoute depuis sa console de compte.
#
# Lancé sur la VM par stack-up.sh et sandbox.sh. Production par défaut ; le bac
# à sable l'appelle avec son royaume :
#   REALM=sandbox-ecobuilding KC_CONTAINER=ecobuilding-sandbox_sandbox-keycloak_1 \
#   SECRETS=sandbox_stack/secrets.env ADMIN_USER=ci-admin ./deploy/kc-passkeys.sh
set -eu
cd "$(dirname "$0")/.."
REALM="${REALM:-confinia}"
SECRETS="${SECRETS:-deploy/secrets.env}"
. "$SECRETS"
KC="${KC_CONTAINER:-ecobuilding-auth_keycloak_1}"
KCADM="podman exec -i $KC /opt/keycloak/bin/kcadm.sh"

$KCADM config credentials --server http://localhost:8080/auth \
  --realm master --user "${ADMIN_USER:-${KC_BOOTSTRAP_ADMIN_USERNAME:-admin}}" \
  --password "$KC_BOOTSTRAP_ADMIN_PASSWORD" >/dev/null

$KCADM update "realms/$REALM" -s webAuthnPolicyPasswordlessPasskeysEnabled=true
# Relu : un Keycloak qui ne connaît pas ce champ laisserait la page sans clé
# d'accès sans que rien ne le dise.
VU=$($KCADM get "realms/$REALM" --fields webAuthnPolicyPasswordlessPasskeysEnabled \
       --format csv --noquotes)
if [ "$VU" != "true" ]; then
  echo "kc-passkeys: le royaume $REALM n'a pas gardé le réglage (Keycloak antérieur à 26.4 ?)"
  exit 1
fi

$KCADM update authentication/required-actions/webauthn-register-passwordless \
  -r "$REALM" -s enabled=true -s defaultAction=false
echo "kc-passkeys: royaume $REALM -> clé d'accès proposée à la connexion, enregistrement facultatif"
