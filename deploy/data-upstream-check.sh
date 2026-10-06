#!/bin/bash
# EcoBuilding — relève la dernière version PUBLIÉE des sources (#401).
#
# Le tableau « Données — mises à jour » montrait l'âge du millésime BDNB :
# 247 jours, jaune, bientôt rouge, alors que nous avions la dernière version
# publiée. Ce qui compte est l'ÉCART avec la publication. Chaque jour, ce
# script lit sur data.gouv.fr le dernier millésime BDNB publié et l'écrit
# dans meta.upstream ; meta.data_updates en déduit `retard` (0 ou 1).
#
# Ne charge JAMAIS rien : la restauration BDNB (~200 Go) reste une étape
# lancée par l'opérateur, de nuit (bdnb-import.yml).
#
# Rejoue aussi deploy/data-updates-view.sql (idempotent, léger) : la vue des
# adresses suit ainsi le millésime courant sans attendre un bdnb-stack.
# Lancé par .github/workflows/data-upstream-check.yml.
set -eu
cd "$(dirname "$0")/.."
CTR="${BDNB_DB_CONTAINER:-ecobuilding-bdnb_bdnb-db_1}"
DATASET="https://www.data.gouv.fr/api/1/datasets/base-de-donnees-nationale-des-batiments/"

timeout 60 podman exec -i "$CTR" psql -U bdnb -d bdnb -q -v ON_ERROR_STOP=1 \
  < deploy/data-updates-view.sql

# Le millésime est dans le chemin des fichiers publiés
# (…/bdnb_millesime_2026-02-a/…) : on garde le plus récent.
LIGNE=$(curl -fsS --max-time 30 "$DATASET" | python3 -c '
import json, re, sys
d = json.load(sys.stdin)
vus = {}
for r in d.get("resources", []):
    m = re.search(r"bdnb_millesime_(\d{4}-\d{2}-[a-z])", r.get("url") or "")
    if m:
        v = m.group(1)
        date = (r.get("last_modified") or r.get("created_at") or "")[:10]
        vus[v] = max(vus.get(v, ""), date)
if not vus:
    sys.exit("aucun millésime BDNB dans les ressources du jeu de données")
v = max(vus)
print(v, vus[v] or "")
')
VERSION=${LIGNE%% *}
PUBLIEE=${LIGNE#* }
echo "BDNB : dernier millésime publié $VERSION (le ${PUBLIEE:-?})"

printf '%s\n' \
  "INSERT INTO meta.upstream (source, version, publiee_le, verifie_le)" \
  "VALUES ('Bâtiments (BDNB)', :'v', NULLIF(:'d', '')::date, now())" \
  "ON CONFLICT (source) DO UPDATE SET version = EXCLUDED.version," \
  "  publiee_le = EXCLUDED.publiee_le, verifie_le = EXCLUDED.verifie_le;" |
  timeout 30 podman exec -i "$CTR" psql -U bdnb -d bdnb -q -v ON_ERROR_STOP=1 \
    -v v="$VERSION" -v d="$PUBLIEE"

ETAT=$(timeout 30 podman exec "$CTR" psql -U bdnb -d bdnb -tAc \
  "SELECT coalesce(version, '?') || ' ' || coalesce(retard::text, '?')
   FROM meta.data_updates WHERE source = 'Bâtiments (BDNB)'")
echo "BDNB : nous avons ${ETAT% *}, retard ${ETAT#* }"
# Annotation du run GitHub quand une version plus récente attend.
[ "${ETAT#* }" = "1" ] && echo "::warning::Nouveau millésime BDNB publié : $VERSION (nous avons ${ETAT% *}). Restauration de nuit : bdnb-import.yml."
exit 0
