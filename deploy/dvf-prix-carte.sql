-- EcoBuilding #319 — DVF prices on the map.
--
-- Two functions read dvf.vente_logement (#426) through its GiST index:
--
-- dvf.prix_points(bbox), for one z14 tile (~2.4 km): every sold ADDRESS
--   point (DVF geolocates each sale on its parcel) with its sale count,
--   median €/m², last sale year and €/m², and its majority type.
--
-- dvf.prix_cellules(bbox), for one z12 tile (~10 km): a fixed grid of
--   ~300 m CELLS (0.004° × 0.003°) with the median €/m² of the cell's
--   majority type and its trend between 2021-2022 and 2024-2025, only when
--   both periods hold at least 10 sales of that type. Each cell is computed
--   from all its sales and returned only by the tile containing its centre,
--   so no cell is ever split or duplicated.
--
-- Applied by deploy/bdnb-local-api.sh (bdnb-stack workflow).
CREATE OR REPLACE FUNCTION dvf.prix_points(minlon float8, minlat float8, maxlon float8, maxlat float8)
RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER
AS $fn$
WITH v AS (
  SELECT round(ST_X(geog::geometry)::numeric, 5) AS lon, round(ST_Y(geog::geometry)::numeric, 5) AS lat,
         type_local, eur_m2, date_mutation
  FROM dvf.vente_logement
  WHERE geog && ST_MakeEnvelope(minlon, minlat, maxlon, maxlat, 4326)::geography
),
p AS (
  SELECT lon, lat, count(*) AS n,
         round(percentile_cont(0.5) WITHIN GROUP (ORDER BY eur_m2))::int AS med,
         to_char(max(date_mutation), 'YYYY') AS an,
         (array_agg(eur_m2 ORDER BY date_mutation DESC))[1] AS dernier,
         mode() WITHIN GROUP (ORDER BY type_local) AS type_local
  FROM v GROUP BY lon, lat
)
SELECT COALESCE(jsonb_agg(jsonb_build_array(lon, lat, n, med, an, dernier,
                CASE WHEN type_local = 'Maison' THEN 'M' ELSE 'A' END)), '[]'::jsonb)
FROM p;
$fn$;

-- The cells are computed ONCE for all of France into a stored table: live,
-- a z12 tile took 2.2 s in Toulouse and 8.6 s in Paris (a large disk read
-- per tile). Built with the same memory guard as dvf.vente_logement (#517,
-- #519); IF NOT EXISTS, so a re-run costs nothing. After a new DVF import,
-- drop it together with dvf.vente_logement and run bdnb-stack at night.
SET max_parallel_workers_per_gather = 0;
SET work_mem = '16MB';
SET maintenance_work_mem = '64MB';

CREATE MATERIALIZED VIEW IF NOT EXISTS dvf.prix_cellule AS
WITH v AS (
  SELECT floor(ST_X(geog::geometry) / 0.004) AS cx, floor(ST_Y(geog::geometry) / 0.003) AS cy,
         type_local, eur_m2, date_mutation
  FROM dvf.vente_logement
),
type_cellule AS (
  SELECT cx, cy, mode() WITHIN GROUP (ORDER BY type_local) AS type_local
  FROM v GROUP BY cx, cy
),
c AS (
  SELECT v.cx, v.cy, t.type_local, count(*) AS n,
         round(percentile_cont(0.5) WITHIN GROUP (ORDER BY eur_m2))::int AS med,
         percentile_cont(0.5) WITHIN GROUP (ORDER BY eur_m2) FILTER (WHERE date_mutation < '2023-01-01') AS avant,
         percentile_cont(0.5) WITHIN GROUP (ORDER BY eur_m2) FILTER (WHERE date_mutation >= '2024-01-01') AS apres,
         count(*) FILTER (WHERE date_mutation < '2023-01-01') AS n_avant,
         count(*) FILTER (WHERE date_mutation >= '2024-01-01') AS n_apres
  FROM v JOIN type_cellule t ON t.cx = v.cx AND t.cy = v.cy AND t.type_local = v.type_local
  GROUP BY v.cx, v.cy, t.type_local
  HAVING count(*) >= 5
)
SELECT ST_SetSRID(ST_MakePoint((cx + 0.5) * 0.004, (cy + 0.5) * 0.003), 4326) AS centre,
       n, med, type_local,
       CASE WHEN n_avant >= 10 AND n_apres >= 10 AND avant > 0
            THEN round(((apres - avant) * 100 / avant)::numeric)::int END AS tendance
FROM c;
CREATE INDEX IF NOT EXISTS prix_cellule_centre_idx ON dvf.prix_cellule USING gist (centre);
GRANT SELECT ON dvf.prix_cellule TO bdnb_anon;

-- One z12 tile of cells: those whose centre lies in the tile.
CREATE OR REPLACE FUNCTION dvf.prix_cellules(minlon float8, minlat float8, maxlon float8, maxlat float8)
RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER
AS $fn$
SELECT COALESCE(jsonb_agg(jsonb_build_array(
         round(ST_X(centre)::numeric, 5), round(ST_Y(centre)::numeric, 5), n, med, tendance,
         CASE WHEN type_local = 'Maison' THEN 'M' ELSE 'A' END)), '[]'::jsonb)
FROM dvf.prix_cellule
WHERE centre && ST_MakeEnvelope(minlon, minlat, maxlon, maxlat, 4326)
  AND ST_X(centre) < maxlon AND ST_Y(centre) < maxlat;
$fn$;

GRANT EXECUTE ON FUNCTION dvf.prix_points(float8, float8, float8, float8) TO bdnb_anon;
GRANT EXECUTE ON FUNCTION dvf.prix_cellules(float8, float8, float8, float8) TO bdnb_anon;
