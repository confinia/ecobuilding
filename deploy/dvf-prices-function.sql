-- EcoBuilding #89 — DVF price block for a building, exposed as a PostgREST RPC.
-- Given a BDNB batiment_groupe_id: recent sales on its cadastral parcelle(s) +
-- commune-level median EUR/m2. Honest about the DVF gaps (Alsace-Moselle 57/67/68
-- and Mayotte 976 are absent from DVF -> available:false, never a wrong number).
-- SECURITY DEFINER so the PostgREST anon role needs only EXECUTE.
CREATE OR REPLACE FUNCTION dvf.prices_for_building(bdnb_id text)
RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER
AS $fn$
WITH parcelles AS (
  SELECT DISTINCT r.parcelle_id,
         r.code_departement_insee AS dep,
         p.code_commune_insee     AS commune
  FROM bdnb_2026_02_a_open_data.rel_batiment_groupe_parcelle r
  LEFT JOIN bdnb_2026_02_a_open_data.parcelle p USING (parcelle_id)
  WHERE r.batiment_groupe_id = bdnb_id
),
ctx AS (SELECT max(dep) AS dep, max(commune) AS commune FROM parcelles),
-- recent sales on the building's own parcelle(s); eur_m2 only for a clean
-- single-local mutation (valeur_fonciere can otherwise bundle several lots).
sales AS (
  SELECT m.date_mutation, m.valeur_fonciere, m.type_local,
         m.surface_reelle_bati, m.nombre_pieces_principales,
         CASE WHEN m.surface_reelle_bati > 5 AND lc.n_local = 1
              AND m.valeur_fonciere / m.surface_reelle_bati BETWEEN 200 AND 200000
              THEN round(m.valeur_fonciere / m.surface_reelle_bati) END AS eur_m2
  FROM dvf.mutation m
  JOIN parcelles pc ON pc.parcelle_id = m.id_parcelle
  LEFT JOIN LATERAL (
    SELECT count(*) FILTER (WHERE m2.type_local IS NOT NULL) AS n_local
    FROM dvf.mutation m2 WHERE m2.id_mutation = m.id_mutation
  ) lc ON true
  WHERE m.type_local IS NOT NULL
    AND m.valeur_fonciere >= 10000   -- drop symbolic transfers (donations, démembrement)
  ORDER BY m.date_mutation DESC
  LIMIT 10
),
-- commune sales restricted to habitable locals, for the median EUR/m2.
cm AS (
  SELECT id_mutation, type_local, valeur_fonciere, surface_reelle_bati
  FROM dvf.mutation
  WHERE code_commune = (SELECT commune FROM ctx)
    AND type_local IN ('Appartement','Maison')
    AND surface_reelle_bati > 5
    AND valeur_fonciere >= 10000
    AND valeur_fonciere / surface_reelle_bati BETWEEN 200 AND 200000
),
cm_single AS (SELECT id_mutation FROM cm GROUP BY id_mutation HAVING count(*) = 1),
commune_stats AS (
  SELECT type_local,
         round(percentile_cont(0.5) WITHIN GROUP (
           ORDER BY valeur_fonciere / surface_reelle_bati)) AS median_eur_m2,
         count(*) AS n
  FROM cm WHERE id_mutation IN (SELECT id_mutation FROM cm_single)
  GROUP BY type_local
)
SELECT jsonb_build_object(
  'available', (SELECT dep FROM ctx) IS NOT NULL
               AND (SELECT dep FROM ctx) NOT IN ('57','67','68','976'),
  'commune_code', (SELECT commune FROM ctx),
  'sales', COALESCE((SELECT jsonb_agg(jsonb_build_object(
      'date', date_mutation, 'valeur_fonciere', valeur_fonciere,
      'type_local', type_local, 'surface_m2', surface_reelle_bati,
      'pieces', nombre_pieces_principales, 'eur_m2', eur_m2)) FROM sales), '[]'::jsonb),
  'commune_eur_m2', COALESCE((SELECT jsonb_object_agg(type_local,
      jsonb_build_object('median', median_eur_m2, 'n', n)) FROM commune_stats), '{}'::jsonb),
  'source', 'DVF (DGFiP) / Etalab — Licence Ouverte 2.0'
);
$fn$;

GRANT EXECUTE ON FUNCTION dvf.prices_for_building(text) TO bdnb_anon;
