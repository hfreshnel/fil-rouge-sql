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
