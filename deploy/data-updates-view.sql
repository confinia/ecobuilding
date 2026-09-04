-- Vue de fraîcheur des données (#403) : source de vérité du tableau de bord
-- « Données — mises à jour ». Détenue par le propriétaire de la base (donc peut
-- lire dvf/bdnb/vues), exposée en LECTURE au rôle read-only grafana_ro sans lui
-- accorder l'accès direct aux tables. À rejouer après un nouveau millésime BDNB
-- ou un changement de couverture DVF.
CREATE SCHEMA IF NOT EXISTS meta;

CREATE OR REPLACE VIEW meta.data_updates AS
SELECT ord, source, version, lignes, as_of, (now()::date - as_of) AS age_jours
FROM (
  -- BDNB : le millésime est encodé dans le NOM du schéma (bdnb_AAAA_MM_...).
  SELECT 1 AS ord, 'Bâtiments (BDNB)' AS source,
         replace(substring(n FROM 'bdnb_([0-9]{4}_[0-9]{2})'), '_', '-') AS version,
         NULL::bigint AS lignes,
         to_date(replace(substring(n FROM 'bdnb_([0-9]{4}_[0-9]{2})'), '_', ''), 'YYYYMM') AS as_of
  FROM (SELECT max(nspname) AS n FROM pg_namespace
        WHERE nspname ~ '^bdnb_[0-9]{4}_[0-9]{2}_.*open_data$') b
  UNION ALL
  -- DVF : compter 18 M lignes scannerait la table ; on prend l'estimation du
  -- planificateur (instantanée). Couverture = années chargées par dvf-import.sh.
  -- La DATE d'import n'est pas encore suivie (#401), donc as_of NULL.
  SELECT 2, 'Prix de vente (DVF)', '2020-2025',
         (SELECT reltuples::bigint FROM pg_class
          WHERE relname = 'mutation' AND relnamespace = 'dvf'::regnamespace),
         NULL::date
  UNION ALL
  SELECT 3, 'Consultations (télémétrie)', NULL,
         (SELECT count(*)::bigint FROM vues.vue_batiment),
         (SELECT max(ts)::date FROM vues.vue_batiment)
) t
ORDER BY ord;

GRANT USAGE ON SCHEMA meta TO grafana_ro;
GRANT SELECT ON meta.data_updates TO grafana_ro;
