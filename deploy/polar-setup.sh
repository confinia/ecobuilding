#!/bin/bash
# EcoBuilding — create the pay-as-you-go billing objects in Polar (#201).
# Idempotent-ish: re-running creates duplicates, so it prints existing objects
# first and exits if the meter already exists.
#
# Run from the workstation (sandbox first, per RULES.md #7 — no real money):
#   POLAR_ACCESS_TOKEN=polar_oat_... POLAR_BASE_URL=https://sandbox-api.polar.sh \
#     ./deploy/polar-setup.sh
#
# Creates:
#   1. a METER counting our ingested credit events (sum of metadata.credits)
#   2. a PRODUCT with a metered-unit price: 0,02 €/credit, CAP 99 €/month
#      (Polar's own cap_amount enforces the ceiling server-side)
# Then prints the ids to put in deploy/secrets.env / sandbox_stack/secrets.env.
set -eu
: "${POLAR_ACCESS_TOKEN:?export POLAR_ACCESS_TOKEN=<polar_oat_...>}"
BASE="${POLAR_BASE_URL:-https://sandbox-api.polar.sh}"
EVENT="${POLAR_METER_EVENT:-ecobuilding_credits}"
UNIT_CENTS="${UNIT_CENTS:-2}"        # 0,02 € per credit
CAP_CENTS="${CAP_CENTS:-9900}"       # hard 99 €/month ceiling
AUTH=(-H "Authorization: Bearer $POLAR_ACCESS_TOKEN" -H "Content-Type: application/json")

echo "== existing meters"
curl -fsS "${AUTH[@]}" "$BASE/v1/meters/?limit=20" | python3 -c "
import json,sys
for m in json.load(sys.stdin).get('items', []):
    print(' ', m['id'], m['name'])
"
if curl -fsS "${AUTH[@]}" "$BASE/v1/meters/?limit=50" | grep -q "\"name\":\"EcoBuilding credits\""; then
  echo "meter already exists — nothing to do (delete it in the dashboard to recreate)"
  exit 0
fi

echo "== create meter (sum of metadata.credits on '$EVENT' events)"
METER=$(curl -fsS "${AUTH[@]}" -X POST "$BASE/v1/meters/" -d @- <<JSON | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])"
{
  "name": "EcoBuilding credits",
  "filter": {"conjunction": "and",
             "clauses": [{"property": "name", "operator": "eq", "value": "$EVENT"}]},
  "aggregation": {"func": "sum", "property": "credits"}
}
JSON
)
echo "   meter id: $METER"

echo "== create product (metered unit price, capped)"
PRODUCT=$(curl -fsS "${AUTH[@]}" -X POST "$BASE/v1/products/" -d @- <<JSON | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])"
{
  "name": "EcoBuilding API — paiement à l'usage",
  "description": "500 crédits offerts par mois, puis 0,02 € par crédit, plafonné à 99 € par mois.",
  "recurring_interval": "month",
  "prices": [{"amount_type": "metered_unit", "price_currency": "eur",
              "meter_id": "$METER", "unit_amount": $UNIT_CENTS, "cap_amount": $CAP_CENTS}]
}
JSON
)
echo "   product id: $PRODUCT"

cat <<EOF

Add to the target secrets.env (sandbox_stack/secrets.env for sandbox):
  POLAR_ACCESS_TOKEN=<the token you used>
  POLAR_PRODUCT_ID=$PRODUCT
  POLAR_METER_EVENT=$EVENT
  POLAR_BASE_URL=$BASE
Then run ./deploy/polar-sim.sh to simulate usage end to end.
EOF
