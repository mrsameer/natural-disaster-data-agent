"""FastAPI service wrapper around the AI-powered web agent.

The service exposes a simple REST endpoint that triggers the existing
`WebAgent` workflow. When the `/scrape` endpoint is hit, the agent
searches and crawls the web for the requested topic, optionally saving
the discovered events to the staging schema.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, validator
from loguru import logger

from src.agents.web_agent import WebAgent, WebAgentError


app = FastAPI(
    title="Web Agent Scraper",
    description="Trigger the AI-powered web agent via a simple HTTP API.",
    version="1.0.0",
)


class ScrapeRequest(BaseModel):
    topic: str = Field(..., description="Disaster topic / search focus", min_length=2)
    start_date: Optional[str] = Field(
        None, description="Start date filter in YYYY-MM-DD format"
    )
    end_date: Optional[str] = Field(
        None, description="End date filter in YYYY-MM-DD format"
    )
    save_to_db: bool = Field(
        False,
        description="Persist discovered events into staging.raw_events",
    )

    @validator("start_date", "end_date")
    def validate_dates(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:  # pragma: no cover - defensive
            raise ValueError("Dates must be in YYYY-MM-DD format") from exc
        return value

    @validator("end_date")
    def validate_range(cls, value: Optional[str], values: Dict[str, Any]) -> Optional[str]:
        start_date = values.get("start_date")
        if value and start_date:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(value, "%Y-%m-%d")
            if end_dt < start_dt:
                raise ValueError("end_date must be greater than or equal to start_date")
        return value


def _serialize_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure records contain JSON-serializable data."""

    def convert(value: Any) -> Any:
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, dict):
            return {k: convert(v) for k, v in value.items()}
        if isinstance(value, list):
            return [convert(v) for v in value]
        return value

    return {key: convert(val) for key, val in record.items()}


async def _run_agent(payload: ScrapeRequest) -> Dict[str, Any]:
    """Execute the WebAgent workflow in a worker thread."""

    def run_sync() -> Dict[str, Any]:
        agent = WebAgent()
        topic = payload.topic or "all"

        records = agent.fetch_data(
            start_date=payload.start_date,
            end_date=payload.end_date,
            disaster_type=topic,
        )

        saved = agent.save_to_staging(records) if payload.save_to_db else 0

        return {
            "topic": topic,
            "records_found": len(records),
            "records_saved": saved,
            "stats": agent.stats,
            "records": [_serialize_record(record) for record in records],
        }

    return await run_in_threadpool(run_sync)


@app.get("/health")
async def health() -> Dict[str, str]:
    """Basic health check endpoint."""
    return {"status": "ok"}


@app.post("/scrape")
async def scrape(request: ScrapeRequest) -> Dict[str, Any]:
    """Trigger the scraping workflow for a requested topic."""
    try:
        result = await _run_agent(request)
        message = (
            f"Scrape completed for '{result['topic']}'. "
            f"Found {result['records_found']} records."
        )
        return {"message": message, **result}
    except ValueError as exc:
        logger.exception("Invalid request payload: {}", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except WebAgentError as exc:
        logger.exception("Web agent failed: {}", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Unexpected server error: {}", exc)
        raise HTTPException(status_code=500, detail="Internal server error") from exc
