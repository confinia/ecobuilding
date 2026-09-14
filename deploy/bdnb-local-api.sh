#!/bin/bash
# EcoBuilding — serve address lookups from the LOCAL BDNB mirror (issue #28).
#
# The open-data pgdump restored by deploy/bdnb-import.sh ships the per-topic
# tables but NOT the wide batiment_groupe_complet view that api.bdnb.io
# serves (locally the table of that name is empty). This script builds, in a
# stable schema "bdnb", views that reproduce the api.bdnb.io shapes the API
# reads, then starts the bdnb-open PostgREST on top (bdnb_stack). The app is
# repointed by the BDNB_*_URL env vars in the compose files — no code change.
#
# Known gap vs api.bdnb.io: the batenr_* solar-thermal columns are not in the
# open dump, so buildings[0].solar.thermal_* is null on local serving.
#
# Run ON the VM, idempotent (CREATE OR REPLACE). Re-run after each millésime
# re-import (the source schema name is discovered, views are rebuilt on it):
#   ~/projects/ecobuilding/deploy/bdnb-local-api.sh
set -eu
cd "$(dirname "$0")/.."

echo "== 1. discover the BDNB source schema"
S=$(podman exec ecobuilding-bdnb_bdnb-db_1 psql -U bdnb -d bdnb -tAc \
  "select table_schema from information_schema.tables
   where table_name='batiment_groupe' and table_type='BASE TABLE' limit 1")
[ -n "$S" ] || { echo "no batiment_groupe table found — run bdnb-import.sh first"; exit 1; }
echo "   source schema: $S"

echo "== 2. build the api.bdnb.io-compatible views in schema bdnb"
podman exec -i ecobuilding-bdnb_bdnb-db_1 psql -U bdnb -d bdnb -v ON_ERROR_STOP=1 <<SQL
CREATE SCHEMA IF NOT EXISTS bdnb;

-- Wide per-building record, one row per batiment_groupe_id. Geometries stay
-- in Lambert-93 as JSON, exactly like api.bdnb.io: the API reprojects itself.
CREATE OR REPLACE VIEW bdnb.batiment_groupe_complet AS
SELECT g.batiment_groupe_id,
       g.code_commune_insee,
       g.code_departement_insee,
       a.libelle_adr_principale_ban,
       r.alea_argile,
       f.annee_construction,
       f.mat_mur_txt,
       f.mat_toit_txt,
       f.nb_log,
       f.nb_niveau,
       t.hauteur_mean,
       d.classe_bilan_dpe,
       d.date_reception_dpe,
       d.conso_5_usages_ep_m2,
       d.emission_ges_5_usages_m2,
       d.type_generateur_climatisation,
       d.type_generateur_climatisation_anciennete,
       s.nb_classe_bilan_dpe_a,
       s.nb_classe_bilan_dpe_b,
       s.nb_classe_bilan_dpe_c,
       s.nb_classe_bilan_dpe_d,
       s.nb_classe_bilan_dpe_e,
       s.nb_classe_bilan_dpe_f,
       s.nb_classe_bilan_dpe_g,
       e.conso_res AS conso_res_dle_elec_2020,
       z.conso_res AS conso_res_dle_gaz_2020,
       ST_AsGeoJSON(g.geom_groupe)::json AS geom_groupe
FROM ${S}.batiment_groupe g
LEFT JOIN ${S}.batiment_groupe_adresse a USING (batiment_groupe_id)
LEFT JOIN ${S}.batiment_groupe_risques r USING (batiment_groupe_id)
LEFT JOIN ${S}.batiment_groupe_ffo_bat f USING (batiment_groupe_id)
LEFT JOIN ${S}.batiment_groupe_bdtopo_bat t USING (batiment_groupe_id)
LEFT JOIN ${S}.batiment_groupe_dpe_representatif_logement d USING (batiment_groupe_id)
LEFT JOIN ${S}.batiment_groupe_dpe_statistique_logement s USING (batiment_groupe_id)
LEFT JOIN ${S}.batiment_groupe_dle_elec_multimillesime e
       ON e.batiment_groupe_id = g.batiment_groupe_id AND e.millesime = '2020'
LEFT JOIN ${S}.batiment_groupe_dle_gaz_multimillesime z
       ON z.batiment_groupe_id = g.batiment_groupe_id AND z.millesime = '2020';

-- api.bdnb.io's ".../batiment_groupe_complet/adresse": the same record keyed
-- by BAN address. PostgREST has no nested paths, so it is a flat view name;
-- BDNB_URL points here.
CREATE OR REPLACE VIEW bdnb.batiment_groupe_complet_adresse AS
SELECT rel.cle_interop_adr, b.*
FROM ${S}.rel_batiment_groupe_adresse rel
JOIN bdnb.batiment_groupe_complet b USING (batiment_groupe_id);

-- Group -> member addresses, with the label and point the click-address
-- logic reads (upstream serves them inline; locally they live in "adresse").
CREATE OR REPLACE VIEW bdnb.rel_batiment_groupe_adresse AS
SELECT rel.batiment_groupe_id,
       rel.cle_interop_adr,
       rel.code_departement_insee,
       rel.origine,
       rel.fiabilite,
       ad.libelle_adresse,
       ST_AsGeoJSON(ad.geom_adresse)::json AS geom_adresse
FROM ${S}.rel_batiment_groupe_adresse rel
LEFT JOIN ${S}.adresse ad USING (cle_interop_adr);

-- Representative-dwelling DPE: same table name and columns upstream and
-- locally, passed through as-is.
CREATE OR REPLACE VIEW bdnb.batiment_groupe_dpe_representatif_logement AS
SELECT * FROM ${S}.batiment_groupe_dpe_representatif_logement;

GRANT USAGE ON SCHEMA bdnb TO bdnb_anon;
GRANT SELECT ON ALL TABLES IN SCHEMA bdnb TO bdnb_anon;
ALTER DEFAULT PRIVILEGES IN SCHEMA bdnb GRANT SELECT ON TABLES TO bdnb_anon;

-- The complet view joins 10 relations — above the default join/from_collapse
-- limit of 8, so the planner stopped reordering and hash-joined the full
-- 13M-row tables (15 s+, timeout) instead of driving from the address index
-- (0.4 s). DATABASE level on purpose: PostgREST logs in as the authenticator
-- and only SET ROLEs to bdnb_anon, so role-level GUCs would never fire.
ALTER DATABASE bdnb SET join_collapse_limit = 16;
ALTER DATABASE bdnb SET from_collapse_limit = 16;
SQL

echo "== 3. statistics (autovacuum is off on this mirror)"
for T in batiment_groupe batiment_groupe_adresse batiment_groupe_risques \
         batiment_groupe_ffo_bat batiment_groupe_bdtopo_bat \
         batiment_groupe_dpe_representatif_logement \
         batiment_groupe_dpe_statistique_logement \
         batiment_groupe_dle_elec_multimillesime \
         batiment_groupe_dle_gaz_multimillesime \
         rel_batiment_groupe_adresse adresse; do
  podman exec ecobuilding-bdnb_bdnb-db_1 psql -U bdnb -d bdnb -qc "ANALYZE ${S}.${T}"
done

echo "== 4. start bdnb-open (PostgREST on schema bdnb)"
# --no-deps: never let a config drift recreate the 219 GB bdnb-db under us.
( cd bdnb_stack && podman-compose -p ecobuilding-bdnb -f docker-compose.yml up -d --no-deps bdnb-open )
sleep 5
# Schema was possibly (re)built while the container ran: reload its cache.
podman kill --signal SIGUSR1 ecobuilding-bdnb_bdnb-open_1 2>/dev/null || true

echo "== 5. smoke: one real address end to end"
BAN=$(podman exec ecobuilding-bdnb_bdnb-db_1 psql -U bdnb -d bdnb -tAc \
  "select cle_interop_adr from ${S}.rel_batiment_groupe_adresse limit 1")
echo "   cle_interop_adr: $BAN"
curl -sS -m 15 "http://127.0.0.1:13021/batiment_groupe_complet_adresse?cle_interop_adr=eq.${BAN}&limit=5" | head -c 400; echo
curl -sS -m 15 "http://127.0.0.1:13021/rel_batiment_groupe_adresse?cle_interop_adr=eq.${BAN}&limit=2" | head -c 300; echo
echo "== done. Repoint the API with the BDNB_*_URL vars (docker-compose.yml)."
