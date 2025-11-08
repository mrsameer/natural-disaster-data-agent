"""Configuration management for the disaster data platform"""
import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Base paths
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"

# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)
(DATA_DIR / "raw").mkdir(exist_ok=True)
(DATA_DIR / "staging").mkdir(exist_ok=True)
(DATA_DIR / "processed").mkdir(exist_ok=True)

# Database configuration
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "database": os.getenv("DB_NAME", "disaster_data"),
    "user": os.getenv("DB_USER", "disaster_user"),
    "password": os.getenv("DB_PASSWORD", "disaster_pass"),
}

# Database URL for SQLAlchemy
DB_URL = f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}"

# USGS Configuration
USGS_CONFIG = {
    "base_url": os.getenv("USGS_BASE_URL", "https://earthquake.usgs.gov/fdsnws/event/1"),
    "start_date": os.getenv("USGS_START_DATE", "2010-01-01"),
    "format": "geojson",
    "timeout": 30,
}

# HDX (EM-DAT) Configuration
HDX_CONFIG = {
    "site": os.getenv("HDX_SITE", "prod"),
    "dataset_name": "emdat-natural-disasters",
    "timeout": 60,
}

# Geocoding Configuration
GEOCODING_CONFIG = {
    "user_agent": os.getenv("GEOCODING_USER_AGENT", "disaster_agent_v1"),
    "timeout": int(os.getenv("GEOCODING_TIMEOUT", "10")),
    "max_retries": 3,
}

# ETL Configuration
ETL_CONFIG = {
    "batch_size": int(os.getenv("BATCH_SIZE", "1000")),
    "max_workers": int(os.getenv("MAX_WORKERS", "4")),
    "deduplication_time_window_hours": 48,
    "deduplication_distance_meters": 100000,  # 100km
}

# Dashboard Configuration
DASHBOARD_CONFIG = {
    "host": os.getenv("DASH_HOST", "0.0.0.0"),
    "port": int(os.getenv("DASH_PORT", "8050")),
    "debug": os.getenv("DASH_DEBUG", "false").lower() == "true",
}

# Logging Configuration
LOG_CONFIG = {
    "level": os.getenv("LOG_LEVEL", "INFO"),
    "file": os.getenv("LOG_FILE", str(LOGS_DIR / "disaster_agent.log")),
    "rotation": "500 MB",
    "retention": "30 days",
}
