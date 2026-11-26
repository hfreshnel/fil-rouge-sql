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
-- Choix : LAG sur v_calendrier (Q1). Une semaine = 168 heures. Comme le calendrier n'a AUCUN trou
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
    FROM v_calendrier
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

-- ===== Bonus qualité (utile pour la séance 5) =====
-- Q4. Détectez les pannes probables : séquences d'au moins 24 heures consécutives à 0 passage
--     pour un compteur habituellement actif (technique « gaps and islands » avec ROW_NUMBER).
