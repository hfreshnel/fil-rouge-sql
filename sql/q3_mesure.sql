-- Fil rouge — Q3 : mesure de Q2 avant / après l'optimisation (vue matérialisée mv_calendrier).
-- Prérequis : sql/fr_02_requetes_metier.sql déjà exécuté (vues v_calendrier, mv_calendrier, v_comparaison_4sem).
-- Lancer :  psql -h localhost -U etl -d metropole -f sql/q3_mesure.sql
-- Résultats et analyse : docs/optimisation.md
--
-- Chaque mesure est lancée 3 fois : la 1re peut lire des pages hors du cache, on retient les suivantes.
-- EXPLAIN ANALYZE exécute vraiment la requête mais ne renvoie pas les lignes : on mesure le calcul, pas l'affichage.

-- ===== AVANT : Q2 calculée sur v_calendrier (calendrier reconstruit à chaque appel) =====
-- Même requête que la vue v_comparaison_4sem ; seule la source change (v_calendrier au lieu de mv_calendrier).
\echo '===== AVANT (v_calendrier) ====='
PREPARE avant AS
WITH semaines AS (
    SELECT counter_id, ts, passages,
           LAG(passages, 168) OVER w AS s1,
           LAG(passages, 336) OVER w AS s2,
           LAG(passages, 504) OVER w AS s3,
           LAG(passages, 672) OVER w AS s4
    FROM v_calendrier
    WINDOW w AS (PARTITION BY counter_id ORDER BY ts)
),
reference AS (
    SELECT counter_id, ts, passages,
           num_nonnulls(s1, s2, s3, s4) AS nb_semaines,
           (COALESCE(s1, 0) + COALESCE(s2, 0) + COALESCE(s3, 0) + COALESCE(s4, 0))::numeric
               / NULLIF(num_nonnulls(s1, s2, s3, s4), 0) AS attendu
    FROM semaines
)
SELECT counter_id, ts, passages AS observe, round(attendu, 2) AS attendu, nb_semaines,
       round(passages / NULLIF(attendu, 0), 2) AS indice
FROM reference;

EXPLAIN (ANALYZE, BUFFERS) EXECUTE avant;
EXPLAIN (ANALYZE, BUFFERS) EXECUTE avant;
EXPLAIN (ANALYZE, BUFFERS) EXECUTE avant;

-- ===== APRÈS : Q2 telle qu'elle est définie (v_comparaison_4sem lit mv_calendrier) =====
\echo '===== APRÈS (mv_calendrier) ====='
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM v_comparaison_4sem;
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM v_comparaison_4sem;
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM v_comparaison_4sem;

-- ===== Coût de l'optimisation : rafraîchir la vue après un chargement, et sa taille =====
\echo '===== Coût : REFRESH et taille ====='
\timing on
REFRESH MATERIALIZED VIEW mv_calendrier;
\timing off
SELECT pg_size_pretty(pg_relation_size('mv_calendrier'))       AS table_mv,
       pg_size_pretty(pg_relation_size('mv_calendrier_cle'))   AS index_mv,
       pg_size_pretty(pg_total_relation_size('counts_hourly')) AS counts_hourly_total;

DEALLOCATE avant;
