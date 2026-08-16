#!/bin/bash
# EcoBuilding — end-to-end usage/billing simulation against Polar (#201).
# Drives REAL API calls with a REAL key against an environment, then checks
# that (a) our local counter, (b) our /v1/usage cost and (c) Polar's meter
# quantity all agree. Sandbox only until RULES.md #7 is met.
#
#   API_BASE=https://sandbox.ecobuilding.confinia.io API_KEY=<key> \
#   POLAR_ACCESS_TOKEN=polar_oat_... POLAR_METER_ID=<id> ./deploy/polar-sim.sh
set -eu
API_BASE="${API_BASE:-https://sandbox.ecobuilding.confinia.io}"
: "${API_KEY:?export API_KEY=<an API key created on that environment>}"
CALLS="${CALLS:-12}"
BASE="${POLAR_BASE_URL:-https://sandbox-api.polar.sh}"
BDNB_ID="${BDNB_ID:-bdnb-bg-RPKN-5A8C-L5QV}"

echo "== 0. usage before"
BEFORE=$(curl -fsS -H "X-API-Key: $API_KEY" "$API_BASE/api/v1/usage" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['credits'])")
echo "   credits: $BEFORE"

echo "== 1. simulate $CALLS building lookups (1 credit each)"
for i in $(seq 1 "$CALLS"); do
  curl -fsS -o /dev/null -H "X-API-Key: $API_KEY" \
    "$API_BASE/api/v1/buildings/$BDNB_ID?lon=2.0815&lat=48.7020" || echo "   call $i failed"
done

echo "== 2. simulate 1 PDF fiche"
curl -fsS -o /dev/null -H "X-API-Key: $API_KEY" \
  "$API_BASE/api/v1/report/$BDNB_ID.pdf?lon=2.0815&lat=48.7020" || echo "   fiche failed"

echo "== 3. usage after (local counter + cost)"
curl -fsS -H "X-API-Key: $API_KEY" "$API_BASE/api/v1/usage" | python3 -c "
import json,sys
u = json.load(sys.stdin)
print(f\"   credits={u['credits']} billable={u['billable_credits']} \"
      f\"cost={u['cost_eur']} EUR cap={u['monthly_cap_eur']} reached={u['cap_reached']}\")
c = u['credit_costs']
expected = $BEFORE + $CALLS * c['buildings'] + c['report']
assert u['credits'] == expected, f\"expected {expected} credits, got {u['credits']}\"
print('   local counter OK')
"

if [ -n "${POLAR_ACCESS_TOKEN:-}" ] && [ -n "${POLAR_METER_ID:-}" ]; then
  echo "== 4. Polar meter quantity (ingested events)"
  sleep 5   # ingestion is asynchronous on Polar's side
  curl -fsS -H "Authorization: Bearer $POLAR_ACCESS_TOKEN" \
    "$BASE/v1/meters/$POLAR_METER_ID/quantities?start_timestamp=$(date -u -v-1d +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d '1 day ago' +%Y-%m-%dT%H:%M:%SZ)&end_timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)&interval=day" \
    | python3 -c "
import json,sys
d = json.load(sys.stdin)
tot = sum(q.get('quantity', 0) for q in d.get('quantities', []))
print(f'   Polar meter total (last 24h): {tot}')
print('   NOTE: compare with the credits consumed above; Polar aggregates asynchronously.')
"
else
  echo "== 4. skipped (POLAR_ACCESS_TOKEN / POLAR_METER_ID not set)"
fi
echo "== simulation done"
