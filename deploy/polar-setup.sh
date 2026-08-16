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
EVENT="${POLAR_METER_EVENT:-ecobuilding_fiche}"
# An ORGANIZATION-scoped token already carries its org and Polar REJECTS an
# explicit organization_id with it (422 organization_token). Only a personal
# token needs one, so the field is included only when POLAR_ORG_ID is set AND
# the token is not an organization token (POLAR_ORG_TOKEN=0 to force it in).
ORG_ID="${POLAR_ORG_ID:-}"
ORG_TOKEN="${POLAR_ORG_TOKEN:-1}"
if [ "$ORG_TOKEN" = "1" ] || [ -z "$ORG_ID" ]; then ORG_FIELD=""; else ORG_FIELD=",\"organization_id\": \"$ORG_ID\""; fi
UNIT_CENTS="${UNIT_CENTS:-49}"       # 0,49 € per FICHE — the unit the customer sees
CAP_CENTS="${CAP_CENTS:-9900}"       # hard 99 €/month ceiling
AUTH=(-H "Authorization: Bearer $POLAR_ACCESS_TOKEN" -H "Content-Type: application/json")

echo "== existing meters"
curl -fsS "${AUTH[@]}" "$BASE/v1/meters/?limit=20" | python3 -c "
import json,sys
for m in json.load(sys.stdin).get('items', []):
    print(' ', m['id'], m['name'])
"
if curl -fsS "${AUTH[@]}" "$BASE/v1/meters/?limit=50" | grep -q "\"name\":\"EcoBuilding fiches PDF\""; then
  echo "meter already exists — nothing to do (delete it in the dashboard to recreate)"
  exit 0
fi

echo "== create meter (sum of metadata.credits on '$EVENT' events)"
METER=$(curl -fsS "${AUTH[@]}" -X POST "$BASE/v1/meters/" -d @- <<JSON | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])"
{
  "name": "EcoBuilding fiches PDF",
  "filter": {"conjunction": "and",
             "clauses": [{"property": "name", "operator": "eq", "value": "$EVENT"}]},
  "aggregation": {"func": "sum", "property": "fiches"}$ORG_FIELD
}
JSON
)
echo "   meter id: $METER"

echo "== create product (metered unit price, capped)"
PRODUCT=$(curl -fsS "${AUTH[@]}" -X POST "$BASE/v1/products/" -d @- <<JSON | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])"
{
  "name": "EcoBuilding — fiches PDF à l'usage",
  "description": "10 fiches offertes chaque mois, puis 0,49 € la fiche, plafonné à 99 € par mois. Sans abonnement fixe.",
  "recurring_interval": "month",
  "prices": [{"amount_type": "metered_unit", "price_currency": "eur",
              "meter_id": "$METER", "unit_amount": $UNIT_CENTS, "cap_amount": $CAP_CENTS}]$ORG_FIELD
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
