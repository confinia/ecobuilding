#!/bin/bash
# EcoBuilding — Creem TEST MODE bootstrap (bascule MoR décidée le 2026-08-17 ;
# règle opérateur : fournisseur de paiement = creem.io, Test Mode uniquement).
#
#   CREEM_API_KEY=creem_test_… ./deploy/creem-setup.sh
#
# Idempotent. Adopte le produit « ecobuilding » créé À LA MAIN dans le
# dashboard (demande opérateur : « use current product as creem product:
# ecobuilding ») comme palier dont le prix correspond, puis crée UNIQUEMENT
# les paliers manquants de la grille v4 (PRICING.md) :
# les paliers manquants (prix et quotas lus dans api/app/pricing.json, le SPOT) :
#   Pro S  9 €/mois  (900 c)  · 10 fiches/jour (gratuit au lancement)
#   Pro M 29 €/mois (2900 c)  · 50 fiches/jour
#   Pro L 99 €/mois (9900 c)  · illimité fair-use
# Imprime le bloc CREEM_* à coller dans sandbox_stack/secrets.env.
set -eu
[ -n "${CREEM_API_KEY:-}" ] || { echo "ERREUR: CREEM_API_KEY absent (clé creem_test_…)"; exit 1; }
case "$CREEM_API_KEY" in
  creem_test_*) BASE="${CREEM_API_BASE:-https://test-api.creem.io/v1}" ;;
  *) echo "ERREUR: clé de PRODUCTION refusée — la règle est Test Mode uniquement"; exit 1 ;;
esac
AUTH=(-H "x-api-key: $CREEM_API_KEY" -H "Content-Type: application/json")

# Prix et quotas depuis le SPOT (api/app/pricing.json), source unique (#397).
SPOT="$(cd "$(dirname "$0")/.." && pwd)/api/app/pricing.json"
spot(){ python3 -c "import json;print(json.load(open('$SPOT'))['tiers']['$1']['$2'])"; }
cents(){ echo $(( $(spot "$1" price_month) * 100 )); }

echo "== produits existants ($BASE)"
EXISTING=$(curl -fsS "${AUTH[@]}" "$BASE/products/search?page_size=50")
echo "$EXISTING" | python3 -c "
import json, sys
d = json.load(sys.stdin)
for p in (d.get('items') or d if isinstance(d, list) else d.get('items') or []):
    print(f\"   {p['id']}  {p.get('price')}c/{p.get('billing_period','')}  {p['name']}\")" || true

pick_or_create() {   # pick_or_create <tier> <cents> <fiches-label> <nom>
  local tier=$1 cents=$2 desc=$3 name=$4
  # 1. un produit existant au BON PRIX récurrent mensuel est adopté tel quel
  #    (dont le produit « ecobuilding » créé à la main) ;
  local id
  id=$(echo "$EXISTING" | python3 -c "
import json, sys
d = json.load(sys.stdin)
items = d.get('items') or (d if isinstance(d, list) else [])
for p in items:
    if int(p.get('price') or 0) == $cents and p.get('billing_type') == 'recurring':
        print(p['id']); break")
  if [ -n "$id" ]; then
    echo "   $tier: adopté ($id)" >&2
  else
    id=$(curl -fsS "${AUTH[@]}" -X POST "$BASE/products" -d @- <<JSON | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])"
{
  "name": "$name",
  "description": "$desc",
  "price": $cents,
  "currency": "EUR",
  "billing_type": "recurring",
  "billing_period": "every-month",
  "tax_mode": "inclusive",
  "tax_category": "saas"
}
JSON
)
    echo "   $tier: créé ($id)" >&2
  fi
  echo "$id"
}

S_ID=$(pick_or_create s "$(cents pro_s)" "$(spot pro_s quota) fiches PDF par jour. Sans engagement." "EcoBuilding Pro S")
M_ID=$(pick_or_create m "$(cents pro_m)" "$(spot pro_m quota) fiches PDF par jour. Sans engagement." "EcoBuilding Pro M")
L_ID=$(pick_or_create l "$(cents pro_l)" "Fiches PDF illimitées (usage raisonnable). Sans engagement." "EcoBuilding Pro L")

cat <<EOF

À coller dans sandbox_stack/secrets.env (puis ./deploy/sandbox.sh) :
  CREEM_API_KEY=$CREEM_API_KEY
  CREEM_PRODUCTS_JSON={"s":"$S_ID","m":"$M_ID","l":"$L_ID"}
  CREEM_WEBHOOK_SECRET=<Dashboard -> Developers -> Webhook, cible :
    https://sandbox.api.ecobuilding.confinia.io/v1/pro/webhook>
Le webhook est une optimisation : sans lui, la réconciliation par e-mail
active le compte en <60 s après paiement (même philosophie que #228).
EOF
