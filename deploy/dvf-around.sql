-- EcoBuilding #426 — DVF sales AROUND a building, the area median and the
-- yearly trend, as a PostgREST RPC next to dvf.prices_for_building (#89).
--
-- dvf.mutation has longitude/latitude but no spatial index: a 250 m search in
-- Toulouse meant tens of thousands of random reads on spinning disks. Hence a
-- derived table of CLEAN housing sales only — one house or flat per mutation
-- (the same rule as the commune median of prices_for_building), plausible
-- €/m² — with a point, stored in geohash order so that neighbours sit on the
-- same pages, a GiST index for the radius and a covering index for the yearly
-- commune medians.
--
-- Built ONCE per DVF import (IF NOT EXISTS: a re-run costs nothing); after a
-- new DVF import, DROP TABLE dvf.vente_logement and run bdnb-stack at night.
-- Applied by deploy/bdnb-local-api.sh (bdnb-stack workflow), never by hand.

CREATE TABLE IF NOT EXISTS dvf.vente_logement AS
WITH m AS (
  SELECT date_mutation, code_commune, type_local, valeur_fonciere,
         surface_reelle_bati, nombre_pieces_principales, longitude, latitude,
         count(*) OVER (PARTITION BY id_mutation) AS n_in_mutation
  FROM dvf.mutation
  WHERE type_local IN ('Appartement', 'Maison')
    AND surface_reelle_bati > 5
    AND valeur_fonciere >= 10000
    AND valeur_fonciere / surface_reelle_bati BETWEEN 200 AND 200000
)
SELECT date_mutation, code_commune, type_local,
       valeur_fonciere, surface_reelle_bati, nombre_pieces_principales,
       round(valeur_fonciere / surface_reelle_bati)::int AS eur_m2,
       ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography AS geog
FROM m
WHERE n_in_mutation = 1 AND longitude IS NOT NULL AND latitude IS NOT NULL
ORDER BY ST_GeoHash(ST_SetSRID(ST_MakePoint(longitude, latitude), 4326), 7);

CREATE INDEX IF NOT EXISTS vente_logement_geog_idx
  ON dvf.vente_logement USING gist (geog);
CREATE INDEX IF NOT EXISTS vente_logement_commune_idx
  ON dvf.vente_logement (code_commune, type_local, date_mutation) INCLUDE (eur_m2);
-- Index-only scans need a fresh visibility map.
VACUUM ANALYZE dvf.vente_logement;
GRANT SELECT ON dvf.vente_logement TO bdnb_anon;


-- Sales within the smallest radius (250, 500, then 1000 m) that holds at
-- least 10 of them — a quiet village street would otherwise show nothing —
-- most recent first (50 at most), the area median per type on those sales,
-- and yearly medians for the commune and for the area. A year with fewer
-- than 10 sales is LEFT OUT of a trend rather than drawn from 3 points.
CREATE OR REPLACE FUNCTION dvf.prices_around(lon float8, lat float8, commune text DEFAULT NULL)
RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER
AS $fn$
DECLARE
  pt geography := ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography;
  rayon int;
  nb int;
BEGIN
  FOREACH rayon IN ARRAY ARRAY[250, 500, 1000] LOOP
    SELECT count(*) INTO nb FROM dvf.vente_logement v WHERE ST_DWithin(v.geog, pt, rayon);
    EXIT WHEN nb >= 10;
  END LOOP;
  RETURN (
    WITH zone AS (
      SELECT v.*, round(ST_Distance(v.geog, pt))::int AS distance_m
      FROM dvf.vente_logement v WHERE ST_DWithin(v.geog, pt, rayon)
    ),
    zone_stats AS (
      SELECT type_local, round(percentile_cont(0.5) WITHIN GROUP (ORDER BY eur_m2))::int AS median,
             count(*) AS n
      FROM zone GROUP BY type_local
    ),
    zone_annees AS (
      SELECT type_local, extract(year FROM date_mutation)::int AS annee,
             round(percentile_cont(0.5) WITHIN GROUP (ORDER BY eur_m2))::int AS median, count(*) AS n
      FROM zone GROUP BY 1, 2 HAVING count(*) >= 10
    ),
    commune_annees AS (
      SELECT type_local, extract(year FROM date_mutation)::int AS annee,
             round(percentile_cont(0.5) WITHIN GROUP (ORDER BY eur_m2))::int AS median, count(*) AS n
      FROM dvf.vente_logement
      WHERE commune IS NOT NULL AND code_commune = commune
      GROUP BY 1, 2 HAVING count(*) >= 10
    )
    SELECT jsonb_build_object(
      'radius_m', rayon,
      'n', (SELECT count(*) FROM zone),
      'sales', COALESCE((SELECT jsonb_agg(s) FROM (
          SELECT jsonb_build_object('date', date_mutation, 'type_local', type_local,
                   'surface_m2', surface_reelle_bati, 'pieces', nombre_pieces_principales,
                   'valeur_fonciere', valeur_fonciere, 'eur_m2', eur_m2,
                   'distance_m', distance_m) AS s
          FROM zone ORDER BY date_mutation DESC, distance_m LIMIT 50) x), '[]'::jsonb),
      'area_eur_m2', COALESCE((SELECT jsonb_object_agg(type_local,
          jsonb_build_object('median', median, 'n', n)) FROM zone_stats), '{}'::jsonb),
      'trend', jsonb_build_object(
        'area', COALESCE((SELECT jsonb_object_agg(type_local, serie) FROM (
            SELECT type_local, jsonb_agg(jsonb_build_object('year', annee, 'median', median, 'n', n)
                                         ORDER BY annee) AS serie
            FROM zone_annees GROUP BY type_local) t), '{}'::jsonb),
        'commune', COALESCE((SELECT jsonb_object_agg(type_local, serie) FROM (
            SELECT type_local, jsonb_agg(jsonb_build_object('year', annee, 'median', median, 'n', n)
                                         ORDER BY annee) AS serie
            FROM commune_annees GROUP BY type_local) t), '{}'::jsonb)),
      'source', 'DVF (DGFiP) / Etalab — Licence Ouverte 2.0'
    )
  );
END
$fn$;

GRANT EXECUTE ON FUNCTION dvf.prices_around(float8, float8, text) TO bdnb_anon;
