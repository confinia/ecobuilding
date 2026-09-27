-- Journal des exécutions de la CI (#469, règle 25).
--
-- Un échec de pipeline n'était visible que dans un mail — que la session ne
-- peut pas lire — et dans GitHub, qu'il faut penser à ouvrir. Les trois trous
-- de pipeline des 16-17 août ont survécu des semaines pour cette raison.
--
-- Pourquoi une TABLE dans Postgres plutôt qu'une métrique Prometheus : une
-- exécution est un événement daté et étiqueté, pas une série temporelle, et
-- Grafana lit déjà cette base (source « Vues », #349). Aucun conteneur, aucun
-- port, aucun exportateur de plus sur une VM déjà saturée en IOPS (#467).
--
-- À rejouer après un changement de schéma. Écrit par deploy/ci-record.sh avec
-- le rôle propriétaire ; grafana_ro ne fait que LIRE.
CREATE SCHEMA IF NOT EXISTS meta;

CREATE TABLE IF NOT EXISTS meta.ci_run (
    id          bigserial PRIMARY KEY,
    workflow    text        NOT NULL,
    ref         text,
    run_id      text,
    -- 'success' | 'failure' | 'cancelled' : le mot de GitHub, tel quel.
    conclusion  text        NOT NULL,
    url         text,
    ts          timestamptz NOT NULL DEFAULT now()
);

-- Le tableau de bord ne lit que la DERNIÈRE exécution par workflow, et la
-- liste des échecs récents : un index sur (workflow, ts) suffit et reste
-- minuscule (quelques lignes par jour).
CREATE INDEX IF NOT EXISTS ci_run_workflow_ts ON meta.ci_run (workflow, ts DESC);

-- Dernière exécution de chaque workflow, avec son âge : la vue que le panneau
-- interroge. Le SILENCE est un signal — un workflow qui n'a pas tourné depuis
-- longtemps se lit ici, alors qu'un mail d'échec ne dit jamais rien de ce qui
-- n'a pas eu lieu.
CREATE OR REPLACE VIEW meta.ci_last AS
SELECT DISTINCT ON (workflow)
       workflow, conclusion, ref, run_id, url, ts,
       round(extract(epoch FROM (now() - ts)) / 3600)::int AS age_heures
FROM meta.ci_run
ORDER BY workflow, ts DESC;

GRANT USAGE ON SCHEMA meta TO grafana_ro;
GRANT SELECT ON meta.ci_run, meta.ci_last TO grafana_ro;
