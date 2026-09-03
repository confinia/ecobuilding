#!/bin/bash
# EcoBuilding #372 — passwordless Grafana via Keycloak.
#
# Reconciles, on the LIVE realm, everything Grafana needs to delegate its login
# to Keycloak, and enables the PASSKEY (WebAuthn passwordless) option WITHOUT
# touching how end users sign in.
#
# Two things, both idempotent (kcadm `update`/`create` re-runnable):
#   1. an OIDC client `grafana` (confidential, standard flow) with the redirect
#      URI Grafana's generic_oauth expects;
#   2. a realm required-action `webauthn-register-passwordless` set ENABLED but
#      NOT default — end users keep their password flow untouched; the operator
#      opts in by registering a passkey once in the account console.
#
# The confinia realm is SHARED with the SaaS end users: this script must never
# change the realm's browser authentication flow. It only ADDS an optional
# capability + one client. Run ON the VM (safe standalone; sandbox via env).
set -eu
cd "$(dirname "$0")/.."
REALM="${REALM:-confinia}"
SECRETS="${SECRETS:-deploy/secrets.env}"
. "$SECRETS"

if [ -z "${GRAFANA_OAUTH_SECRET:-}" ]; then
  echo "kc-grafana: GRAFANA_OAUTH_SECRET not in $SECRETS — skipping (realm $REALM unchanged)"
  exit 0
fi

KC="${KC_CONTAINER:-ecobuilding-auth_keycloak_1}"
KCADM="podman exec -i $KC /opt/keycloak/bin/kcadm.sh"
BASE="${GRAFANA_BASE_URL:-https://grafana.ecobuilding.confinia.io}"

$KCADM config credentials --server http://localhost:8080/auth \
  --realm master --user "${ADMIN_USER:-${KC_BOOTSTRAP_ADMIN_USERNAME:-admin}}" \
  --password "$KC_BOOTSTRAP_ADMIN_PASSWORD" >/dev/null

# --- 1. the grafana OIDC client ------------------------------------------------
# generic_oauth sends the browser back to <root>/login/generic_oauth.
REDIRECT="$BASE/login/generic_oauth"
ID=$($KCADM get clients -r "$REALM" -q clientId=grafana \
       --fields id --format csv --noquotes 2>/dev/null || true)
CLIENT_JSON=$(cat <<JSON
{
  "clientId": "grafana",
  "name": "Grafana (observabilité interne)",
  "protocol": "openid-connect",
  "publicClient": false,
  "standardFlowEnabled": true,
  "directAccessGrantsEnabled": false,
  "secret": "$GRAFANA_OAUTH_SECRET",
  "redirectUris": ["$REDIRECT"],
  "webOrigins": ["$BASE"],
  "attributes": {"post.logout.redirect.uris": "$BASE/*"}
}
JSON
)
if [ -n "$ID" ]; then
  echo "$CLIENT_JSON" | $KCADM update "clients/$ID" -r "$REALM" -f -
  echo "kc-grafana: client grafana reconciled"
else
  echo "$CLIENT_JSON" | $KCADM create clients -r "$REALM" -f -
  echo "kc-grafana: client grafana created"
fi

# A realm role Grafana maps to Admin (GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_PATH).
$KCADM create roles -r "$REALM" -s name=grafana-admin \
  -s 'description=Grafana Admin via OAuth (#372)' 2>/dev/null \
  && echo "kc-grafana: role grafana-admin created" \
  || echo "kc-grafana: role grafana-admin already present"

# Put the user's realm roles WHERE Grafana reads them (#372). Keycloak's stock
# 'roles' scope only writes realm_access.roles to the ACCESS token; Grafana's
# generic_oauth reads roles from the ID token + userinfo, so without this the
# login is rejected with "IdP did not return a role attribute". This
# client-scoped mapper emits realm_access.roles into the ID token and userinfo
# too (grafana client only — the shared scope is left untouched).
GID=$($KCADM get clients -r "$REALM" -q clientId=grafana \
        --fields id --format csv --noquotes)
HAS=$($KCADM get "clients/$GID/protocol-mappers/models" -r "$REALM" \
        --fields name --format csv --noquotes 2>/dev/null | grep -c grafana-realm-roles || true)
if [ "${HAS:-0}" = "0" ]; then
  $KCADM create "clients/$GID/protocol-mappers/models" -r "$REALM" -f - <<'JSON'
{
  "name": "grafana-realm-roles",
  "protocol": "openid-connect",
  "protocolMapper": "oidc-usermodel-realm-role-mapper",
  "config": {
    "claim.name": "realm_access.roles",
    "jsonType.label": "String",
    "multivalued": "true",
    "id.token.claim": "true",
    "access.token.claim": "true",
    "userinfo.token.claim": "true",
    "usermodel.realmRoleMapping.rolePrefix": ""
  }
}
JSON
  echo "kc-grafana: realm-roles mapper added to the grafana client"
else
  echo "kc-grafana: realm-roles mapper already present"
fi

# --- 2. passkey as an OPTIONAL required action (non-breaking) -------------------
# ENABLED so the account console offers "add passkey"; defaultAction=false so no
# end user is forced into it. The operator registers a passkey once; afterwards
# the login page's "Sign in with a passkey" button is a one-tap login.
RA_ID=webauthn-register-passwordless
CURRENT=$($KCADM get "authentication/required-actions/$RA_ID" -r "$REALM" \
            --fields enabled --format csv --noquotes 2>/dev/null || echo "")
if [ -n "$CURRENT" ]; then
  $KCADM update "authentication/required-actions/$RA_ID" -r "$REALM" \
    -s enabled=true -s defaultAction=false
  echo "kc-grafana: passkey required-action enabled (optional, end users untouched)"
else
  echo "kc-grafana: WARN webauthn-register-passwordless action not found on this realm"
fi

echo "kc-grafana: done. Register your passkey at $KC_ACCOUNT_URL, then log into"
echo "            $BASE and pick 'Sign in with a passkey'."
