-- EcoBuilding #429 — observed price range for a dwelling, from DVF comparables.
--
-- NOT a valuation model: the sales of the same type (house / flat), of a
-- similar surface (±30 %), over the last three years, in the smallest radius
-- (300 m, 600 m, 1.2 km, 2.5 km) that holds at least 8 of them. Returns their
-- €/m² quartiles, the matching price range for the given surface, and the
-- comparables themselves, so every figure traces back to a DGFiP mutation.
-- Reads dvf.vente_logement (deploy/dvf-around.sql). Applied by
-- deploy/bdnb-local-api.sh (bdnb-stack workflow).
CREATE OR REPLACE FUNCTION dvf.estimation(lon float8, lat float8, type_local text, surface float8)
RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER
AS $fn$
DECLARE
  pt geography := ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography;
  depuis date := (current_date - interval '3 years')::date;
  rayon int;
  nb int := 0;
BEGIN
  IF type_local NOT IN ('Maison', 'Appartement') OR surface IS NULL OR surface <= 5 THEN
    RETURN NULL;
  END IF;
  FOREACH rayon IN ARRAY ARRAY[300, 600, 1200, 2500] LOOP
    SELECT count(*) INTO nb FROM dvf.vente_logement v
    WHERE ST_DWithin(v.geog, pt, rayon) AND v.type_local = estimation.type_local
      AND v.date_mutation >= depuis
      AND v.surface_reelle_bati BETWEEN surface * 0.7 AND surface * 1.3;
    EXIT WHEN nb >= 8;
  END LOOP;
  IF nb < 5 THEN
    RETURN NULL;
  END IF;
  RETURN (
    WITH comp AS (
      SELECT v.date_mutation, v.surface_reelle_bati, v.nombre_pieces_principales,
             v.valeur_fonciere, v.eur_m2, round(ST_Distance(v.geog, pt))::int AS distance_m
      FROM dvf.vente_logement v
      WHERE ST_DWithin(v.geog, pt, rayon) AND v.type_local = estimation.type_local
        AND v.date_mutation >= depuis
        AND v.surface_reelle_bati BETWEEN surface * 0.7 AND surface * 1.3
    ),
    q AS (
      SELECT round(percentile_cont(0.25) WITHIN GROUP (ORDER BY eur_m2))::int AS p25,
             round(percentile_cont(0.5)  WITHIN GROUP (ORDER BY eur_m2))::int AS p50,
             round(percentile_cont(0.75) WITHIN GROUP (ORDER BY eur_m2))::int AS p75,
             count(*) AS n, min(date_mutation) AS du, max(date_mutation) AS au
      FROM comp
    )
    SELECT jsonb_build_object(
      'type_local', type_local, 'surface_m2', round(surface::numeric, 1),
      'radius_m', rayon, 'n', q.n, 'since', depuis, 'from', q.du, 'to', q.au,
      'eur_m2', jsonb_build_object('p25', q.p25, 'p50', q.p50, 'p75', q.p75),
      'price', jsonb_build_object('low', round(q.p25 * surface / 1000) * 1000,
                                  'mid', round(q.p50 * surface / 1000) * 1000,
                                  'high', round(q.p75 * surface / 1000) * 1000),
      'comparables', COALESCE((SELECT jsonb_agg(c) FROM (
          SELECT jsonb_build_object('date', date_mutation, 'surface_m2', surface_reelle_bati,
                   'pieces', nombre_pieces_principales, 'valeur_fonciere', valeur_fonciere,
                   'eur_m2', eur_m2, 'distance_m', distance_m) AS c
          FROM comp ORDER BY abs(surface_reelle_bati - surface), date_mutation DESC LIMIT 10) x),
        '[]'::jsonb),
      'source', 'DVF (DGFiP) / Etalab — Licence Ouverte 2.0'
    ) FROM q
  );
END
$fn$;

GRANT EXECUTE ON FUNCTION dvf.estimation(float8, float8, text, float8) TO bdnb_anon;
