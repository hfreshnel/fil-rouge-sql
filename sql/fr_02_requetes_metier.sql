-- Fil rouge — Requêtes métier (créneaux fil rouge des séances 2 et 3) — RENDU DE GROUPE
-- Tables : counters, counts_hourly (cf. fr_01_schema.sql)

-- ===== Séance 2 =====
-- Q1. Calendrier complet : pour UN compteur, toutes les heures entre sa première et sa dernière mesure,
--     avec le nombre de passages ou NULL si l'heure manque. (CTE récursive ou generate_series)
--     Combien d'heures manquent par compteur ?

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
