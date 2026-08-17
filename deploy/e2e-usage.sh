#!/bin/bash
# EcoBuilding — pay-as-you-go metering e2e (#201), run BY THE PIPELINE
# (rule 19: app-running tests belong to CI, never to a workstation).
# Runs on the VM: provisions a throwaway API key on the sandbox stack, drives
# real calls through the public sandbox host, asserts the credit counter, then
# removes the key. Also drives the Polar leg when creds are configured.
set -eu
cd "$(dirname "$0")/.."
API_BASE="${API_BASE:-https://sandbox.ecobuilding.confinia.io}"
KEYS_FILE="${KEYS_FILE:-$PWD/sandbox_stack/data/leads/keys.jsonl}"
CALLS="${CALLS:-6}"

KEY="eb_e2e_$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')"
mkdir -p "$(dirname "$KEYS_FILE")"
cleanup() {
  # Always drop the throwaway key, even on failure (no test key survives a run).
  [ -f "$KEYS_FILE" ] && grep -v "$KEY" "$KEYS_FILE" > "$KEYS_FILE.tmp" 2>/dev/null \
    && mv "$KEYS_FILE.tmp" "$KEYS_FILE" || true
}
trap cleanup EXIT
printf '{"key":"%s","note":"e2e usage (CI)","created":"%s"}\n' \
  "$KEY" "$(date -u +%FT%TZ)" >> "$KEYS_FILE"

# _load_keys() re-reads the file per request: no restart needed.
USAGE0=$(curl -fsS -m 20 -H "X-API-Key: $KEY" "$API_BASE/api/v1/usage")
BEFORE=$(printf '%s' "$USAGE0" | python3 -c "import json,sys; print(json.load(sys.stdin)['credits'])")
# Unit prices come from the API itself: a business repricing must not require
# editing this test (the 5 -> 20 credit fiche change broke the hardcoded one).
C_BUILDING=$(printf '%s' "$USAGE0" | python3 -c "import json,sys; print(json.load(sys.stdin)['credit_costs']['buildings'])")
C_REPORT=$(printf '%s' "$USAGE0" | python3 -c "import json,sys; print(json.load(sys.stdin)['credit_costs']['report'])")

for _ in $(seq 1 "$CALLS"); do
  curl -fsS -m 30 -o /dev/null -H "X-API-Key: $KEY" \
    "$API_BASE/api/v1/buildings/bdnb-bg-RPKN-5A8C-L5QV?lon=2.0815&lat=48.7020"
done
curl -fsS -m 90 -o /dev/null -H "X-API-Key: $KEY" \
  "$API_BASE/api/v1/report/bdnb-bg-RPKN-5A8C-L5QV.pdf?lon=2.0815&lat=48.7020"

curl -fsS -m 20 -H "X-API-Key: $KEY" "$API_BASE/api/v1/usage" | python3 -c "
import json, sys
u = json.load(sys.stdin)
expected = $BEFORE + $CALLS * $C_BUILDING + $C_REPORT
assert u['credits'] == expected, f\"credits: expected {expected}, got {u['credits']}\"
# v4 : plus de plafond metered ; un compte GRATUIT ne doit jamais rien devoir,
# et la grille des paliers arrive avec la réponse.
assert u['plan'] == 'free' and u['cost_eur'] == 0.0, u
assert 'tiers' in u and u['tiers']['l']['eur'] == max(t['eur'] for t in u['tiers'].values()), u
print(f\"usage e2e OK: {u['credits']} credits, plan {u['plan']}, 0 EUR\")
"

# Cost model must be identical on the public simulator (page <-> server), and
# must be derived from the API's own fields so a repricing never breaks CI.
curl -fsS -m 20 "$API_BASE/api/v1/pricing?credits=$((100 * C_REPORT))" | python3 -c "
import json, sys
p = json.load(sys.stdin)
# v4 : le simulateur recommande le plus petit palier couvrant le volume,
# entierement derive des champs de l'API (un repricing ne casse pas la CI).
tier = p['recommended_tier']
q = p['tiers'][tier]['fiches_month']
assert q is None or p['fiches'] <= q, p
assert p['cost_eur'] == (0.0 if p['fiches'] <= p['free_tiers']['free_account_reports_month']
                         else float(p['tiers'][tier]['eur'])), p
print(f\"pricing simulator OK: {p['fiches']} fiches -> palier {tier} = {p['cost_eur']} EUR\")
"
