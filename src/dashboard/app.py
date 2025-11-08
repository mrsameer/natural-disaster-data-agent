"""Main Dashboard Application - Global Time-Series Monitor

This dashboard provides a strategic, analytical view of global natural disasters
with time-series-first optimization using TimescaleDB.
"""

import dash
from dash import dcc, html, dash_table, Input, Output, State
import dash_bootstrap_components as dbc
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import pandas as pd
from loguru import logger

from src.database import engine
from src.config import DASHBOARD_CONFIG


# Initialize Dash app with Bootstrap theme
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True
)

app.title = "Natural Disaster Data Platform"


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def fetch_kpi_data(start_date=None, end_date=None):
    """Fetch KPI metrics"""
    where_clause = ""
    if start_date and end_date:
        where_clause = f"WHERE event_time BETWEEN '{start_date}' AND '{end_date}'"

    query = f"""
        SELECT
            COUNT(*) as total_events,
            COALESCE(SUM(fatalities_total), 0) as total_fatalities,
            COALESCE(SUM(economic_loss_usd), 0) as total_economic_loss,
            COALESCE(SUM(affected_total), 0) as total_affected
        FROM event_fact
        {where_clause}
        AND is_master_event = true
    """

    df = pd.read_sql(query, engine)
    return df.iloc[0].to_dict()


def fetch_time_series_data(start_date=None, end_date=None, disaster_group=None):
    """Fetch time-series data using TimescaleDB's time_bucket"""
    where_clauses = ["e.is_master_event = true"]

    if start_date and end_date:
        where_clauses.append(f"e.event_time BETWEEN '{start_date}' AND '{end_date}'")

    if disaster_group and disaster_group != "All":
        where_clauses.append(f"et.disaster_group = '{disaster_group}'")

    where_clause = " AND ".join(where_clauses)

    query = f"""
        SELECT
            time_bucket('1 month', e.event_time) as time_bucket,
            et.disaster_group,
            COUNT(*) as event_count,
            COALESCE(SUM(e.fatalities_total), 0) as total_fatalities,
            COALESCE(SUM(e.economic_loss_usd), 0) as total_economic_loss
        FROM event_fact e
        LEFT JOIN event_type_dim et ON e.event_type_id = et.event_type_id
        WHERE {where_clause}
        GROUP BY time_bucket, et.disaster_group
        ORDER BY time_bucket
    """

    df = pd.read_sql(query, engine)
    return df


def fetch_recent_events(limit=10):
    """Fetch recent master events"""
    query = f"""
        SELECT
            event_time,
            disaster_group,
            disaster_type,
            location_name,
            country_iso3,
            fatalities_total,
            economic_loss_usd
        FROM v_master_events
        ORDER BY event_time DESC
        LIMIT {limit}
    """

    df = pd.read_sql(query, engine)
    return df


def fetch_disaster_groups():
    """Fetch available disaster groups"""
    query = "SELECT DISTINCT disaster_group FROM event_type_dim ORDER BY disaster_group"
    df = pd.read_sql(query, engine)
    return ["All"] + df["disaster_group"].tolist()


# ============================================================================
# DASHBOARD LAYOUT
# ============================================================================

def create_kpi_card(title, value, icon="📊"):
    """Create a KPI card component"""
    return dbc.Card(
        dbc.CardBody([
            html.H6(title, className="text-muted mb-2"),
            html.H3(f"{icon} {value:,.0f}" if isinstance(value, (int, float)) else f"{icon} {value}"),
        ]),
        className="mb-3 shadow-sm"
    )


# Main layout
app.layout = dbc.Container([
    # Header
    dbc.Row([
        dbc.Col([
            html.H1("🌍 Global Natural Disaster Monitor", className="text-primary mb-0"),
            html.P("Time-Series Analysis Platform (2010-Present)", className="text-muted"),
        ], width=8),
        dbc.Col([
            html.Div([
                html.Small("Last Updated:", className="text-muted d-block"),
                html.Strong(datetime.now().strftime("%Y-%m-%d %H:%M UTC")),
            ], className="text-end mt-3")
        ], width=4),
    ], className="mb-4 mt-3"),

    html.Hr(),

    # Filters Row
    dbc.Row([
        dbc.Col([
            html.Label("Date Range:", className="fw-bold"),
            dcc.DatePickerRange(
                id='date-range-picker',
                start_date=(datetime.now() - timedelta(days=365*5)).date(),
                end_date=datetime.now().date(),
                display_format='YYYY-MM-DD',
                className="mb-2"
            ),
        ], width=6),
        dbc.Col([
            html.Label("Disaster Group:", className="fw-bold"),
            dcc.Dropdown(
                id='disaster-group-dropdown',
                options=[],  # Will be populated by callback
                value="All",
                clearable=False,
                className="mb-2"
            ),
        ], width=6),
    ], className="mb-4"),

    # KPI Cards Row
    html.Div(id="kpi-cards", className="mb-4"),

    # Main Charts Row
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader(html.H5("📈 Event Frequency by Disaster Group")),
                dbc.CardBody([
                    dcc.Graph(id='event-frequency-chart', config={'displayModeBar': False})
                ])
            ], className="shadow-sm")
        ], width=6),
        dbc.Col([
            dbc.Card([
                dbc.CardHeader(html.H5("💀 Impact Over Time")),
                dbc.CardBody([
                    dcc.Graph(id='impact-chart', config={'displayModeBar': False})
                ])
            ], className="shadow-sm")
        ], width=6),
    ], className="mb-4"),

    # Recent Events Table
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader(html.H5("🔔 Recent Master Events")),
                dbc.CardBody([
                    html.Div(id='recent-events-table')
                ])
            ], className="shadow-sm")
        ])
    ]),

    # Auto-refresh interval (every 5 minutes)
    dcc.Interval(id='interval-component', interval=5*60*1000, n_intervals=0),

], fluid=True)


# ============================================================================
# CALLBACKS
# ============================================================================

@app.callback(
    Output('disaster-group-dropdown', 'options'),
    Input('interval-component', 'n_intervals')
)
def update_disaster_groups(n):
    """Update disaster group dropdown options"""
    try:
        groups = fetch_disaster_groups()
        return [{'label': g, 'value': g} for g in groups]
    except Exception as e:
        logger.error(f"Failed to fetch disaster groups: {e}")
        return [{'label': 'All', 'value': 'All'}]


@app.callback(
    Output('kpi-cards', 'children'),
    [Input('date-range-picker', 'start_date'),
     Input('date-range-picker', 'end_date'),
     Input('interval-component', 'n_intervals')]
)
def update_kpis(start_date, end_date, n):
    """Update KPI cards"""
    try:
        kpis = fetch_kpi_data(start_date, end_date)

        return dbc.Row([
            dbc.Col(create_kpi_card("Total Events", kpis['total_events'], "🌪️"), width=3),
            dbc.Col(create_kpi_card("Total Fatalities", kpis['total_fatalities'], "💀"), width=3),
            dbc.Col(create_kpi_card("Total Affected", kpis['total_affected'], "👥"), width=3),
            dbc.Col(create_kpi_card(
                "Economic Loss",
                f"${kpis['total_economic_loss']/1e9:.1f}B" if kpis['total_economic_loss'] > 0 else "$0",
                "💰"
            ), width=3),
        ])
    except Exception as e:
        logger.error(f"Failed to update KPIs: {e}")
        return html.Div("Error loading KPIs", className="text-danger")


@app.callback(
    Output('event-frequency-chart', 'figure'),
    [Input('date-range-picker', 'start_date'),
     Input('date-range-picker', 'end_date'),
     Input('disaster-group-dropdown', 'value'),
     Input('interval-component', 'n_intervals')]
)
def update_frequency_chart(start_date, end_date, disaster_group, n):
    """Update event frequency stacked bar chart"""
    try:
        df = fetch_time_series_data(start_date, end_date, disaster_group)

        if df.empty:
            return go.Figure().add_annotation(text="No data available", showarrow=False)

        fig = px.bar(
            df,
            x='time_bucket',
            y='event_count',
            color='disaster_group',
            title='',
            labels={'time_bucket': 'Date', 'event_count': 'Number of Events'},
            color_discrete_sequence=px.colors.qualitative.Set2
        )

        fig.update_layout(
            hovermode='x unified',
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=20, r=20, t=40, b=20),
            height=400
        )

        return fig

    except Exception as e:
        logger.error(f"Failed to update frequency chart: {e}")
        return go.Figure().add_annotation(text=f"Error: {str(e)}", showarrow=False)


@app.callback(
    Output('impact-chart', 'figure'),
    [Input('date-range-picker', 'start_date'),
     Input('date-range-picker', 'end_date'),
     Input('disaster-group-dropdown', 'value'),
     Input('interval-component', 'n_intervals')]
)
def update_impact_chart(start_date, end_date, disaster_group, n):
    """Update impact dual-axis line chart"""
    try:
        df = fetch_time_series_data(start_date, end_date, disaster_group)

        if df.empty:
            return go.Figure().add_annotation(text="No data available", showarrow=False)

        # Aggregate by time bucket
        df_agg = df.groupby('time_bucket').agg({
            'total_fatalities': 'sum',
            'total_economic_loss': 'sum'
        }).reset_index()

        fig = go.Figure()

        # Fatalities line
        fig.add_trace(go.Scatter(
            x=df_agg['time_bucket'],
            y=df_agg['total_fatalities'],
            name='Fatalities',
            line=dict(color='red', width=2),
            yaxis='y'
        ))

        # Economic loss line
        fig.add_trace(go.Scatter(
            x=df_agg['time_bucket'],
            y=df_agg['total_economic_loss'] / 1e9,  # Convert to billions
            name='Economic Loss ($B)',
            line=dict(color='green', width=2),
            yaxis='y2'
        ))

        fig.update_layout(
            hovermode='x unified',
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=20, r=20, t=40, b=20),
            height=400,
            yaxis=dict(title='Fatalities', side='left'),
            yaxis2=dict(title='Economic Loss ($B)', side='right', overlaying='y'),
        )

        return fig

    except Exception as e:
        logger.error(f"Failed to update impact chart: {e}")
        return go.Figure().add_annotation(text=f"Error: {str(e)}", showarrow=False)


@app.callback(
    Output('recent-events-table', 'children'),
    Input('interval-component', 'n_intervals')
)
def update_recent_events(n):
    """Update recent events table"""
    try:
        df = fetch_recent_events(limit=20)

        if df.empty:
            return html.P("No recent events found", className="text-muted")

        # Format columns
        if 'event_time' in df.columns:
            df['event_time'] = pd.to_datetime(df['event_time']).dt.strftime('%Y-%m-%d %H:%M')

        if 'economic_loss_usd' in df.columns:
            df['economic_loss_usd'] = df['economic_loss_usd'].apply(
                lambda x: f"${x/1e6:.1f}M" if pd.notna(x) and x > 0 else "-"
            )

        table = dash_table.DataTable(
            data=df.to_dict('records'),
            columns=[{"name": i.replace('_', ' ').title(), "id": i} for i in df.columns],
            style_table={'overflowX': 'auto'},
            style_cell={
                'textAlign': 'left',
                'padding': '10px',
                'fontSize': '14px'
            },
            style_header={
                'backgroundColor': 'rgb(230, 230, 230)',
                'fontWeight': 'bold'
            },
            style_data_conditional=[
                {
                    'if': {'row_index': 'odd'},
                    'backgroundColor': 'rgb(248, 248, 248)'
                }
            ],
            page_size=10
        )

        return table

    except Exception as e:
        logger.error(f"Failed to update recent events: {e}")
        return html.Div(f"Error loading events: {str(e)}", className="text-danger")


# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    logger.add("logs/dashboard.log", rotation="100 MB", retention="30 days")
    logger.info("Starting dashboard application")

    app.run(
        host=DASHBOARD_CONFIG["host"],
        port=DASHBOARD_CONFIG["port"],
        debug=DASHBOARD_CONFIG["debug"]
    )
