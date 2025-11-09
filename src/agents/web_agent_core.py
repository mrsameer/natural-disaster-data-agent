"""
Google ADK Core Functions for Web-Based Disaster Data Collection

This module implements the complete Google ADK workflow for intelligent
disaster data acquisition from web sources.
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler
from duckduckgo_search import DDGS
from google import genai
from google.genai import types

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class WebAgentCoreError(Exception):
    """Base exception for web agent core errors"""

    pass


def setup_gemini_client(api_key: str) -> genai.Client:
    """Initialize Google Gemini client

    Args:
        api_key: Google API key

    Returns:
        Configured Gemini client
    """
    client = genai.Client(api_key=api_key)
    return client


def search_web_for_disaster_data(
    disaster_type: str, max_urls: int = 5, user_query: str = ""
) -> List[Dict[str, Any]]:
    """Search web for disaster-related URLs using DuckDuckGo

    Args:
        disaster_type: Type of disaster to search for
        max_urls: Maximum number of URLs to return
        user_query: Natural language query for temporal filtering

    Returns:
        List of search results with URL, title, snippet
    """
    logger.info(
        f"Searching web for {disaster_type} disasters (max_urls={max_urls})"
    )

    try:
        # Build search query with enhanced temporal and location context
        # Extract month information from date format (2025-10-01, 2025-11-30)
        import re
        month_names = {
            "10": "October", "11": "November", "09": "September",
            "08": "August", "07": "July", "06": "June"
        }

        # Try to extract months from date patterns in query
        date_pattern = r"2025-(\d{2})-"
        months_found = re.findall(date_pattern, user_query)

        if months_found:
            month_strs = [month_names.get(m, "") for m in months_found if m in month_names]
            if month_strs:
                # For cyclones, add Andhra Pradesh to get more specific results
                if disaster_type == "cyclones":
                    base_query = f"cyclone Andhra Pradesh {' '.join(set(month_strs))} 2025"
                else:
                    base_query = f"{disaster_type} India {' '.join(set(month_strs))} 2025"
            else:
                base_query = f"{disaster_type} disaster India news"
        elif "andhra pradesh" in user_query.lower():
            base_query = f"{disaster_type} Andhra Pradesh India"
        elif "october" in user_query.lower() or "november" in user_query.lower():
            base_query = f"{disaster_type} India October November 2025"
        else:
            base_query = f"{disaster_type} disaster India news"

        # Enhance with temporal context from user query
        if "past week" in user_query.lower():
            # DuckDuckGo time filter for past week
            time_filter = "w"
        elif "past month" in user_query.lower() or "past 30 days" in user_query.lower():
            time_filter = "m"
        elif "today" in user_query.lower() or "latest" in user_query.lower():
            time_filter = "d"
        else:
            time_filter = None

        # Try search with basic query first
        logger.info(f"Search query: {base_query}")

        # Perform search
        ddgs = DDGS()
        results = []

        search_params = {"max_results": max_urls * 3}  # Get extra for filtering
        if time_filter:
            search_params["timelimit"] = time_filter

        # List of trusted domains for filtering results
        trusted_domains = [
            "thehindu.com",
            "ndtv.com",
            "indianexpress.com",
            "hindustantimes.com",
            "timesofindia.indiatimes.com",
            "ndma.gov.in",
            "bbc.com",
            "reuters.com",
            "aljazeera.com",
        ]

        for result in ddgs.text(base_query, **search_params):
            if len(results) >= max_urls:
                break

            url = result.get("href") or result.get("link")
            domain = urlparse(url).netloc

            # Filter to include only results from trusted sources if possible
            # But if we don't have enough results, include others
            is_trusted = any(trusted in domain for trusted in trusted_domains)

            if is_trusted or len(results) < max_urls:
                results.append(
                    {
                        "url": url,
                        "title": result.get("title", ""),
                        "snippet": result.get("body", ""),
                        "domain": domain,
                    }
                )

        logger.info(f"Found {len(results)} URLs from search")
        return results

    except Exception as e:
        logger.error(f"Search failed: {e}")
        # Return empty list instead of failing completely
        return []


async def crawl_urls_with_ai(
    urls: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Crawl URLs and extract content using Crawl4AI

    Args:
        urls: List of URL dictionaries from search

    Returns:
        List of crawled content with URL, title, paragraphs
    """
    logger.info(f"Starting AI crawl for {len(urls)} URLs")

    crawled_results = []

    async with AsyncWebCrawler(verbose=False) as crawler:
        for idx, url_data in enumerate(urls):
            url = url_data["url"]
            logger.info(f"Crawling URL {idx + 1}/{len(urls)}: {url}")

            try:
                result = await crawler.arun(url=url)

                if result.success:
                    # Extract clean text content
                    soup = BeautifulSoup(result.html, "html.parser")

                    # Remove scripts, styles, nav, footer
                    for tag in soup(
                        ["script", "style", "nav", "footer", "header"]
                    ):
                        tag.decompose()

                    # Extract paragraphs
                    paragraphs = []
                    for p_tag in soup.find_all("p"):
                        text = p_tag.get_text(strip=True)
                        if len(text) > 50:  # Filter out short snippets
                            paragraphs.append(text)

                    if paragraphs:
                        crawled_results.append(
                            {
                                "url": url,
                                "title": url_data.get("title", ""),
                                "domain": url_data.get("domain", ""),
                                "paragraphs": paragraphs,
                                "total_paragraphs": len(paragraphs),
                            }
                        )
                        logger.info(
                            f"  ✓ Extracted {len(paragraphs)} paragraphs"
                        )
                    else:
                        logger.warning(f"  ✗ No content extracted from {url}")

                else:
                    logger.warning(f"  ✗ Failed to crawl {url}: {result.error}")

                # Rate limiting
                await asyncio.sleep(2)

            except Exception as e:
                logger.error(f"  ✗ Error crawling {url}: {e}")
                continue

    logger.info(
        f"Crawl complete: {len(crawled_results)}/{len(urls)} successful"
    )
    return crawled_results


def validate_and_extract(
    crawled_data: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Validate and structure crawled content

    Args:
        crawled_data: List of crawled content

    Returns:
        List of validated and structured content
    """
    logger.info(f"Validating {len(crawled_data)} crawled pages")

    validated = []
    for idx, data in enumerate(crawled_data):
        # Combine paragraphs with IDs for reference
        paragraphs_with_ids = [
            {"id": f"PARAGRAPH_{i}", "text": p}
            for i, p in enumerate(data["paragraphs"])
        ]

        validated.append(
            {
                "url": data["url"],
                "title": data["title"],
                "domain": data["domain"],
                "paragraphs": paragraphs_with_ids,
                "content_ids": [p["id"] for p in paragraphs_with_ids],
            }
        )

    logger.info(f"Validated {len(validated)} pages")
    return validated


def cluster_related_content_with_llm(
    validated_data: List[Dict[str, Any]],
    api_key: str,
    disaster_type: str,
    user_query: str,
) -> List[Dict[str, Any]]:
    """Use Google Gemini LLM to cluster content into discrete events

    Args:
        validated_data: List of validated content
        api_key: Google API key
        disaster_type: Type of disaster
        user_query: User's natural language query

    Returns:
        List of discrete event clusters
    """
    logger.info("Clustering content into discrete events using Gemini LLM")

    if not api_key:
        logger.warning("No API key provided, skipping LLM clustering")
        return []

    try:
        client = setup_gemini_client(api_key)

        # Prepare content for LLM
        all_content = []
        for idx, data in enumerate(validated_data):
            for para in data["paragraphs"]:
                all_content.append(
                    {
                        "url": data["url"],
                        "title": data["title"],
                        "domain": data["domain"],
                        "paragraph_id": para["id"],
                        "text": para["text"],
                    }
                )

        # Build LLM prompt
        prompt = f"""
You are an AI assistant specialized in extracting discrete disaster event information from news articles.

Task: Analyze the following news content and identify DISCRETE disaster events. Each event should be:
1. A specific incident with a clear time and location
2. Distinct from other events (not the same incident reported multiple times)
3. Related to {disaster_type} disasters in India

User Query: {user_query}

For each discrete event found, extract:
- event_type: Type of disaster (flood, earthquake, cyclone, etc.)
- event_name: Brief descriptive name
- description: 1-2 sentence summary
- start_date: Date in YYYY-MM-DD format, or "RELATIVE:today" if unclear
- primary_location: Main location affected (city/district/state)
- affected_locations: List of all locations mentioned
- deaths: Number of fatalities (0 if not mentioned)
- injured: Number injured (0 if not mentioned)
- displaced: Number displaced/evacuated (0 if not mentioned)
- severity: low/medium/high
- source_urls: List of URLs that mention this event
- content_ids: List of paragraph IDs that describe this event

News Content:
{json.dumps(all_content[:50], indent=2)}

Return a JSON array of discrete events. If no discrete events found, return empty array.
"""

        # Call Gemini API
        response = client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
            ),
        )

        # Parse response
        events_json = response.text
        events = json.loads(events_json)

        if isinstance(events, dict) and "events" in events:
            events = events["events"]

        logger.info(f"LLM extracted {len(events)} discrete events")
        return events

    except Exception as e:
        logger.error(f"LLM clustering failed: {e}")
        logger.exception("Full error:")
        return []


def generate_discrete_event_packets(
    event_clusters: List[Dict[str, Any]], disaster_type: str
) -> List[Dict[str, Any]]:
    """Generate Kafka-style packets from event clusters

    Args:
        event_clusters: List of event clusters from LLM
        disaster_type: Type of disaster

    Returns:
        List of discrete event packets
    """
    logger.info(f"Generating packets for {len(event_clusters)} events")

    packets = []
    timestamp = datetime.now().isoformat()

    for idx, event in enumerate(event_clusters):
        packet_id = (
            f"disaster_event_{datetime.now().strftime('%Y%m%d%H%M%S')}_{idx}"
        )

        # Extract impact data
        deaths = event.get("deaths", 0)
        injured = event.get("injured", 0)
        displaced = event.get("displaced", 0)
        total_affected = injured + displaced

        # Build packet
        packet = {
            "packet_id": packet_id,
            "packet_type": "discrete_disaster_event",
            "kafka_topic": "disaster-events-discrete",
            "timestamp": timestamp,
            "schema_version": "2.1",
            "event": {
                "event_id": packet_id,
                "event_type": event.get("event_type", disaster_type),
                "event_name": event.get("event_name", ""),
                "description": event.get("description", ""),
                "severity": event.get("severity", "medium"),
            },
            "temporal": {
                "start_date": event.get("start_date", "RELATIVE:today"),
                "end_date": event.get("end_date"),
                "all_dates_mentioned": [event.get("start_date", "RELATIVE:today")],
                "is_ongoing": event.get("end_date") is None,
            },
            "spatial": {
                "primary_location": event.get("primary_location", "Unknown"),
                "affected_locations": event.get("affected_locations", []),
                "num_locations": len(event.get("affected_locations", [])),
            },
            "impact": {
                "deaths": deaths,
                "injured": injured,
                "displaced": displaced,
                "total_affected": total_affected,
            },
            "source": {
                "url": event.get("source_urls", [""])[0],
                "domain": urlparse(event.get("source_urls", [""])[0]).netloc if event.get("source_urls") else "",
                "title": event.get("event_name", ""),
                "collection_timestamp": timestamp,
                "content_ids": event.get("content_ids", []),
            },
            "metadata": {
                "disaster_type": disaster_type,
                "relevance_score": 8,
                "confidence": event.get("severity", "medium"),
                "extraction_method": "llm_clustering",
            },
            "processing_instructions": {
                "priority": "high" if deaths > 10 else "normal",
                "requires_nlp": False,
                "requires_geo_coding": True,
                "requires_time_normalization": "RELATIVE:" in event.get("start_date", ""),
                "retention_days": 365,
            },
        }

        packets.append(packet)

    logger.info(f"Generated {len(packets)} event packets")
    return packets


def collect_and_process_disaster_data(
    disaster_type: str = "floods",
    max_urls: int = 3,
    user_query: str = "",
) -> Dict[str, Any]:
    """Complete end-to-end disaster data collection workflow

    Args:
        disaster_type: Type of disaster ('floods', 'droughts', 'cyclones', etc.)
        max_urls: Maximum number of URLs to crawl
        user_query: Natural language query for time filtering

    Returns:
        Dictionary with workflow results including discrete event packets
    """
    logger.info(
        f"Starting Google ADK workflow: disaster_type={disaster_type}, "
        f"max_urls={max_urls}"
    )

    try:
        # Get API key from environment
        import os

        api_key = os.getenv("GOOGLE_API_KEY")

        if not api_key:
            logger.error("GOOGLE_API_KEY not set in environment")
            return {
                "status": "error",
                "error": "GOOGLE_API_KEY not configured",
                "summary": {"urls_searched": 0, "urls_crawled": 0, "discrete_events_found": 0},
                "final_packets": [],
            }

        # Step 1: Search for URLs
        logger.info("Step 1: Web Search")
        search_results = search_web_for_disaster_data(
            disaster_type, max_urls, user_query
        )

        if not search_results:
            logger.warning("No search results found")
            return {
                "status": "success",
                "timestamp": datetime.now().isoformat(),
                "disaster_type": disaster_type,
                "workflow_steps": {
                    "1_search": {"status": "success", "urls_found": 0}
                },
                "summary": {
                    "urls_searched": 0,
                    "urls_crawled": 0,
                    "discrete_events_found": 0,
                },
                "final_packets": [],
            }

        # Step 2: Crawl URLs
        logger.info("Step 2: Crawling URLs")
        crawled_data = asyncio.run(crawl_urls_with_ai(search_results))

        if not crawled_data:
            logger.warning("No content crawled successfully")
            return {
                "status": "success",
                "timestamp": datetime.now().isoformat(),
                "disaster_type": disaster_type,
                "workflow_steps": {
                    "1_search": {"status": "success", "urls_found": len(search_results)},
                    "2_crawl": {"status": "success", "success": 0, "errors": len(search_results)},
                },
                "summary": {
                    "urls_searched": len(search_results),
                    "urls_crawled": 0,
                    "discrete_events_found": 0,
                },
                "final_packets": [],
            }

        # Step 3: Validate and structure
        logger.info("Step 3: Validating content")
        validated_data = validate_and_extract(crawled_data)

        # Step 4: Cluster with LLM
        logger.info("Step 4: LLM clustering")
        event_clusters = cluster_related_content_with_llm(
            validated_data, api_key, disaster_type, user_query
        )

        # Step 5: Generate packets
        logger.info("Step 5: Generating event packets")
        packets = generate_discrete_event_packets(event_clusters, disaster_type)

        # Build result
        result = {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "disaster_type": disaster_type,
            "workflow_steps": {
                "0_time_extraction": {
                    "status": "success",
                    "description": user_query or "default",
                },
                "1_search": {
                    "status": "success",
                    "urls_found": len(search_results),
                },
                "2_crawl": {
                    "status": "success",
                    "success": len(crawled_data),
                    "errors": len(search_results) - len(crawled_data),
                },
                "3_extraction": {
                    "status": "success",
                    "extracted": len(validated_data),
                },
                "4_kafka": {"status": "success", "packets": len(packets)},
            },
            "summary": {
                "urls_searched": len(search_results),
                "urls_filtered": len(search_results),
                "urls_crawled": len(crawled_data),
                "discrete_events_found": len(event_clusters),
                "kafka_packets": len(packets),
                "total_locations": sum(
                    p["spatial"]["num_locations"] for p in packets
                ),
            },
            "final_packets": packets,
        }

        logger.info(
            f"Workflow complete: {len(packets)} packets generated "
            f"from {len(crawled_data)} crawled URLs"
        )

        return result

    except Exception as e:
        logger.exception(f"Workflow failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
            "disaster_type": disaster_type,
            "summary": {"urls_searched": 0, "urls_crawled": 0, "discrete_events_found": 0},
            "final_packets": [],
        }