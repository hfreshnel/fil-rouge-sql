-- Fil rouge — Livrable final : indice de surfréquentation par événement — RENDU DE GROUPE
--
-- Méthode imposée :
--  1. Zone : rattacher chaque lieu (venues) aux compteurs à moins de 800 m et aux stations Lovélo à moins de 500 m
--     -> remplir event_zone avec la fonction distance_m().
--  2. Fenêtre : de 1 h avant le début à 1 h après la fin de chaque occurrence (event_occurrences).
--  3. Référence : même créneau, même jour de semaine, sur les 4 semaines précédentes,
--     EN EXCLUANT les créneaux où un autre événement a lieu dans la même zone.
--  4. Indice = passages observés / passages de référence (moyenne). NULL si aucun capteur ou référence nulle.
--
-- À livrer :
--  R1. INSERT INTO event_zone ... (rattachement)
--  R2. Une vue v_indice_evenement(event_uid, begin_ts, counter_id, observe, attendu, indice)
--  R3. Top 10 des événements par indice moyen, avec RANK()
--  R4. Part des événements sans aucun capteur à proximité (couverture) — à commenter dans la Dataset Card
--  R5. (option Lovélo) baisse moyenne de vélos disponibles pendant la fenêtre vs la référence
--
-- Prérequis : comptages chargés + sql/fr_02_requetes_metier.sql (mv_calendrier, v_pannes),
--             événements et lieux chargés (transform/clean_events.py), stations Lovélo (option).

-- ===== R1. Rattachement des lieux aux capteurs proches (event_zone) =====
-- Pour chaque lieu, tous les compteurs à moins de 800 m et toutes les stations Lovélo à moins de 500 m.
-- Un lieu peut avoir plusieurs capteurs, un capteur peut servir à plusieurs lieux (relation n-n).
--
-- Choix :
--  - event_zone est une table CALCULÉE : on la vide puis on la recalcule entièrement. Un simple
--    ON CONFLICT laisserait en place une paire devenue fausse (lieu dont les coordonnées ont été corrigées).
--    TRUNCATE + INSERT dans une même transaction : en cas d'erreur, l'ancienne version reste intacte.
--  - Les lieux sans coordonnées sont ignorés : ils n'auront aucun capteur, donc un indice NULL (R4 les compte).
--  - Produit cartésien lieux × capteurs : quelques centaines de lieux × 35 compteurs, quelques milliers de
--    distances à calculer, c'est instantané. Pas besoin d'index spatial (PostGIS) à ce volume.
BEGIN;
TRUNCATE event_zone;

INSERT INTO event_zone (venue_id, sensor_kind, sensor_id, distance_m)
WITH paires AS (                                    -- distance de chaque lieu à chaque capteur
    SELECT v.venue_id, 'counter' AS sensor_kind, c.counter_id AS sensor_id,
           distance_m(v.lat, v.lon, c.lat, c.lon) AS distance_m
    FROM venues v
    CROSS JOIN counters c
    WHERE v.lat IS NOT NULL AND v.lon IS NOT NULL
      AND c.lat IS NOT NULL AND c.lon IS NOT NULL
    UNION ALL
    SELECT v.venue_id, 'lovelo', s.station_id,
           distance_m(v.lat, v.lon, s.lat, s.lon)
    FROM venues v
    CROSS JOIN lovelo_stations s
    WHERE v.lat IS NOT NULL AND v.lon IS NOT NULL
      AND s.lat IS NOT NULL AND s.lon IS NOT NULL
)
SELECT venue_id, sensor_kind, sensor_id, round(distance_m::numeric, 1)
FROM paires
WHERE (sensor_kind = 'counter' AND distance_m < 800)    -- zone imposée : 800 m pour les compteurs
   OR (sensor_kind = 'lovelo'  AND distance_m < 500);   --                500 m pour Lovélo

COMMIT;

-- R1 bis. Contrôle : lieux rattachés et capteurs par lieu.
SELECT count(*)                                                         AS lieux,
       count(*) FILTER (WHERE v.lat IS NULL)                            AS sans_coordonnees,
       count(*) FILTER (WHERE z.nb_compteurs > 0)                       AS avec_compteur,
       count(*) FILTER (WHERE z.nb_stations > 0)                        AS avec_station_lovelo,
       count(*) FILTER (WHERE coalesce(z.nb_compteurs, 0) + coalesce(z.nb_stations, 0) = 0) AS sans_capteur
FROM venues v
LEFT JOIN (SELECT venue_id,
                  count(*) FILTER (WHERE sensor_kind = 'counter') AS nb_compteurs,
                  count(*) FILTER (WHERE sensor_kind = 'lovelo')  AS nb_stations
           FROM event_zone GROUP BY venue_id) z USING (venue_id);

-- R1 ter. Détail par lieu : compteur le plus proche et nombre de capteurs dans la zone.
SELECT v.name, v.city,
       count(*) FILTER (WHERE z.sensor_kind = 'counter')               AS compteurs,
       count(*) FILTER (WHERE z.sensor_kind = 'lovelo')                AS stations,
       min(z.distance_m) FILTER (WHERE z.sensor_kind = 'counter')      AS compteur_le_plus_proche_m
FROM venues v
LEFT JOIN event_zone z USING (venue_id)
GROUP BY v.venue_id, v.name, v.city
ORDER BY compteurs DESC, v.name;

-- ===== R2. Indice de surfréquentation par occurrence et par compteur (v_indice_evenement) =====
-- Une ligne par (occurrence, compteur de la zone). Une occurrence sans compteur garde UNE ligne, avec
-- counter_id et indice NULL : elle reste visible, et R4 la compte dans la couverture.
--
-- Règles (méthode imposée + docs/profilage.md) :
--  - Fenêtre : de begin_ts - 1 h à end_ts + 1 h. On prend toutes les heures qui la CHEVAUCHENT
--    (une heure h compte si h < fin et h + 1 h > début) : 20:30-22:45 -> fenêtre 19:30-23:45 -> heures 19 h à 23 h.
--  - Observé : somme des passages du compteur sur ces heures.
--  - Référence : la même fenêtre 1, 2, 3 et 4 semaines avant (k = 1..4), décalée en HEURE DE PARIS
--    (AT TIME ZONE) : un concert à 20 h est comparé à 20 h, même autour des changements d'heure.
--    attendu = moyenne des semaines retenues ; nb_semaines = combien ont été retenues (0 à 4).
--  - Une fenêtre (observée ou de référence) ne vaut que si TOUTES ses heures sont mesurées et hors panne (Q4) :
--    une somme amputée d'une heure serait trop basse. Sinon elle vaut NULL.
--  - Une semaine de référence est écartée si une autre occurrence (non annulée) a lieu au même moment
--    dans la zone du même compteur : elle gonflerait l'habitude.
--  - Les événements annulés sont exclus : ils n'ont pas eu lieu (statut 'annule', cf. transform/clean_events.py).
--  - indice = observe / attendu, NULL (jamais 0) si pas de compteur, observé NULL, ou attendu NULL ou nul.
CREATE OR REPLACE VIEW v_indice_evenement AS
WITH pannes AS MATERIALIZED (                       -- 33 séries (Q4), calculées une seule fois
    SELECT counter_id, debut, fin FROM v_pannes
),
occurrences AS (                                    -- occurrences à analyser, avec leur fenêtre ± 1 h
    SELECT o.event_uid, o.begin_ts, e.venue_id,
           o.begin_ts - interval '1 hour' AS debut_fenetre,
           o.end_ts   + interval '1 hour' AS fin_fenetre
    FROM event_occurrences o
    JOIN events e USING (event_uid)
    WHERE e.status IS DISTINCT FROM 'annule'        -- IS DISTINCT FROM : un statut NULL est gardé
),
occupations AS MATERIALIZED (                       -- pour chaque compteur, les fenêtres des occurrences de sa zone
    SELECT z.sensor_id AS counter_id, oc.event_uid, oc.begin_ts, oc.debut_fenetre, oc.fin_fenetre
    FROM occurrences oc
    JOIN event_zone z ON z.venue_id = oc.venue_id AND z.sensor_kind = 'counter'
),
fenetres AS (                                       -- k = 0 : fenêtre observée ; k = 1..4 : semaines de référence
    SELECT oc.event_uid, oc.begin_ts, oc.counter_id, s.k,
           ((oc.debut_fenetre AT TIME ZONE 'Europe/Paris') - s.k * interval '7 days') AT TIME ZONE 'Europe/Paris' AS debut_k,
           ((oc.fin_fenetre   AT TIME ZONE 'Europe/Paris') - s.k * interval '7 days') AT TIME ZONE 'Europe/Paris' AS fin_k
    FROM occupations oc
    CROSS JOIN generate_series(0, 4) AS s(k)
),
heures AS (                                         -- chaque heure de chaque fenêtre, mesurée ou non
    SELECT f.event_uid, f.begin_ts, f.counter_id, f.k, f.debut_k, f.fin_k, c.passages,
           EXISTS (SELECT 1 FROM pannes p
                   WHERE p.counter_id = f.counter_id AND h.ts BETWEEN p.debut AND p.fin) AS en_panne
    FROM fenetres f
    CROSS JOIN LATERAL generate_series(date_trunc('hour', f.debut_k), f.fin_k, interval '1 hour') AS h(ts)
    LEFT JOIN mv_calendrier c ON c.counter_id = f.counter_id AND c.ts = h.ts   -- NULL si hors calendrier ou manquante
    WHERE h.ts < f.fin_k
),
sommes AS (                                         -- passages de chaque fenêtre, NULL si incomplète ou en panne
    SELECT event_uid, begin_ts, counter_id, k, debut_k, fin_k,
           CASE WHEN count(passages) = count(*)     -- count(passages) ignore les NULL : toutes les heures mesurées
                 AND NOT bool_or(en_panne)          -- et aucune en panne
                THEN sum(passages) END AS passages
    FROM heures
    GROUP BY event_uid, begin_ts, counter_id, k, debut_k, fin_k
),
-- Semaines de référence occupées par un autre événement. Comparer chaque semaine à TOUTES les occurrences
-- prenait 40 s (pas d'index possible sur une CTE). Deux fenêtres ne peuvent se chevaucher que si elles touchent
-- un même jour : on répète chaque fenêtre pour chaque jour qu'elle touche, et on joint sur (compteur, jour).
-- PostgreSQL fait alors une jointure par hachage sur de tout petits groupes.
occupations_jours AS MATERIALIZED (
    SELECT o.counter_id, o.event_uid, o.begin_ts, o.debut_fenetre, o.fin_fenetre, j.jour
    FROM occupations o
    CROSS JOIN LATERAL generate_series(date_trunc('day', o.debut_fenetre), o.fin_fenetre, interval '1 day') AS j(jour)
),
bloquees AS MATERIALIZED (                          -- calculée UNE fois (sinon recalculée pour chaque ligne)
    SELECT DISTINCT f.event_uid, f.begin_ts, f.counter_id, f.k
    FROM fenetres f
    CROSS JOIN LATERAL generate_series(date_trunc('day', f.debut_k), f.fin_k, interval '1 day') AS j(jour)
    JOIN occupations_jours o ON o.counter_id = f.counter_id AND o.jour = j.jour   -- même compteur, même jour
    WHERE f.k > 0
      AND (o.event_uid, o.begin_ts) <> (f.event_uid, f.begin_ts)                  -- une AUTRE occurrence
      AND o.debut_fenetre < f.fin_k AND o.fin_fenetre > f.debut_k                 -- les deux fenêtres se chevauchent
),
retenues AS (                                       -- observé (k = 0) + semaines de référence non bloquées
    SELECT s.*
    FROM sommes s
    LEFT JOIN bloquees b USING (event_uid, begin_ts, counter_id, k)   -- anti-jointure : garder ce qui n'est PAS bloqué
    WHERE b.k IS NULL                               -- k = 0 n'est jamais bloqué (bloquees ne contient que k > 0)
),
par_compteur AS (
    SELECT event_uid, begin_ts, counter_id,
           max(passages)   FILTER (WHERE k = 0) AS observe,
           avg(passages)   FILTER (WHERE k > 0) AS attendu,     -- avg ignore les semaines NULL
           count(passages) FILTER (WHERE k > 0) AS nb_semaines
    FROM retenues
    GROUP BY event_uid, begin_ts, counter_id
)
SELECT oc.event_uid, oc.begin_ts, p.counter_id,
       p.observe,
       round(p.attendu, 2)                          AS attendu,
       coalesce(p.nb_semaines, 0)                   AS nb_semaines,
       round(p.observe / NULLIF(p.attendu, 0), 2)   AS indice
FROM occurrences oc
LEFT JOIN par_compteur p USING (event_uid, begin_ts);   -- garde les occurrences sans compteur

-- ===== R3. Top 10 des événements par indice moyen, avec RANK() =====
-- Indice moyen d'un événement = moyenne de ses indices, toutes occurrences et tous compteurs de la zone confondus.
--
-- Choix :
--  - Seuil de robustesse, pour le CLASSEMENT seulement (la vue R2 garde tout) : une mesure n'entre que si
--    au moins 20 passages étaient attendus sur la fenêtre. Sous ce seuil, l'indice est surtout du bruit :
--    12 passages pour 4 attendus donnent 3,0. Sur le jeu synthétique, ce seuil écarte 3 % des mesures.
--  - RANK() et pas ROW_NUMBER() : deux événements à égalité ont le même rang, et le suivant saute
--    (1, 2, 2, 4). Le « top 10 » peut donc compter plus de 10 lignes en cas d'égalité au 10e rang.
--    DENSE_RANK() ne sauterait pas de rang (1, 2, 2, 3).
--  - Le rang est calculé sur l'indice non arrondi : arrondir avant créerait de fausses égalités.
WITH mesures AS (
    SELECT * FROM v_indice_evenement
    WHERE indice IS NOT NULL
      AND attendu >= 20                             -- seuil de robustesse (voir ci-dessus)
),
par_evenement AS (
    SELECT event_uid,
           avg(indice)                       AS indice_moyen,
           count(*)                          AS nb_mesures,         -- couples (occurrence, compteur)
           count(DISTINCT begin_ts)          AS nb_occurrences,
           count(DISTINCT counter_id)        AS nb_compteurs,
           sum(observe)                      AS observe_total,
           round(sum(attendu))               AS attendu_total
    FROM mesures
    GROUP BY event_uid
),
classement AS (
    SELECT *, RANK() OVER (ORDER BY indice_moyen DESC) AS rang
    FROM par_evenement
)
SELECT k.rang,
       e.title                               AS evenement,
       v.name                                AS lieu,
       round(k.indice_moyen, 2)              AS indice_moyen,
       k.nb_occurrences, k.nb_compteurs, k.nb_mesures,
       k.observe_total, k.attendu_total
FROM classement k
JOIN events e USING (event_uid)
LEFT JOIN venues v USING (venue_id)
WHERE k.rang <= 10
ORDER BY k.rang, e.title;

-- ===== R4. Couverture : part des événements sans aucun capteur à proximité =====
-- À reporter et commenter dans la Dataset Card (section limites).
-- Périmètre : événements non annulés ayant au moins une occurrence (ceux que l'indice cherche à mesurer).
-- Chaque événement est classé dans UNE catégorie, de la plus bloquante à la meilleure, pour voir où on le perd :
--   1. lieu sans coordonnées          -> impossible à rattacher
--   2. aucun capteur à proximité      -> ni compteur à moins de 800 m, ni station à moins de 500 m
--   3. station Lovélo seulement       -> pas d'indice vélo (R2 ne porte que sur les compteurs), utile pour R5
--   4. compteur, mais aucun indice    -> référence absente (autres événements), panne ou heures manquantes
--   5. au moins un indice calculé
-- « Sans aucun capteur » (la question R4) = catégories 1 + 2.
CREATE OR REPLACE VIEW v_couverture AS
WITH capteurs_par_lieu AS (                         -- ce que chaque lieu a dans sa zone
    SELECT venue_id,
           bool_or(sensor_kind = 'counter') AS a_compteur,
           bool_or(sensor_kind = 'lovelo')  AS a_station
    FROM event_zone
    GROUP BY venue_id
),
avec_indice AS MATERIALIZED (                       -- événements avec au moins un indice (R2 calculée une seule fois)
    SELECT DISTINCT event_uid FROM v_indice_evenement WHERE indice IS NOT NULL
)
SELECT e.event_uid,
       CASE WHEN v.lat IS NULL OR v.lon IS NULL     THEN '1. lieu sans coordonnées'
            WHEN c.venue_id IS NULL                 THEN '2. aucun capteur à proximité'
            WHEN NOT c.a_compteur                   THEN '3. station Lovélo seulement'
            WHEN i.event_uid IS NULL                THEN '4. compteur, mais aucun indice'
            ELSE                                         '5. au moins un indice'
       END AS categorie
FROM events e
LEFT JOIN venues v USING (venue_id)
LEFT JOIN capteurs_par_lieu c USING (venue_id)
LEFT JOIN avec_indice i USING (event_uid)
WHERE e.status IS DISTINCT FROM 'annule'
  AND EXISTS (SELECT 1 FROM event_occurrences o WHERE o.event_uid = e.event_uid);

-- R4a. Répartition des événements par catégorie.
SELECT categorie,
       count(*)                                              AS evenements,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1)    AS pct      -- sum(...) OVER () : total de toutes les lignes
FROM v_couverture
GROUP BY categorie
ORDER BY categorie;

-- R4b. La réponse à R4, en une ligne.
--      NULLIF(count(*), 0) : sans événement chargé, les pourcentages valent NULL au lieu d'une division par zéro.
SELECT count(*)                                                                                   AS evenements,
       round(100.0 * count(*) FILTER (WHERE categorie < '3') / NULLIF(count(*), 0), 1)            AS pct_sans_aucun_capteur,
       round(100.0 * count(*) FILTER (WHERE categorie < '4') / NULLIF(count(*), 0), 1)            AS pct_sans_compteur,
       round(100.0 * count(*) FILTER (WHERE categorie = '5. au moins un indice') / NULLIF(count(*), 0), 1) AS pct_avec_indice
FROM v_couverture;
