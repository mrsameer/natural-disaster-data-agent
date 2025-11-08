-- Initialize PostgreSQL with required extensions
-- This script runs when the database is first created

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- Enable PostGIS extension for geospatial capabilities
CREATE EXTENSION IF NOT EXISTS postgis;

-- Create schema for staging data
CREATE SCHEMA IF NOT EXISTS staging;

-- Grant privileges
GRANT ALL PRIVILEGES ON SCHEMA public TO disaster_user;
GRANT ALL PRIVILEGES ON SCHEMA staging TO disaster_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO disaster_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA staging TO disaster_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO disaster_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA staging TO disaster_user;

-- Set default privileges for future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO disaster_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA staging GRANT ALL ON TABLES TO disaster_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO disaster_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA staging GRANT ALL ON SEQUENCES TO disaster_user;
