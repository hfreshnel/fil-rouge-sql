-- Fil rouge « Les événements font-ils bouger la Métropole ? » — schéma PostgreSQL
-- Base dédiée conseillée :  CREATE DATABASE metropole;  puis  psql -d metropole -f fr_01_schema.sql
-- Les noms de colonnes sont NOS noms normalisés : le chargement fait la correspondance avec les sources.

DROP TABLE IF EXISTS event_zone, counts_hourly, counters, lovelo_status, lovelo_stations,
                     event_occurrences, events, venues CASCADE;

-- Référentiel des lieux (salles et équipements culturels + lieux rencontrés dans l'agenda)
CREATE TABLE venues (
    venue_id     BIGSERIAL PRIMARY KEY,
    name         TEXT NOT NULL,
    name_norm    TEXT NOT NULL,              -- nom normalisé (minuscules, sans accents ni ponctuation)
    address      TEXT,
    city         TEXT,
    lat          DOUBLE PRECISION,
    lon          DOUBLE PRECISION,
    source       TEXT NOT NULL,              -- 'referentiel' | 'openagenda'
    UNIQUE (name_norm, city)
);

-- Événements (un par uid OpenAgenda)
CREATE TABLE events (
    event_uid    BIGINT PRIMARY KEY,
    title        TEXT NOT NULL,
    description  TEXT,
    keywords     TEXT[],
    venue_id     BIGINT REFERENCES venues(venue_id),
    status       TEXT,                       -- programmé, annulé, reporté…
    updated_at   TIMESTAMPTZ,
    loaded_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Un événement peut avoir plusieurs dates : une ligne par occurrence
CREATE TABLE event_occurrences (
    event_uid    BIGINT NOT NULL REFERENCES events(event_uid) ON DELETE CASCADE,
    begin_ts     TIMESTAMPTZ NOT NULL,
    end_ts       TIMESTAMPTZ NOT NULL CHECK (end_ts >= begin_ts),
    PRIMARY KEY (event_uid, begin_ts)
);

-- Compteurs vélo (Eco Compteur, portail Métropole)
CREATE TABLE counters (
    counter_id   TEXT PRIMARY KEY,
    name         TEXT,
    lat          DOUBLE PRECISION,
    lon          DOUBLE PRECISION
);

-- Comptages horaires : la table volumineuse (index et partitionnement en séance 3)
CREATE TABLE counts_hourly (
    counter_id   TEXT NOT NULL REFERENCES counters(counter_id),
    ts           TIMESTAMPTZ NOT NULL,       -- début de l'heure
    passages     INTEGER CHECK (passages >= 0),
    PRIMARY KEY (counter_id, ts)
);

-- Lovélo (option) : stations et relevés collectés
CREATE TABLE lovelo_stations (
    station_id   TEXT PRIMARY KEY,
    name         TEXT,
    lat          DOUBLE PRECISION,
    lon          DOUBLE PRECISION,
    capacity     INTEGER
);
CREATE TABLE lovelo_status (
    station_id      TEXT NOT NULL REFERENCES lovelo_stations(station_id),
    reported_at     TIMESTAMPTZ NOT NULL,
    bikes_available INTEGER,
    docks_available INTEGER,
    is_renting      BOOLEAN,
    PRIMARY KEY (station_id, reported_at)    -- dédoublonnage naturel des relevés
);

-- Rattachement d'un lieu aux capteurs proches (calculé, cf. fr_03_indice.sql)
CREATE TABLE event_zone (
    venue_id     BIGINT NOT NULL REFERENCES venues(venue_id),
    sensor_kind  TEXT NOT NULL CHECK (sensor_kind IN ('counter', 'lovelo')),
    sensor_id    TEXT NOT NULL,
    distance_m   DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (venue_id, sensor_kind, sensor_id)
);

-- Distance en mètres entre deux points (formule de haversine), sans extension PostGIS
CREATE OR REPLACE FUNCTION distance_m(lat1 float8, lon1 float8, lat2 float8, lon2 float8)
RETURNS float8 LANGUAGE sql IMMUTABLE AS $$
  SELECT 2 * 6371000 * asin(sqrt(
           power(sin(radians(lat2 - lat1) / 2), 2)
         + cos(radians(lat1)) * cos(radians(lat2)) * power(sin(radians(lon2 - lon1) / 2), 2)))
$$;
