# Natural Disaster Data Agent Platform

A comprehensive, federated data pipeline and analysis platform for acquiring, processing, and visualizing global natural disaster data (2010-present).

## 🌟 Architecture Overview

This system implements a **Star Schema** data warehouse with:
- **TimescaleDB** for time-series optimization
- **PostGIS** for geospatial analysis
- **Federated data acquisition agents** (USGS, EM-DAT, NOAA, etc.)
- **ETL pipeline** with geocoding and deduplication
- **Interactive Plotly Dash dashboards**

## 🚀 Quick Start

### Prerequisites

- Docker & Docker Compose (for containerized deployment)
- Python 3.11+ with UV (for local development)
- PostgreSQL 16+ with TimescaleDB and PostGIS (if running natively)

### Option 1: Docker Deployment (Recommended)

```bash
# Clone the repository
git clone <repository-url>
cd natural-disaster-data-agent

# Copy environment configuration
cp .env.example .env

# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Access dashboard at http://localhost:8050
```

### Option 2: Local Development with UV

```bash
# Install dependencies using UV
uv pip install -e .

# Set up PostgreSQL with TimescaleDB and PostGIS
# (See Database Setup section below)

# Configure environment
cp .env.example .env
# Edit .env with your database credentials

# Run agents individually
python -m src.agents.usgs_agent
python -m src.agents.emdat_agent

# Run ETL pipeline
python -m src.etl.pipeline

# Start dashboard
python -m src.dashboard.app
```

## 📊 Database Setup

### Using Docker (Automatic)

The `docker-compose.yml` handles database initialization automatically.

### Manual Setup

```sql
-- Install extensions
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
CREATE EXTENSION IF NOT EXISTS postgis;

-- Run initialization scripts
\i src/database/init.sql
\i src/database/schema.sql
```

## 🔧 Configuration

Edit `.env` file to configure:

```bash
# Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME=disaster_data
DB_USER=disaster_user
DB_PASSWORD=disaster_pass

# Data Sources
USGS_START_DATE=2010-01-01

# ETL
BATCH_SIZE=1000
MAX_WORKERS=4

# Dashboard
DASH_PORT=8050
```

## 📡 Data Acquisition Agents

### Agent 1: USGS Earthquakes
- **Source**: USGS FDSN Event Web Service
- **Data**: Global earthquakes with PAGER loss estimates
- **Run**: `python -m src.agents.usgs_agent`

### Agent 2: EM-DAT via HDX
- **Source**: Humanitarian Data Exchange (HDX)
- **Data**: Major disasters (10+ fatalities or 100+ affected)
- **Run**: `python -m src.agents.emdat_agent`

## 🔄 ETL Pipeline

The ETL pipeline performs:
1. **Economic loss parsing**: "10.5M" → 10,500,000 USD
2. **Geocoding**: Text locations → coordinates (using Nominatim)
3. **Classification**: Disaster type hierarchy
4. **Deduplication**: Geospatial-temporal matching

**Run**: `python -m src.etl.pipeline`

## 📈 Dashboard

Access the interactive dashboard at `http://localhost:8050`

Features:
- **Time-series analysis** using TimescaleDB's time_bucket
- **KPI cards**: Total events, fatalities, economic losses
- **Stacked bar charts**: Event frequency by disaster group
- **Dual-axis charts**: Fatalities vs. economic impact
- **Recent events table**: Latest master events

## 🏗️ Database Schema

### Star Schema Design

**Fact Table:**
- `event_fact` (TimescaleDB hypertable on `event_time`)

**Dimension Tables:**
- `location_dim` (PostGIS geography type)
- `event_type_dim` (Disaster classification hierarchy)
- `magnitude_dim` (Heterogeneous magnitude storage)
- `source_audit_dim` (Data lineage and traceability)

**Key View:**
- `v_master_events` (Deduplicated events with full context)

## 🧪 Testing the System

```bash
# 1. Check database connection
python -c "from src.database import test_connection; test_connection()"

# 2. Run USGS agent (fetch last 30 days)
python -m src.agents.usgs_agent

# 3. Run ETL pipeline
python -m src.etl.pipeline

# 4. Query data
psql -h localhost -U disaster_user -d disaster_data -c "SELECT COUNT(*) FROM event_fact;"

# 5. Start dashboard
python -m src.dashboard.app
```

## 📦 Project Structure

```
natural-disaster-data-agent/
├── src/
│   ├── agents/              # Data acquisition agents
│   │   ├── usgs_agent.py
│   │   ├── emdat_agent.py
│   │   └── ...
│   ├── etl/                 # ETL pipeline
│   │   ├── pipeline.py
│   │   └── transformations.py
│   ├── dashboard/           # Plotly Dash dashboards
│   │   └── app.py
│   ├── database/            # Database schemas
│   │   ├── init.sql
│   │   └── schema.sql
│   └── config.py            # Configuration management
├── data/                    # Data storage
│   ├── raw/
│   ├── staging/
│   └── processed/
├── logs/                    # Application logs
├── docker-compose.yml       # Docker orchestration
├── Dockerfile              # Container definition
├── pyproject.toml          # UV/Python dependencies
└── README.md
```

## 🔐 Security Notes

- Never commit `.env` file to version control
- Use strong database passwords in production
- Rate-limit API requests to respect data source policies
- Implement authentication for production dashboards

## 📝 License

Open-source (adjust as needed)

## 🤝 Contributing

Contributions welcome! Please follow:
1. Fork the repository
2. Create a feature branch
3. Add tests
4. Submit a pull request

## 📧 Support

For issues and questions, please open a GitHub issue.

---

**Built with**: Python 3.11, UV, PostgreSQL, TimescaleDB, PostGIS, Plotly Dash, Docker
