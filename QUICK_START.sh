#!/bin/bash
# Natural Disaster Data Agent - Quick Start Script

echo "🌍 Natural Disaster Data Agent - System Status"
echo "=============================================="
echo ""

# Check PostgreSQL
if systemctl is-active --quiet postgresql 2>/dev/null || pgrep postgres > /dev/null; then
    echo "✅ PostgreSQL: RUNNING"
else
    echo "⚠️  PostgreSQL: STOPPED - Run: service postgresql start"
fi

# Check database
DB_COUNT=$(psql -h localhost -U disaster_user -d disaster_data -t -c "SELECT COUNT(*) FROM event_fact;" 2>/dev/null)
if [ $? -eq 0 ]; then
    echo "✅ Database: CONNECTED (${DB_COUNT} events loaded)"
else
    echo "❌ Database: CONNECTION FAILED"
fi

# Check dashboard
if pgrep -f "src.dashboard.app" > /dev/null; then
    echo "✅ Dashboard: RUNNING at http://localhost:8050"
else
    echo "⚠️  Dashboard: STOPPED - Run: python -m src.dashboard.app &"
fi

echo ""
echo "📊 Quick Commands:"
echo "===================="
echo "# View data in database:"
echo "psql -h localhost -U disaster_user -d disaster_data -c 'SELECT * FROM v_master_events LIMIT 5;'"
echo ""
echo "# Run USGS agent (last 7 days):"
echo "python -c \"from datetime import datetime, timedelta; from src.agents.usgs_agent import USGSAgent; agent = USGSAgent(); agent.run((datetime.now()-timedelta(7)).strftime('%Y-%m-%d'), datetime.now().strftime('%Y-%m-%d'))\""
echo ""
echo "# Run ETL pipeline:"
echo "python -m src.etl.pipeline"
echo ""
echo "# Start dashboard:"
echo "python -m src.dashboard.app &"
echo ""
echo "# Access dashboard:"
echo "Open browser to: http://localhost:8050"
echo ""
echo "📁 Project location: /home/user/natural-disaster-data-agent"
echo "📖 Documentation: README.md | SYSTEM_STATUS.md"
echo ""
