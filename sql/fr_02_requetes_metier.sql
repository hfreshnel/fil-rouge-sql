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

-- ===== Séance 3 =====
-- Q3. Mesurez Q2 avec EXPLAIN (ANALYZE, BUFFERS) sur toute la table.
--     Proposez et mesurez UNE optimisation (index, réécriture, partitionnement par mois, vue matérialisée).
--     Collez plan avant / plan après et le gain dans docs/optimisation.md.

-- ===== Bonus qualité (utile pour la séance 5) =====
-- Q4. Détectez les pannes probables : séquences d'au moins 24 heures consécutives à 0 passage
--     pour un compteur habituellement actif (technique « gaps and islands » avec ROW_NUMBER).
