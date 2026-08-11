#!/bin/bash
# EcoBuilding — load DVF geolocalise (Etalab, open data, Licence Ouverte 2.0)
# into the same PostGIS as BDNB, as schema "dvf" (issue #89). Home/property
# transaction prices, joined to buildings via the cadastral parcelle
# (rel_batiment_groupe_parcelle -> parcelle_id = DVF id_parcelle).
# Run ON the VM:  nohup ./deploy/dvf-import.sh > ~/bdnb/dvf.log 2>&1 &
set -eu
DB=ecobuilding-bdnb_bdnb-db_1
PSQL="podman exec -i $DB psql -U bdnb -d bdnb -v ON_ERROR_STOP=1"
STATUS=~/bdnb/dvf.status
say(){ echo "== $*"; echo "$*" > "$STATUS"; }
YEARS="2020 2021 2022 2023 2024 2025"
BASE="https://files.data.gouv.fr/geo-dvf/latest/csv"

say "1. schema + raw table"
$PSQL <<'SQL'
CREATE SCHEMA IF NOT EXISTS dvf;
DROP TABLE IF EXISTS dvf.mutation_raw;
CREATE TABLE dvf.mutation_raw (
  id_mutation text, date_mutation text, numero_disposition text, nature_mutation text,
  valeur_fonciere text, adresse_numero text, adresse_suffixe text, adresse_nom_voie text,
  adresse_code_voie text, code_postal text, code_commune text, nom_commune text,
  code_departement text, ancien_code_commune text, ancien_nom_commune text, id_parcelle text,
  ancien_id_parcelle text, numero_volume text, lot1_numero text, lot1_surface_carrez text,
  lot2_numero text, lot2_surface_carrez text, lot3_numero text, lot3_surface_carrez text,
  lot4_numero text, lot4_surface_carrez text, lot5_numero text, lot5_surface_carrez text,
  nombre_lots text, code_type_local text, type_local text, surface_reelle_bati text,
  nombre_pieces_principales text, code_nature_culture text, nature_culture text,
  code_nature_culture_speciale text, nature_culture_speciale text, surface_terrain text,
  longitude text, latitude text);
SQL

for y in $YEARS; do
  url="$BASE/$y/full.csv.gz"
  curl -sfIL -m 30 "$url" >/dev/null 2>&1 || { echo "   $y: not available, skipping"; continue; }
  say "2.$y streaming $url"
  curl -sL -m 1800 "$url" | zcat \
    | $PSQL -c "COPY dvf.mutation_raw FROM STDIN WITH (FORMAT csv, HEADER true)"
done

say "3. typed table + indexes"
$PSQL <<'SQL'
DROP TABLE IF EXISTS dvf.mutation;
CREATE TABLE dvf.mutation AS
SELECT id_mutation,
       date_mutation::date                              AS date_mutation,
       nature_mutation,
       NULLIF(valeur_fonciere,'')::numeric              AS valeur_fonciere,
       code_commune, nom_commune, code_departement, id_parcelle,
       type_local,
       NULLIF(surface_reelle_bati,'')::numeric          AS surface_reelle_bati,
       NULLIF(nombre_pieces_principales,'')::int        AS nombre_pieces_principales,
       NULLIF(surface_terrain,'')::numeric              AS surface_terrain,
       NULLIF(longitude,'')::float8                     AS longitude,
       NULLIF(latitude,'')::float8                      AS latitude
FROM dvf.mutation_raw
WHERE nature_mutation = 'Vente' AND NULLIF(valeur_fonciere,'') IS NOT NULL;
CREATE INDEX ON dvf.mutation (id_parcelle);
CREATE INDEX ON dvf.mutation (code_commune, type_local);
DROP TABLE dvf.mutation_raw;
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='bdnb_anon') THEN
    CREATE ROLE bdnb_anon NOLOGIN;
  END IF;
END $$;
GRANT USAGE ON SCHEMA dvf TO bdnb_anon;
GRANT SELECT ON ALL TABLES IN SCHEMA dvf TO bdnb_anon;
SQL

say "4. validate: row count + a real building->parcelle->DVF join"
$PSQL -c "SELECT count(*) AS dvf_rows FROM dvf.mutation;"
$PSQL -c "SELECT count(*) AS joinable
  FROM dvf.mutation m
  JOIN bdnb_2026_02_a_open_data.rel_batiment_groupe_parcelle r USING (id_parcelle);"
say "DONE"
