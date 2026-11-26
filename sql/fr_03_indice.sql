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
