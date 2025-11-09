# Web Agent Setup Guide

## 📋 Overview

The **WebAgent** is an AI-powered data acquisition agent that complements the existing USGS and EM-DAT agents by crawling web sources for recent disaster data. It uses:

- **Google Gemini LLM** for intelligent event extraction
- **Crawl4AI** for web content crawling
- **DuckDuckGo Search** for discovering relevant URLs
- **BeautifulSoup** for structured data extraction

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      WebAgent Workflow                       │
└─────────────────────────────────────────────────────────────┘

User Query → Web Search → Crawl URLs → Extract Events → Transform → Save to DB

1. Search      : DuckDuckGo search for disaster news
2. Crawl       : Crawl4AI extracts HTML content
3. Extract     : BeautifulSoup parses structured data
4. Cluster     : Gemini LLM clusters related content into discrete events
5. Filter      : Temporal/spatial filtering
6. Transform   : Convert to staging.raw_events format
7. Save        : Insert into PostgreSQL staging table
```

## 📦 Files Created

```
src/agents/
├── web_agent.py           # Main agent (inherits from BaseAgent)
└── web_agent_core.py      # Google ADK workflow functions

src/
└── config.py              # Updated with WEB_AGENT_CONFIG

.env.example               # Updated with Web Agent vars

test_web_agent.py          # Test suite for validation
```

## 🚀 Installation & Setup

### Step 1: Install Dependencies

Add to your `pyproject.toml`:

```toml
dependencies = [
    # ... existing dependencies ...

    # Web Agent dependencies
    "google-genai>=0.2.0",      # Google Gemini LLM
    "crawl4ai>=0.3.0",          # AI-based web crawling
    "beautifulsoup4>=4.12.0",   # HTML parsing
    "duckduckgo-search>=4.0.0", # Web search
]
```

Or install directly:

```bash
pip install google-genai crawl4ai beautifulsoup4 duckduckgo-search
```

### Step 2: Get Google API Key

1. Visit: https://aistudio.google.com/app/apikey
2. Create a new API key
3. Copy the key

### Step 3: Configure Environment

Create `.env` file (or copy from `.env.example`):

```bash
# Web Agent Configuration
GOOGLE_API_KEY=your_actual_google_api_key_here
WEB_AGENT_MAX_URLS=5
WEB_AGENT_USE_MOCK=false
WEB_AGENT_TIMEOUT=120
WEB_SEARCH_ENGINE=duckduckgo
WEB_MIN_RELEVANCE_SCORE=2
WEB_ENABLE_LLM_CLUSTERING=true
```

### Step 4: Integrate Google ADK Code

**IMPORTANT**: The `web_agent_core.py` file currently contains a placeholder. You need to:

1. Open `src/agents/web_agent_core.py`
2. Replace the placeholder with your Google ADK sample code
3. Ensure the main function is named `collect_and_process_disaster_data()`

Your function should return this structure:

```python
{
    "status": "success",
    "summary": {
        "urls_searched": 10,
        "urls_crawled": 5,
        "discrete_events_found": 3
    },
    "final_packets": [
        {
            "packet_type": "discrete_disaster_event",
            "temporal": {"start_date": "2025-11-06"},
            "spatial": {"primary_location": "Kerala"},
            "impact": {"deaths": 25, "injured": 50},
            "event": {"event_type": "flood"},
            "source": {"url": "...", "title": "..."}
        }
    ]
}
```

## ✅ Testing

### Test with Mock Data (No API Key Required)

```bash
python test_web_agent.py
```

This runs 5 test cases:
1. Agent initialization
2. Mock data fetching
3. Statistics tracking
4. Packet transformation
5. Error handling

### Test with Real Web Crawling

```bash
# Small test (1-2 URLs)
python -m src.agents.web_agent --disaster-type floods --max-urls 2

# With date range
python -m src.agents.web_agent \
    --disaster-type earthquakes \
    --start-date 2025-11-01 \
    --end-date 2025-11-09 \
    --max-urls 3
```

### View Logs

```bash
tail -f logs/web_agent.log
```

## 📊 Usage Examples

### Python API

```python
from src.agents.web_agent import WebAgent

# Initialize agent
agent = WebAgent()

# Option 1: Fetch data only
records = agent.fetch_data(
    start_date="2025-11-01",
    end_date="2025-11-09",
    disaster_type="floods"
)

print(f"Fetched {len(records)} records")

# Option 2: Fetch and save to database
agent.run(
    start_date="2025-11-01",
    end_date="2025-11-09",
    disaster_type="cyclones"
)

# Get statistics
stats = agent.get_statistics()
print(f"URLs crawled: {stats['urls_crawled']}")
print(f"Events extracted: {stats['events_extracted']}")
```

### Command Line

```bash
# Search for all disasters in the past week
python -m src.agents.web_agent --disaster-type all

# Search for floods with date filter
python -m src.agents.web_agent \
    --disaster-type floods \
    --start-date 2025-11-01 \
    --end-date 2025-11-09

# Use mock data for testing
python -m src.agents.web_agent --mock --disaster-type earthquakes
```

## 🔄 Integration with Existing Pipeline

The WebAgent follows the same pattern as USGS and EM-DAT agents:

### Data Flow

```
WebAgent → staging.raw_events → ETL Pipeline → event_fact (TimescaleDB)
```

### Record Format

WebAgent transforms web data to match the standardized schema:

```python
{
    "source_event_id": "disaster_event_20251109120000_0",
    "event_time": datetime(2025, 11, 6),
    "location_text": "Kerala",
    "latitude": None,  # Geocoded by ETL
    "longitude": None,
    "disaster_type": "Flood",
    "magnitude_value": None,
    "magnitude_unit": None,
    "fatalities": 25,
    "economic_loss": None,
    "affected": 1050,  # injured + displaced
    "raw_json": {...}  # Full packet for debugging
}
```

### Deduplication

The existing ETL pipeline handles deduplication across all sources (USGS, EM-DAT, WebAgent) using:

- **Temporal window**: 48 hours
- **Spatial threshold**: 100km radius
- **Event type matching**

## 🎯 Disaster Types Supported

- `floods` - Flooding events
- `droughts` - Drought conditions
- `cyclones` - Tropical cyclones, hurricanes
- `earthquakes` - Seismic events
- `landslides` - Landslides and mudslides
- `all` - All disaster types

## ⚙️ Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `GOOGLE_API_KEY` | - | **Required** for LLM clustering |
| `WEB_AGENT_MAX_URLS` | 5 | Max URLs to crawl per query |
| `WEB_AGENT_USE_MOCK` | false | Use mock data for testing |
| `WEB_AGENT_TIMEOUT` | 120 | Timeout in seconds |
| `WEB_SEARCH_ENGINE` | duckduckgo | Search engine to use |
| `WEB_MIN_RELEVANCE_SCORE` | 2 | Min relevance for URL filtering |
| `WEB_ENABLE_LLM_CLUSTERING` | true | Enable LLM-based event extraction |

## 🐛 Troubleshooting

### Issue: "GOOGLE_API_KEY not set"

**Solution**:
```bash
export GOOGLE_API_KEY=your_key_here
# Or add to .env file
```

### Issue: "Failed to import web_agent_core"

**Solution**: Make sure you've pasted your Google ADK code into `web_agent_core.py`

### Issue: "ModuleNotFoundError: crawl4ai"

**Solution**:
```bash
pip install crawl4ai beautifulsoup4 google-genai duckduckgo-search
```

### Issue: No events extracted

**Solution**:
1. Check if URLs are being found: Look at logs
2. Try with `--mock` flag to test transformation
3. Increase `WEB_AGENT_MAX_URLS`
4. Adjust date range

### Issue: SSL or network errors

**Solution**:
1. Check internet connection
2. Try different `WEB_SEARCH_ENGINE`
3. Increase `WEB_AGENT_TIMEOUT`

## 📈 Performance Considerations

### Recommended Settings

For **development/testing**:
```bash
WEB_AGENT_MAX_URLS=2
WEB_AGENT_TIMEOUT=60
```

For **production**:
```bash
WEB_AGENT_MAX_URLS=10
WEB_AGENT_TIMEOUT=180
```

### Rate Limiting

The agent includes:
- 2-second delays between crawls
- Exponential backoff on errors (2s, 4s, 8s)
- 3 retry attempts for transient failures

### Cost Estimation

**Google Gemini API** (as of 2025):
- Flash model: ~$0.00015 per request
- For 10 URLs: ~$0.0015 per run
- Monthly (daily runs): ~$0.045/month

## 🔒 Security Best Practices

1. **Never commit API keys** to git
2. Use `.env` file (already in `.gitignore`)
3. Rotate API keys periodically
4. Use read-only database user for staging
5. Validate all web content before processing

## 🚦 Next Steps

1. ✅ Install dependencies
2. ✅ Set `GOOGLE_API_KEY` in `.env`
3. ✅ Paste your Google ADK code into `web_agent_core.py`
4. ✅ Run `python test_web_agent.py` (after installing dependencies)
5. ✅ Test with `--mock` flag
6. ✅ Test with small `--max-urls 2`
7. ✅ Run full production workflow
8. ✅ Monitor logs in `logs/web_agent.log`

## 📚 Additional Resources

- **Google ADK Docs**: https://ai.google.dev/
- **Crawl4AI**: https://github.com/unclecode/crawl4ai
- **DuckDuckGo Search**: https://github.com/deedy5/duckduckgo_search

## 🤝 Support

If you encounter issues:
1. Check logs in `logs/web_agent.log`
2. Run test suite: `python test_web_agent.py`
3. Enable debug logging: `LOG_LEVEL=DEBUG`
4. Review the troubleshooting section above
