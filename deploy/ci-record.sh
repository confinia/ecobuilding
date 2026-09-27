#!/bin/bash
# EcoBuilding — consigner une exécution de CI dans meta.ci_run (#469, règle 25).
#
# Appelé par chaque workflow avec `if: always()`, SUCCÈS COMPRIS : c'est ce qui
# rend le silence lisible. Un tableau qui ne montre que les échecs ne distingue
# pas « tout va bien » de « le workflow ne tourne plus ».
#
#   ./deploy/ci-record.sh "<workflow>" "<ref>" "<run id>" "<conclusion>" "<url>"
#
# Ne fait JAMAIS échouer l'appelant : un journal d'observation qui casse la
# pipeline qu'il observe coûte plus qu'il ne rapporte.
set -u
cd "$(dirname "$0")/.."
WF="${1:-unknown}"; REF="${2:-}"; RUN="${3:-}"; CONC="${4:-unknown}"; URL="${5:-}"
CTR="${BDNB_DB_CONTAINER:-ecobuilding-bdnb_bdnb-db_1}"

# Les valeurs passent par des VARIABLES psql, jamais par concaténation : une
# branche nommée avec une apostrophe casserait l'insertion, et une branche est
# du texte fourni de l'extérieur.
inserer() {
    printf '%s\n' \
        "INSERT INTO meta.ci_run (workflow, ref, run_id, conclusion, url)" \
        "VALUES (:'wf', :'ref', :'run', :'conc', :'url');" |
        timeout 30 podman exec -i \
            -e PGOPTIONS=--statement-timeout=10s \
            "$CTR" psql -U bdnb -d bdnb -q -v ON_ERROR_STOP=1 \
            -v wf="$WF" -v ref="$REF" -v run="$RUN" -v conc="$CONC" -v url="$URL"
}

# Le schéma se pose TOUT SEUL au premier échec d'insertion, puis on réessaie :
# personne ne doit se souvenir de jouer un .sql à la main sur la VM (règle 20),
# et le fichier est idempotent (CREATE ... IF NOT EXISTS).
if ! inserer 2>/dev/null; then
    echo "ci-record: journal absent ou illisible, application du schéma"
    timeout 60 podman exec -i "$CTR" psql -U bdnb -d bdnb -q -v ON_ERROR_STOP=1 \
        < deploy/ci-run-table.sql || echo "ci-record: schéma non appliqué"
    inserer || echo "ci-record: écriture impossible (workflow=$WF conclusion=$CONC) — on continue"
fi
exit 0
