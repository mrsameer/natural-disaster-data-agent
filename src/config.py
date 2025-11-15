"""Configuration management for the disaster data platform"""
import os
from pathlib import Path
from typing import Optional, Sequence
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def _sanitize_env_value(value: Optional[str], placeholders: Optional[Sequence[str]] = None) -> Optional[str]:
    """Normalize env values, treating blanks or placeholders as unset."""
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None

    # Remove inline comments that start with '#'
    if "#" in cleaned:
        hash_index = cleaned.find("#")
        if hash_index == 0:
            return None
        cleaned = cleaned[:hash_index].rstrip()

    if not cleaned:
        return None
    if placeholders:
        lowered = cleaned.lower()
        for placeholder in placeholders:
            if lowered == placeholder.lower():
                return None
    return cleaned


def _get_env(
    name: str,
    default: Optional[str] = None,
    placeholders: Optional[Sequence[str]] = None,
) -> Optional[str]:
    raw = os.getenv(name)
    if raw is None:
        raw = default
    return _sanitize_env_value(raw, placeholders)

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
# Note: EM-DAT full database requires subscription
# Using publicly available country profiles (aggregated data)
HDX_CONFIG = {
    "site": os.getenv("HDX_SITE", "prod"),
    "dataset_name": os.getenv("HDX_DATASET_NAME", "emdat-country-profiles"),
    "timeout": 60,
}

# Web Agent Configuration (Google ADK + AI Crawling)
# This agent uses Google Gemini LLM for intelligent event extraction from web sources
_google_api_key = _get_env("GOOGLE_API_KEY", placeholders=["your_google_api_key_here"])
_google_model = _get_env("GOOGLE_GEMINI_MODEL", default="gemini-2.0-flash-exp") or "gemini-2.0-flash-exp"
_litellm_proxy_api_key = _get_env("LITELLM_PROXY_API_KEY", default="changeme-litellm")
_litellm_proxy_api_base = _get_env(
    "LITELLM_PROXY_API_BASE", default="http://host.docker.internal:4000"
) or "http://host.docker.internal:4000"
_litellm_proxy_model = _get_env("LITELLM_PROXY_MODEL", default="gpt-oss:20b") or "gpt-oss:20b"
_web_agent_llm_timeout = int(os.getenv("WEB_AGENT_LLM_TIMEOUT", "1200"))

WEB_AGENT_CONFIG = {
    "max_urls": int(os.getenv("WEB_AGENT_MAX_URLS", "5")),
    "google_api_key": _google_api_key,
    "google_gemini_model": _google_model,
    "timeout": int(os.getenv("WEB_AGENT_TIMEOUT", "120")),
    "search_engine": os.getenv("WEB_SEARCH_ENGINE", "duckduckgo"),
    "min_relevance_score": int(os.getenv("WEB_MIN_RELEVANCE_SCORE", "2")),
    "enable_llm_clustering": os.getenv("WEB_ENABLE_LLM_CLUSTERING", "true").lower() == "true",
    "use_litellm_proxy": os.getenv("USE_LITELLM_PROXY", "false").lower() == "true",
    "litellm_proxy_api_key": _litellm_proxy_api_key,
    "litellm_proxy_api_base": _litellm_proxy_api_base,
    "litellm_proxy_model": _litellm_proxy_model,
    "llm_timeout": _web_agent_llm_timeout,
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
