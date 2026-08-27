#!/bin/bash
# EcoBuilding — end-to-end SIGN-UP journey (#212), run BY THE PIPELINE
# (rule 19). Proves that a brand-new account is autonomous: it registers,
# gets a token, sees its own allowance, generates a fiche billed to the
# ACCOUNT (not the visitor's IP), and is upsold instead of dead-ended when
# the allowance runs out. Throwaway user, always deleted.
set -eu
cd "$(dirname "$0")/.."
API_BASE="${API_BASE:-https://sandbox.ecobuilding.confinia.io}"
REALM="${REALM:-sandbox-ecobuilding}"
KC="${KC_CONTAINER:-ecobuilding-sandbox_sandbox-keycloak_1}"
. sandbox_stack/secrets.env

USER="e2e-$(date +%s)@confinia.io"
PASS="E2e-$(python3 -c 'import secrets; print(secrets.token_urlsafe(12))')"
KCADM="podman exec -i $KC /opt/keycloak/bin/kcadm.sh"

# E2E_ADMIN_USER exists because a realm's bootstrap admin password can drift
# from secrets.env (it is only applied at first boot); a dedicated CI admin is
# recreatable at any time with `kc.sh bootstrap-admin user`.
$KCADM config credentials --server http://localhost:8080/auth --realm master \
  --user "${E2E_ADMIN_USER:-${KC_BOOTSTRAP_ADMIN_USERNAME:-admin}}" \
  --password "$KC_BOOTSTRAP_ADMIN_PASSWORD" >/dev/null

# The realm JSON is only imported when the realm is CREATED, so the CI client
# is ensured here (idempotent) rather than assumed.
if [ -z "$($KCADM get clients -r "$REALM" -q clientId=ecobuilding-e2e --fields id --format csv --noquotes 2>/dev/null)" ]; then
  $KCADM create clients -r "$REALM" -s clientId=ecobuilding-e2e -s enabled=true \
    -s publicClient=true -s standardFlowEnabled=false \
    -s directAccessGrantsEnabled=true -s serviceAccountsEnabled=false >/dev/null
  echo "== CI client ecobuilding-e2e created (sandbox realm only)"
fi

# The realm's declarative user profile makes `organization` REQUIRED: without
# it Keycloak answers "Account is not fully set up" on any login — the same
# wall a real signup hits if the field is skipped, so the e2e sets it like the
# registration form does.
UID_=$($KCADM create users -r "$REALM" -s "username=$USER" -s "email=$USER" \
        -s enabled=true -s emailVerified=true -s "firstName=CI" -s "lastName=E2E" \
        -s "attributes.organization=E2E" -i)
cleanup() { $KCADM delete "users/$UID_" -r "$REALM" >/dev/null 2>&1 || true; }
trap cleanup EXIT
$KCADM set-password -r "$REALM" --userid "$UID_" --new-password "$PASS" >/dev/null
echo "== account created: $USER"

# Token via the sandbox-only direct-grant client (never exists in prod).
# Requested through the PUBLIC host: the Keycloak image ships no curl, and this
# exercises the real edge -> router -> keycloak path a browser would take.
TOKEN=$(curl -fsS -m 30 -X POST \
  -d "client_id=ecobuilding-e2e" --data-urlencode "username=$USER" \
  --data-urlencode "password=$PASS" -d "grant_type=password" \
  "$API_BASE/auth/realms/$REALM/protocol/openid-connect/token" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
echo "== token obtained"

# 1. A fresh account sees the free-account ladder, not a bill.
curl -fsS -m 20 -H "Authorization: Bearer $TOKEN" "$API_BASE/api/v1/usage" | python3 -c "
import json, sys
u = json.load(sys.stdin)
assert u['plan'] == 'free', u
assert u['cost_eur'] == 0.0, u
# Allowance read from the API: a pricing change must not break this test.
assert u['reports_left'] == u['reports_included'] and u['reports_included'] > 0, u
print(f\"   new account: plan={u['plan']} fiches restantes={u['reports_left']}\")
"

# 2. A fiche generated while signed in is billed to the ACCOUNT.
curl -fsS -m 120 -o /dev/null -H "Authorization: Bearer $TOKEN" \
  "$API_BASE/api/v1/report/bdnb-bg-RPKN-5A8C-L5QV.pdf?lon=2.0815&lat=48.7020"
curl -fsS -m 20 -H "Authorization: Bearer $TOKEN" "$API_BASE/api/v1/usage" | python3 -c "
import json, sys
u = json.load(sys.stdin)
assert u['reports_used'] == 1, u
assert u['reports_left'] == u['reports_included'] - 1, u
print(f\"   after 1 fiche: used={u['reports_used']} restantes={u['reports_left']}\")
"

# 3. Épuiser le droit doit refuser SANS impasse — et le droit est QUOTIDIEN,
#    en documents DISTINCTS (#290). Générer dix fiches prendrait des minutes :
#    la liste du jour est remplie directement (le même magasin que lit l'API),
#    et la VRAIE réponse est vérifiée ensuite.
API_BASE="$API_BASE" TOKEN="$TOKEN" DAILY_FILE="$PWD/sandbox_stack/data/leads/mobile_daily.json" python3 <<'PY'
import base64, hashlib, json, os, urllib.error, urllib.request
from datetime import date

base, token = os.environ["API_BASE"], os.environ["TOKEN"]
payload = token.split(".")[1]
claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
bucket = "kc:" + hashlib.sha256(claims["sub"].encode()).hexdigest()[:14]

req0 = urllib.request.Request(f"{base}/api/v1/usage", headers={"Authorization": f"Bearer {token}"})
u0 = json.load(urllib.request.urlopen(req0))
assert u0.get("period") == "day", f"le droit doit être quotidien : {u0}"
included = u0["reports_included"]

# La fiche déjà obtenue à l'étape 2 doit rester GRATUITE en réouverture.
deja = "bdnb-bg-RPKN-5A8C-L5QV"
req = urllib.request.Request(
    f"{base}/api/v1/report/{deja}.pdf?lon=2.0815&lat=48.7020",
    headers={"Authorization": f"Bearer {token}"})
urllib.request.urlopen(req, timeout=120)
u1 = json.load(urllib.request.urlopen(req0))
assert u1["reports_used"] == u0["reports_used"], \
    f"rouvrir le même document a décompté : {u0} -> {u1}"
print("   même document rouvert -> non décompté")

# Remplir la liste du JOUR avec des documents distincts, jusqu'au droit.
path = os.environ["DAILY_FILE"]
store = json.load(open(path)) if os.path.exists(path) else {}
jour = date.today().isoformat()
vus = store.get(bucket) or {"day": jour, "ids": []}
if vus.get("day") != jour:
    vus = {"day": jour, "ids": []}
while len(vus["ids"]) < included:
    vus["ids"].append(f"bdnb-bg-E2E-{len(vus['ids'])}")
store[bucket] = vus
json.dump(store, open(path, "w"))

# Un document DISTINCT de plus doit être refusé, avec la période et l'issue.
req = urllib.request.Request(
    f"{base}/api/v1/report/bdnb-bg-STREAM.pdf?lon=3.8767&lat=43.6108",
    headers={"Authorization": f"Bearer {token}"})
try:
    urllib.request.urlopen(req, timeout=120)
    raise SystemExit("FAIL: the allowance was not enforced")
except urllib.error.HTTPError as e:
    assert e.code == 429, e.code
    detail = json.loads(e.read()).get("detail", "")
    assert "par jour" in detail, detail            # la bonne période
    assert "demain" in detail, detail              # et quand ça repart
    assert "contact@confinia.io" in detail, detail # un humain joignable
    print("   droit du jour épuisé -> 429 « par jour », « demain », contact")

# Et un document DÉJÀ vu aujourd'hui passe encore : même épuisé, le même
# document reste consultable — le refuser passerait pour une panne.
req = urllib.request.Request(
    f"{base}/api/v1/report/{deja}.pdf?lon=2.0815&lat=48.7020",
    headers={"Authorization": f"Bearer {token}"})
urllib.request.urlopen(req, timeout=120)
print("   document déjà vu, droit épuisé -> toujours servi")
PY
echo "== signup journey OK (droit quotidien, réouverture gratuite, refus net)"
