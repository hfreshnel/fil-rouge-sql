-- Fil rouge — Requêtes métier (créneaux fil rouge des séances 2 et 3) — RENDU DE GROUPE
-- Tables : counters, counts_hourly (cf. fr_01_schema.sql)

-- ===== Séance 2 =====
-- Q1. Calendrier complet : pour UN compteur, toutes les heures entre sa première et sa dernière mesure,
--     avec le nombre de passages ou NULL si l'heure manque. (CTE récursive ou generate_series)
--     Combien d'heures manquent par compteur ?
--
-- Choix : generate_series plutôt qu'une CTE récursive. Il produit la même suite d'heures en une seule
-- fonction, sans risque de boucle infinie, et c'est plus rapide sur ~1 M d'heures.
-- Sur timestamptz, « + 1 hour » avance d'une heure réelle : les changements d'heure (mars, octobre)
-- ne créent ni trou ni doublon, puisque les ts sont en UTC.
-- Une heure absente reste NULL, JAMAIS 0 : 0 voudrait dire « personne n'est passé », NULL veut dire
-- « on ne sait pas » (cf. docs/profilage.md).

-- Q1a. Calendrier complet de TOUS les compteurs, en vue : Q2, Q4 et l'indice s'appuient dessus.
--      Pour chaque compteur, une ligne par heure entre sa première et sa dernière mesure.
CREATE OR REPLACE VIEW v_calendrier AS
WITH bornes AS (                                    -- première et dernière mesure de chaque compteur
    SELECT counter_id, min(ts) AS debut, max(ts) AS fin
    FROM counts_hourly
    GROUP BY counter_id
)
SELECT b.counter_id,
       h.ts,
       c.passages                                   -- NULL si l'heure manque (LEFT JOIN sans correspondance)
FROM bornes b
CROSS JOIN LATERAL generate_series(b.debut, b.fin, interval '1 hour') AS h(ts)   -- toutes les heures du compteur
LEFT JOIN counts_hourly c ON c.counter_id = b.counter_id AND c.ts = h.ts;

-- Optimisation retenue en Q3 (voir docs/optimisation.md) : le calendrier est MATÉRIALISÉ.
-- v_calendrier reste la définition ; mv_calendrier en est une copie stockée, triée et indexée,
-- que lisent Q2, Q4 et l'indice. Le tri à la création range les lignes sur disque dans l'ordre
-- (counter_id, ts) : l'index les relit dans cet ordre sans tri.
-- À rafraîchir après chaque chargement : load_comptages.py le fait, et ce script aussi (REFRESH ci-dessous).
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_calendrier AS
    SELECT counter_id, ts, passages FROM v_calendrier ORDER BY counter_id, ts;
CREATE UNIQUE INDEX IF NOT EXISTS mv_calendrier_cle ON mv_calendrier (counter_id, ts);
REFRESH MATERIALIZED VIEW mv_calendrier;
ANALYZE mv_calendrier;

-- Q1b. Calendrier d'UN compteur : Eco 37 - Pont Boieldieu, le plus troué d'après le profilage.
--      Le calendrier complet fait ~40 000 lignes ; on affiche ici le début de son trou de 87 jours
--      (dernière mesure le 02/12/2025 à 07:00 UTC). Retirer le filtre sur ts pour avoir tout le calendrier.
SELECT k.ts, k.passages
FROM v_calendrier k
JOIN counters USING (counter_id)
WHERE counters.name = 'Eco 37 - Pont Boieldieu'
  AND k.ts BETWEEN '2025-12-02 03:00+00' AND '2025-12-02 12:00+00'
ORDER BY k.ts;

-- Q1c. Heures manquantes par compteur (du plus troué au moins troué).
SELECT counters.name,
       count(*)                                     AS heures_attendues,
       count(*) FILTER (WHERE k.passages IS NULL)   AS heures_manquantes,
       round(100.0 * count(*) FILTER (WHERE k.passages IS NULL) / count(*), 1) AS pct_manquant
FROM v_calendrier k
JOIN counters USING (counter_id)
GROUP BY counters.name
ORDER BY heures_manquantes DESC;

-- Q2. Pour chaque compteur et chaque heure, comparez les passages à la moyenne des 4 mêmes créneaux
--     (même jour de semaine, même heure) des 4 semaines précédentes. Indice = observé / moyenne.
--     (indice : LAG(passages, 168) sur une série horaire complète, ou une auto-jointure sur ts - k * 7 jours)
--
-- Choix : LAG sur le calendrier complet (Q1), lu dans sa version matérialisée mv_calendrier (Q3). Une semaine = 168 heures. Comme le calendrier n'a AUCUN trou
-- (une ligne par heure, NULL si la mesure manque), reculer de 168 lignes = reculer de 7 jours exactement.
-- Sur counts_hourly directement, ce serait faux : avec une heure absente, 168 lignes plus haut = plus d'une semaine.
-- Règles (cf. docs/profilage.md et sql/fr_03_indice.sql) :
--   - une semaine sans mesure (NULL) ne compte pas dans la moyenne : moyenne des semaines disponibles ;
--   - nb_semaines dit sur combien de semaines (0 à 4) la référence repose, pour pouvoir filtrer ;
--   - indice NULL (jamais 0) si l'heure observée manque, ou si la référence est absente ou nulle.
-- Limite : les ts sont en UTC. La semaine qui suit un changement d'heure, « même heure » 7 jours plus tôt
-- correspond à 1 h de décalage en heure de Paris (8 h devient 7 h ou 9 h). Effet faible, assumé.

CREATE OR REPLACE VIEW v_comparaison_4sem AS
WITH semaines AS (                                  -- passages du même créneau 1, 2, 3 et 4 semaines avant
    SELECT counter_id, ts, passages,
           LAG(passages, 168) OVER w AS s1,
           LAG(passages, 336) OVER w AS s2,
           LAG(passages, 504) OVER w AS s3,
           LAG(passages, 672) OVER w AS s4
    FROM mv_calendrier                              -- avant l'optimisation Q3 : FROM v_calendrier
    WINDOW w AS (PARTITION BY counter_id ORDER BY ts)
),
reference AS (                                      -- moyenne des semaines disponibles (NULL ignorés)
    SELECT counter_id, ts, passages,
           num_nonnulls(s1, s2, s3, s4) AS nb_semaines,
           (COALESCE(s1, 0) + COALESCE(s2, 0) + COALESCE(s3, 0) + COALESCE(s4, 0))::numeric
               / NULLIF(num_nonnulls(s1, s2, s3, s4), 0) AS attendu   -- NULL si aucune semaine
    FROM semaines
)
SELECT counter_id, ts,
       passages                                     AS observe,
       round(attendu, 2)                            AS attendu,
       nb_semaines,
       round(passages / NULLIF(attendu, 0), 2)      AS indice   -- NULL si observé manquant ou attendu nul
FROM reference;

-- Exemple : les 10 heures les plus au-dessus de l'habitude au compteur le plus fréquenté (Eco 38 - Pont Corneille),
-- sur une référence complète (4 semaines) et d'au moins 50 passages attendus.
-- Sans seuil, le classement est écrasé par des références quasi nulles. Cas réel : Eco 37, mardi 23/06/2026 8 h,
-- 178 passages pour 0,25 attendus -> indice 712, parce que le compteur était à 0 (en panne) les semaines d'avant.
-- D'où la règle du profilage : exclure les pannes (Q4) de la référence de l'indice.
SELECT k.ts AT TIME ZONE 'Europe/Paris' AS heure_paris, k.observe, k.attendu, k.indice
FROM v_comparaison_4sem k
JOIN counters USING (counter_id)
WHERE counters.name = 'Eco 38 - Pont Corneille'
  AND k.nb_semaines = 4
  AND k.attendu >= 50
  AND k.indice IS NOT NULL                         -- en tri décroissant, les NULL passeraient en tête
ORDER BY k.indice DESC
LIMIT 10;

-- ===== Séance 3 =====
-- Q3. Mesurez Q2 avec EXPLAIN (ANALYZE, BUFFERS) sur toute la table.
--     Proposez et mesurez UNE optimisation (index, réécriture, partitionnement par mois, vue matérialisée).
--     Collez plan avant / plan après et le gain dans docs/optimisation.md.
--
-- Optimisation retenue : vue matérialisée mv_calendrier (créée sous Q1a), 2,6 s -> 1,3 s.
-- Mesures reproductibles : psql -h localhost -U etl -d metropole -f sql/q3_mesure.sql
-- Plans, chiffres et pistes écartées : docs/optimisation.md
EXPLAIN (ANALYZE, BUFFERS) SELECT k.ts AT TIME ZONE 'Europe/Paris' AS heure_paris, k.observe, k.attendu, k.indice
FROM v_comparaison_4sem k
JOIN counters USING (counter_id)
WHERE counters.name = 'Eco 38 - Pont Corneille'
  AND k.nb_semaines = 4
  AND k.attendu >= 50
  AND k.indice IS NOT NULL                         
ORDER BY k.indice DESC
LIMIT 10;

-- ===== Bonus qualité (utile pour la séance 5) =====
-- Q4. Détectez les pannes probables : séquences d'au moins 24 heures consécutives à 0 passage
--     pour un compteur habituellement actif (technique « gaps and islands » avec ROW_NUMBER).
--
-- Gaps and islands : on ne garde que les heures à 0, numérotées 1, 2, 3… par compteur (ROW_NUMBER).
-- Dans une suite d'heures CONSÉCUTIVES, ts avance d'1 h et le numéro de 1 : ts - numéro × 1 h reste constant.
-- Dès qu'une heure non nulle (ou manquante) coupe la suite, ts saute plus loin que le numéro et la constante change.
-- Cette constante (« ilot ») identifie donc chaque série ; un GROUP BY dessus donne début, fin et durée.
--   ts      passages  numéro  ts - numéro h
--   10:00   0         1       09:00   ┐ même îlot : 3 h à 0
--   11:00   0         2       09:00   │
--   12:00   0         3       09:00   ┘
--   13:00   5         -       (écartée)
--   14:00   0         4       10:00   ← nouvel îlot
-- On s'appuie sur mv_calendrier : une heure manquante y est NULL (pas 0), elle coupe donc la série.
-- On ne déclare pas « panne » ce qu'on ne connaît pas.
-- Effet visible : chaque nuit de passage à l'heure d'hiver, l'heure 00:00 UTC manque pour TOUS les compteurs
-- (anomalie de la source, cf. docs/profilage.md). La panne d'Eco 22 est ainsi coupée en deux séries
-- (1 710 h puis 758 h) le 26/10/2025. Sans conséquence pour l'indice : les deux séries sont exclues.
--
-- « Habituellement actif » : médiane des totaux journaliers (jours UTC entièrement mesurés) >= 24 passages,
-- soit au moins 1 passage/h en moyenne. Pour un tel compteur, 24 h à 0 n'ont rien de normal.
-- Critère calculé sur TOUTE l'histoire du compteur, pas sur les semaines précédentes (Q2) : une panne
-- fait tomber la référence des semaines suivantes à 0, et la panne suivante paraîtrait alors « normale »
-- (cas réel : Eco 37, 1 087 h à 0 à partir du 27/02/2026, juste après son trou de 87 jours : 0 attendu).
-- Le compteur le plus calme (Eco 19 - Bords de Seine) a une médiane de 50 passages/jour : les 35 sont actifs.

CREATE OR REPLACE VIEW v_pannes AS
WITH jours AS (                                     -- total de chaque jour entièrement mesuré
    SELECT counter_id, date_trunc('day', ts) AS jour, sum(passages) AS total
    FROM mv_calendrier
    GROUP BY counter_id, date_trunc('day', ts)
    HAVING count(passages) = 24                     -- count(col) ignore les NULL : 24 heures mesurées
),
activite AS (                                       -- activité habituelle du compteur
    SELECT counter_id, percentile_cont(0.5) WITHIN GROUP (ORDER BY total) AS mediane_jour
    FROM jours
    GROUP BY counter_id
),
zeros AS (                                          -- heures à 0, avec l'identifiant de leur îlot
    SELECT counter_id, ts,
           ts - ROW_NUMBER() OVER (PARTITION BY counter_id ORDER BY ts) * interval '1 hour' AS ilot
    FROM mv_calendrier
    WHERE passages = 0
),
series AS (                                         -- une ligne par îlot
    SELECT counter_id, min(ts) AS debut, max(ts) AS fin, count(*) AS heures
    FROM zeros
    GROUP BY counter_id, ilot
)
SELECT s.counter_id, s.debut, s.fin, s.heures, a.mediane_jour
FROM series s
JOIN activite a USING (counter_id)
WHERE s.heures >= 24                                -- au moins 24 h consécutives à 0
  AND a.mediane_jour >= 24;                         -- compteur habituellement actif

-- Q4a. Bilan (attendu d'après docs/profilage.md : 33 séries, 5 073 heures, 9 compteurs).
SELECT count(*)                   AS series,
       sum(heures)                AS heures_en_panne,
       count(DISTINCT counter_id) AS compteurs
FROM v_pannes;

-- Q4b. Les 10 pannes les plus longues (heures de Paris).
SELECT counters.name,
       p.debut AT TIME ZONE 'Europe/Paris' AS debut_paris,
       p.fin   AT TIME ZONE 'Europe/Paris' AS fin_paris,
       p.heures,
       round(p.heures / 24.0, 1)           AS jours
FROM v_pannes p
JOIN counters USING (counter_id)
ORDER BY p.heures DESC
LIMIT 10;
