-- Natural Disaster Data Platform - Star Schema Design
-- This schema implements a TimescaleDB hypertable with PostGIS for geospatial-temporal analysis

-- ============================================================================
-- DIMENSION TABLES
-- ============================================================================

-- Event Type Dimension (Disaster Classification Hierarchy)
CREATE TABLE IF NOT EXISTS event_type_dim (
    event_type_id SERIAL PRIMARY KEY,
    disaster_group TEXT NOT NULL,           -- e.g., 'Geophysical', 'Meteorological', 'Hydrological'
    disaster_type TEXT NOT NULL,            -- e.g., 'Earthquake', 'Storm', 'Flood'
    disaster_subtype TEXT,                  -- e.g., 'Ground Shaking', 'Tropical Cyclone'
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(disaster_group, disaster_type, disaster_subtype)
);

-- Location Dimension (Geospatial Context)
CREATE TABLE IF NOT EXISTS location_dim (
    location_id BIGSERIAL PRIMARY KEY,
    location_name TEXT,                     -- Original location string
    city TEXT,
    state TEXT,
    country_iso3 CHAR(3),                   -- ISO 3166-1 alpha-3 country code
    geom geography(Point, 4326),            -- PostGIS geography type (WGS84)
    geocoded BOOLEAN DEFAULT false,         -- Flag if geocoded
    geocode_confidence TEXT,                -- Geocoding confidence level
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Create spatial index on location geometry
CREATE INDEX IF NOT EXISTS idx_location_geom ON location_dim USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_location_country ON location_dim (country_iso3);

-- Magnitude Dimension (Heterogeneous Magnitude Scale Storage)
CREATE TABLE IF NOT EXISTS magnitude_dim (
    magnitude_id BIGSERIAL PRIMARY KEY,
    primary_value FLOAT,                    -- e.g., 7.2 for Richter, 150 for wind speed
    primary_unit TEXT,                      -- e.g., 'Richter', 'km/h', 'EF-Scale', 'MMI'
    secondary_value FLOAT,                  -- Optional secondary measurement
    secondary_unit TEXT,                    -- Optional secondary unit
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Source Audit Dimension (Data Lineage and Traceability)
CREATE TABLE IF NOT EXISTS source_audit_dim (
    source_record_id BIGSERIAL PRIMARY KEY,
    staging_event_id TEXT,                  -- Original event ID from source
    source_name TEXT NOT NULL,              -- e.g., 'USGS-PAGER', 'NOAA-FTP', 'EM-DAT'
    ingest_timestamp TIMESTAMPTZ DEFAULT now(),
    raw_data JSONB,                         -- Full original data for debugging
    processing_status TEXT DEFAULT 'pending', -- 'pending', 'processed', 'error'
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_source_name ON source_audit_dim (source_name);
CREATE INDEX IF NOT EXISTS idx_source_staging_id ON source_audit_dim (staging_event_id);

-- ============================================================================
-- FACT TABLE (TimescaleDB Hypertable)
-- ============================================================================

-- Event Fact Table (Central Metrics Table)
CREATE TABLE IF NOT EXISTS event_fact (
    event_id BIGSERIAL PRIMARY KEY,  -- <-- ADDED PRIMARY KEY HERE
    event_time TIMESTAMPTZ NOT NULL,        -- Event start time (UTC) - Hypertable dimension
    event_time_end TIMESTAMPTZ,             -- Event end time (if applicable)
    location_id BIGINT REFERENCES location_dim(location_id),
    event_type_id INT REFERENCES event_type_dim(event_type_id),
    magnitude_id BIGINT REFERENCES magnitude_dim(magnitude_id),
    fatalities_total INT,                   -- Total deaths
    economic_loss_usd BIGINT,               -- Economic loss in USD
    affected_total INT,                     -- Total people affected
    is_master_event BOOLEAN DEFAULT false,  -- True if deduplicated master record
    master_event_id BIGINT,                 -- Self-reference to master if duplicate
    confidence_score FLOAT,                 -- Deduplication confidence (0-1)
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Convert to TimescaleDB hypertable (time-series optimization)
SELECT create_hypertable('event_fact', 'event_time',
    chunk_time_interval => INTERVAL '1 month',
    if_not_exists => TRUE
);

-- Create indexes on fact table
CREATE INDEX IF NOT EXISTS idx_event_location ON event_fact (location_id, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_event_type ON event_fact (event_type_id, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_event_master ON event_fact (is_master_event, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_event_time ON event_fact (event_time DESC);

-- ============================================================================
-- EVENT-SOURCE JUNCTION TABLE (Many-to-Many Relationship)
-- ============================================================================

-- Links master events to their constituent source records
CREATE TABLE IF NOT EXISTS event_source_junction (
    event_id BIGINT REFERENCES event_fact(event_id),
    source_record_id BIGINT REFERENCES source_audit_dim(source_record_id),
    contribution_weight FLOAT DEFAULT 1.0,   -- How much this source contributed
    PRIMARY KEY (event_id, source_record_id)
);

-- ============================================================================
-- STAGING TABLES (Raw Data Landing Zone)
-- ============================================================================

-- Staging table for raw events before transformation
CREATE TABLE IF NOT EXISTS staging.raw_events (
    staging_id BIGSERIAL PRIMARY KEY,
    source_name TEXT NOT NULL,
    source_event_id TEXT,
    event_time TIMESTAMPTZ,
    location_text TEXT,
    latitude FLOAT,
    longitude FLOAT,
    disaster_type TEXT,
    magnitude_value FLOAT,
    magnitude_unit TEXT,
    fatalities INT,
    economic_loss TEXT,                      -- Raw string (e.g., "10.5M")
    affected INT,
    raw_json JSONB,
    ingested_at TIMESTAMPTZ DEFAULT now(),
    processed BOOLEAN DEFAULT false
);

CREATE INDEX IF NOT EXISTS idx_staging_processed ON staging.raw_events (processed, ingested_at);
CREATE INDEX IF NOT EXISTS idx_staging_source ON staging.raw_events (source_name);

-- ============================================================================
-- SEED DATA (Initial Event Types)
-- ============================================================================

INSERT INTO event_type_dim (disaster_group, disaster_type, disaster_subtype) VALUES
    -- Geophysical
    ('Geophysical', 'Earthquake', 'Ground Shaking'),
    ('Geophysical', 'Earthquake', 'Tsunami'),
    ('Geophysical', 'Volcano', 'Volcanic Activity'),
    ('Geophysical', 'Mass Movement', 'Landslide'),
    ('Geophysical', 'Mass Movement', 'Avalanche'),

    -- Meteorological
    ('Meteorological', 'Storm', 'Tropical Cyclone'),
    ('Meteorological', 'Storm', 'Tornado'),
    ('Meteorological', 'Storm', 'Severe Storm'),
    ('Meteorological', 'Extreme Temperature', 'Heat Wave'),
    ('Meteorological', 'Extreme Temperature', 'Cold Wave'),
    ('Meteorological', 'Fog', NULL),

    -- Hydrological
    ('Hydrological', 'Flood', 'Riverine Flood'),
    ('Hydrological', 'Flood', 'Flash Flood'),
    ('Hydrological', 'Flood', 'Coastal Flood'),
    ('Hydrological', 'Mass Movement', 'Mudslide'),

    -- Climatological
    ('Climatological', 'Drought', NULL),
    ('Climatological', 'Wildfire', NULL),

    -- Biological
    ('Biological', 'Epidemic', NULL),
    ('Biological', 'Insect Infestation', NULL),

    -- Extraterrestrial
    ('Extraterrestrial', 'Impact', 'Meteor')
ON CONFLICT (disaster_group, disaster_type, disaster_subtype) DO NOTHING;

-- ============================================================================
-- UTILITY FUNCTIONS
-- ============================================================================

-- Function to parse economic loss strings (e.g., "10.5M" -> 10500000)
CREATE OR REPLACE FUNCTION parse_economic_loss(loss_string TEXT)
RETURNS BIGINT AS $$
DECLARE
    multiplier BIGINT := 1;
    numeric_part TEXT;
    suffix CHAR(1);
BEGIN
    IF loss_string IS NULL OR loss_string = '' THEN
        RETURN NULL;
    END IF;

    -- Extract suffix
    suffix := UPPER(RIGHT(loss_string, 1));

    -- Determine multiplier
    CASE suffix
        WHEN 'K' THEN multiplier := 1000;
        WHEN 'M' THEN multiplier := 1000000;
        WHEN 'B' THEN multiplier := 1000000000;
        ELSE
            -- No suffix, try direct conversion
            BEGIN
                RETURN loss_string::BIGINT;
            EXCEPTION WHEN OTHERS THEN
                RETURN NULL;
            END;
    END CASE;

    -- Extract numeric part
    numeric_part := TRIM(SUBSTRING(loss_string FROM 1 FOR LENGTH(loss_string) - 1));

    RETURN (numeric_part::FLOAT * multiplier)::BIGINT;
EXCEPTION WHEN OTHERS THEN
    RETURN NULL;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Function to get or create location
CREATE OR REPLACE FUNCTION get_or_create_location(
    p_lat FLOAT,
    p_lon FLOAT,
    p_location_name TEXT DEFAULT NULL,
    p_city TEXT DEFAULT NULL,
    p_state TEXT DEFAULT NULL,
    p_country_iso3 CHAR(3) DEFAULT NULL
)
RETURNS BIGINT AS $$
DECLARE
    v_location_id BIGINT;
    v_geom geography;
BEGIN
    -- Create geography point
    IF p_lat IS NOT NULL AND p_lon IS NOT NULL THEN
        v_geom := ST_SetSRID(ST_MakePoint(p_lon, p_lat), 4326)::geography;

        -- Try to find existing location within 1km
        SELECT location_id INTO v_location_id
        FROM location_dim
        WHERE ST_DWithin(geom, v_geom, 1000)  -- 1km radius
        LIMIT 1;

        IF v_location_id IS NOT NULL THEN
            RETURN v_location_id;
        END IF;
    END IF;

    -- Create new location
    INSERT INTO location_dim (location_name, city, state, country_iso3, geom, geocoded)
    VALUES (p_location_name, p_city, p_state, p_country_iso3, v_geom, p_lat IS NOT NULL)
    RETURNING location_id INTO v_location_id;

    RETURN v_location_id;
END;
$$ LANGUAGE plpgsql;

-- Create view for master events with full context
CREATE OR REPLACE VIEW v_master_events AS
SELECT
    e.event_id,
    e.event_time,
    e.event_time_end,
    e.fatalities_total,
    e.economic_loss_usd,
    e.affected_total,
    et.disaster_group,
    et.disaster_type,
    et.disaster_subtype,
    l.location_name,
    l.city,
    l.state,
    l.country_iso3,
    ST_Y(l.geom::geometry) AS latitude,
    ST_X(l.geom::geometry) AS longitude,
    m.primary_value AS magnitude,
    m.primary_unit AS magnitude_unit,
    e.created_at,
    ARRAY_AGG(DISTINCT sa.source_name) AS sources
FROM event_fact e
LEFT JOIN event_type_dim et ON e.event_type_id = et.event_type_id
LEFT JOIN location_dim l ON e.location_id = l.location_id
LEFT JOIN magnitude_dim m ON e.magnitude_id = m.magnitude_id
LEFT JOIN event_source_junction esj ON e.event_id = esj.event_id
LEFT JOIN source_audit_dim sa ON esj.source_record_id = sa.source_record_id
WHERE e.is_master_event = true
GROUP BY e.event_id, et.event_type_id, l.location_id, m.magnitude_id;

-- Grant permissions on view
GRANT SELECT ON v_master_events TO disaster_user;

COMMENT ON TABLE event_fact IS 'TimescaleDB hypertable storing all disaster event metrics';
COMMENT ON TABLE location_dim IS 'Geospatial dimension using PostGIS geography type';
COMMENT ON TABLE source_audit_dim IS 'Complete data lineage for debugging and traceability';
COMMENT ON VIEW v_master_events IS 'Consolidated view of master (deduplicated) events with full context';
