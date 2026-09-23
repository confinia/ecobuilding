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

-- Every construction year BDNB knows for a groupe, side by side (#432). The
-- Fichiers-Fonciers year alone is parcel-level and can name an extension
-- (Tournefeuille: 2019 for a 1980s house with a 2017 extension permit) or
-- the parcel's first building (Gruissan: 1962 for an îlot whose DPEs say
-- 2001-2005). Local only: api.bdnb.io has no such view. ~0.4 s per groupe
-- through the two lateral aggregates; the API caches it a day.
CREATE OR REPLACE VIEW bdnb.batiment_groupe_annees AS
SELECT g.batiment_groupe_id,
       f.annee_construction              AS annee_ffo,
       d.annee_construction_dpe          AS annee_dpe_representatif,
       d.periode_construction_dpe        AS periode_dpe_representatif,
       dl.annee_dpe_min, dl.annee_dpe_max, dl.nb_dpe_annee,
       n.periode_construction_max        AS periode_rnc,
       sit.travaux_sur_existant, sit.extension, sit.surelevation,
       sit.nouvelle_construction, sit.annee_construction_obsolete,
       sit.annee_premiere_dau, sit.annee_derniere_dau
FROM ${S}.batiment_groupe g
LEFT JOIN ${S}.batiment_groupe_ffo_bat f USING (batiment_groupe_id)
LEFT JOIN ${S}.batiment_groupe_dpe_representatif_logement d USING (batiment_groupe_id)
LEFT JOIN ${S}.batiment_groupe_rnc n USING (batiment_groupe_id)
LEFT JOIN LATERAL (
  SELECT min(l.annee_construction_dpe)   AS annee_dpe_min,
         max(l.annee_construction_dpe)   AS annee_dpe_max,
         count(l.annee_construction_dpe) AS nb_dpe_annee
  FROM ${S}.rel_batiment_groupe_dpe_logement r
  JOIN ${S}.dpe_logement l USING (identifiant_dpe)
  WHERE r.batiment_groupe_id = g.batiment_groupe_id) dl ON true
LEFT JOIN LATERAL (
  SELECT bool_or(ps.travaux_sur_construction_existante)     AS travaux_sur_existant,
         bool_or(ps.indicateur_extension)                   AS extension,
         bool_or(ps.indicateur_surelevation_ou_nivsupp)     AS surelevation,
         bool_or(ps.nouvelle_construction IS NOT NULL)      AS nouvelle_construction,
         bool_or(ps.annee_construction_obsolete)            AS annee_construction_obsolete,
         min(ps.annee_premiere_dau_identifiee)              AS annee_premiere_dau,
         max(ps.annee_derniere_dau_identifiee)              AS annee_derniere_dau
  FROM ${S}.rel_batiment_groupe_parcelle rp
  JOIN ${S}.parcelle_sitadel ps USING (parcelle_id)
  WHERE rp.batiment_groupe_id = g.batiment_groupe_id) sit ON true;

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

echo "== 4. secrets: postgres-exporter credentials (#437)"
# The LIVE password is the one embedded in PGRST_DB_URI (what PostgREST uses
# every day) — NOT BDNB_DB_PASSWORD: bdnb-import.sh regenerates that pair on
# re-runs, but an already-initialized pgdata volume keeps its original
# password, so the two drift apart (seen 2026-09-19: pg_up 0, auth failed).
# Idempotent rewrite so a drift is corrected on every run.
P=$(grep '^PGRST_DB_URI=' deploy/secrets.env | head -1 | sed -E 's|.*://[^:]+:([^@]+)@.*|\1|')
if [ -n "$P" ]; then
  grep -q '^DATA_SOURCE_PASS=' deploy/secrets.env \
    && sed -i "s|^DATA_SOURCE_PASS=.*|DATA_SOURCE_PASS=${P}|" deploy/secrets.env \
    || echo "DATA_SOURCE_PASS=${P}" >> deploy/secrets.env
else
  echo "   WARN: PGRST_DB_URI absent — bdnb-exporter will not authenticate"
fi

echo "== 5. start bdnb-open, bdnb-rest (admin port) and bdnb-exporter"
# The exporter is STATELESS and reads DATA_SOURCE_PASS at creation only: a
# rewritten secrets.env changes nothing for a running container (`up` skips
# recreation when the compose config itself is unchanged — seen 2026-09-20,
# pg_up stayed 0 after the credential fix). Removing it first forces a fresh
# read; bdnb-db and the PostgRESTs are left alone.
podman rm -f ecobuilding-bdnb_bdnb-exporter_1 2>/dev/null || true
# Any change to docker-compose.yml recreates the WHOLE stack, bdnb-db
# included: podman-compose 1.3.0 `up` runs a project-wide `down` as soon as
# one container's config hash differs from the file, and --no-deps does not
# exclude depends_on targets (seen 2026-09-23, #452). The data volume
# survives; Postgres gets stop_grace_period (compose) for a clean shutdown,
# and the mirror is unreachable for ~30 s. So: compose edits at night only.
( cd bdnb_stack && podman-compose -p ecobuilding-bdnb -f docker-compose.yml \
    up -d --no-deps bdnb-open bdnb-rest bdnb-exporter )
sleep 5
# Schema was possibly (re)built while the container ran: reload its cache.
podman kill --signal SIGUSR1 ecobuilding-bdnb_bdnb-open_1 2>/dev/null || true
podman inspect ecobuilding-bdnb_bdnb-db_1 --format \
  '   bdnb-db healthcheck: interval={{.Config.Healthcheck.Interval}} timeout={{.Config.Healthcheck.Timeout}} start={{.Config.Healthcheck.StartPeriod}} stop-timeout={{.Config.StopTimeout}}s'

echo "== 6. prometheus: pick up the bdnb scrape jobs (config is volume-mounted)"
podman kill --signal HUP ecobuilding-monitoring_prometheus_1 2>/dev/null \
  || echo "   (prometheus not running — jobs will load with the monitoring stack)"

echo "== 7. monitoring smoke"
for T in 13022 13023; do
  printf "   admin :%s /ready -> " "$T"
  curl -sS -m 5 -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:${T}/ready" || true
done
printf "   exporter :13031 pg_up -> "
curl -sS -m 5 "http://127.0.0.1:13031/metrics" | grep -m1 '^pg_up' || echo "no pg_up metric"

echo "== 8. smoke: one real address end to end"
BAN=$(podman exec ecobuilding-bdnb_bdnb-db_1 psql -U bdnb -d bdnb -tAc \
  "select cle_interop_adr from ${S}.rel_batiment_groupe_adresse limit 1")
echo "   cle_interop_adr: $BAN"
curl -sS -m 15 "http://127.0.0.1:13021/batiment_groupe_complet_adresse?cle_interop_adr=eq.${BAN}&limit=5" | head -c 400; echo
curl -sS -m 15 "http://127.0.0.1:13021/rel_batiment_groupe_adresse?cle_interop_adr=eq.${BAN}&limit=2" | head -c 300; echo
# The years view (#432) on the Tournefeuille groupe of the report: FFO 2019
# next to a 2017 extension permit.
curl -sS -m 15 "http://127.0.0.1:13021/batiment_groupe_annees?batiment_groupe_id=eq.bdnb-bg-SPW3-4YZ9-Y7RR" | head -c 400; echo
echo "== done. Repoint the API with the BDNB_*_URL vars (docker-compose.yml)."
