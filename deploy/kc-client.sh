#!/bin/bash
# EcoBuilding — reconcile the ecobuilding-web client on the LIVE realm from the
# versioned bootstrap (auth_stack/realm-confinia.json). Keycloak's
# --import-realm never updates an existing realm, so client changes in the
# JSON (e.g. the next. -> staging. hostname rename) must be replayed here.
# Idempotent: update overwrites the same fields on every run. Run ON the VM
# (called by deploy.sh; safe standalone).
set -eu
cd "$(dirname "$0")/.."
. deploy/secrets.env

KC=ecobuilding-auth_keycloak_1
KCADM="podman exec -i $KC /opt/keycloak/bin/kcadm.sh"

$KCADM config credentials --server http://localhost:8080/auth --realm master \
  --user "${KC_BOOTSTRAP_ADMIN_USERNAME:-admin}" \
  --password "$KC_BOOTSTRAP_ADMIN_PASSWORD" >/dev/null

ID=$($KCADM get clients -r confinia -q clientId=ecobuilding-web \
  --fields id --format csv --noquotes)
[ -n "$ID" ] || { echo "kc-client: ecobuilding-web not found in realm confinia"; exit 1; }

# The bootstrap JSON is the source of truth: replay its URI surface verbatim.
python3 -c '
import json
r = json.load(open("auth_stack/realm-confinia.json"))
c = next(c for c in r["clients"] if c["clientId"] == "ecobuilding-web")
print(json.dumps({k: c[k] for k in ("rootUrl", "baseUrl", "redirectUris",
                                    "webOrigins", "attributes")}))
' | $KCADM update "clients/$ID" -r confinia -f -

echo "kc-client: ecobuilding-web URIs reconciled from realm-confinia.json"
