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
assert u['monthly_cap_eur'] == 99.0, u
assert u['cost_eur'] <= u['monthly_cap_eur']
print(f\"usage e2e OK: {u['credits']} credits, {u['cost_eur']} EUR (cap {u['monthly_cap_eur']})\")
"

# Cost model must be identical on the public simulator (page <-> server), and
# must be derived from the API's own fields so a repricing never breaks CI.
curl -fsS -m 20 "$API_BASE/api/v1/pricing?credits=$((100 * C_REPORT))" | python3 -c "
import json, sys
p = json.load(sys.stdin)
fiches = 100
extra = max(0, fiches - p['included_fiches'])
expected = round(min(extra * p['price_per_fiche_eur'], p['monthly_cap_eur']), 2)
assert p['cost_eur'] == expected, (p['cost_eur'], expected)
assert p['cost_eur'] <= p['monthly_cap_eur']
print(f\"pricing simulator OK: {fiches} fiches -> {p['cost_eur']} EUR \"
      f\"({extra} facturees x {p['price_per_fiche_eur']}, cap {p['monthly_cap_eur']})\")
"
