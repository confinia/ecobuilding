-- Vue de fraîcheur des données (#403) : source de vérité du tableau de bord
-- « Données — mises à jour ». Détenue par le propriétaire de la base (donc peut
-- lire dvf/bdnb/vues), exposée en LECTURE au rôle read-only grafana_ro sans lui
-- accorder l'accès direct aux tables. Idempotent : rejoué chaque jour par
-- deploy/data-upstream-check.sh et à chaque bdnb-local-api.sh (#401).
CREATE SCHEMA IF NOT EXISTS meta;

-- Dernière version PUBLIÉE de chaque source, relevée chaque jour par
-- deploy/data-upstream-check.sh (#401). L'âge d'un millésime ne dit pas s'il
-- existe plus récent : seul l'écart avec la publication le dit.
CREATE TABLE IF NOT EXISTS meta.upstream (
  source     text PRIMARY KEY,
  version    text NOT NULL,
  publiee_le date,
  verifie_le timestamptz NOT NULL DEFAULT now()
);

-- Adresse de chaque bâtiment pour les tableaux de bord (#401). Pointée sur le
-- millésime COURANT à chaque passage : les panneaux qui nommaient le schéma
-- (bdnb_2026_02_a_open_data) seraient tombés au millésime suivant, et
-- grafana_ro n'aurait pas eu le droit de lire le nouveau schéma.
DO $$
DECLARE s text;
BEGIN
  SELECT max(nspname) INTO s FROM pg_namespace
  WHERE nspname ~ '^bdnb_[0-9]{4}_[0-9]{2}_.*open_data$';
  IF s IS NOT NULL THEN
    EXECUTE format('CREATE OR REPLACE VIEW meta.adresse_batiment AS
      SELECT batiment_groupe_id, libelle_adr_principale_ban
      FROM %I.batiment_groupe_adresse', s);
  END IF;
END $$;

-- Colonnes AJOUTÉES en fin (CREATE OR REPLACE VIEW ne sait qu'ajouter) :
-- publiee = dernière version publiée, retard = 1 si elle est plus récente que
-- la nôtre, 0 si nous l'avons, NULL tant que rien n'a été vérifié.
CREATE OR REPLACE VIEW meta.data_updates AS
SELECT ord, t.source, t.version, lignes, as_of, (now()::date - as_of) AS age_jours,
       u.version AS publiee, u.verifie_le,
       CASE WHEN u.version IS NULL OR t.version IS NULL THEN NULL
            WHEN u.version > t.version THEN 1 ELSE 0 END AS retard
FROM (
  -- BDNB : le millésime est encodé dans le NOM du schéma (bdnb_AAAA_MM_...).
  -- Version au format publié (2026-02-a), pour se comparer à meta.upstream.
  SELECT 1 AS ord, 'Bâtiments (BDNB)' AS source,
         regexp_replace(substring(n FROM 'bdnb_([0-9]{4}_[0-9]{2}_[a-z])'), '_', '-', 'g') AS version,
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
LEFT JOIN meta.upstream u ON u.source = t.source
ORDER BY ord;

GRANT USAGE ON SCHEMA meta TO grafana_ro;
GRANT SELECT ON meta.data_updates, meta.upstream TO grafana_ro;
DO $$ BEGIN
  IF to_regclass('meta.adresse_batiment') IS NOT NULL THEN
    GRANT SELECT ON meta.adresse_batiment TO grafana_ro;
  END IF;
END $$;
