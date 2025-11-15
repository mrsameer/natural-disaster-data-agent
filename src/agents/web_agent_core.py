"""
Google ADK Core Functions for Web-Based Disaster Data Collection

This module implements the complete Google ADK workflow for intelligent
disaster data acquisition from web sources.
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, parse_qs, unquote

import requests
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


def _normalize_env(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if "#" in cleaned:
        hash_index = cleaned.find("#")
        if hash_index == 0:
            return None
        cleaned = cleaned[:hash_index].rstrip()
    return cleaned or None


def _load_llm_config_from_env() -> Optional[Dict[str, Any]]:
    """Build default LLM configuration from environment variables."""
    google_api_key = _normalize_env(os.getenv("GOOGLE_API_KEY"))
    timeout = int(os.getenv("WEB_AGENT_LLM_TIMEOUT", "1200"))
    if google_api_key and google_api_key.lower() != "your_google_api_key_here":
        return {
            "provider": "google",
            "api_key": google_api_key,
            "model": _normalize_env(os.getenv("GOOGLE_GEMINI_MODEL")) or "gemini-2.0-flash-exp",
            "timeout": timeout,
        }

    use_proxy = os.getenv("USE_LITELLM_PROXY", "false").lower() == "true"
    proxy_api_key = _normalize_env(os.getenv("LITELLM_PROXY_API_KEY"))
    proxy_api_base = _normalize_env(os.getenv("LITELLM_PROXY_API_BASE")) or "http://host.docker.internal:4000"
    proxy_model = _normalize_env(os.getenv("LITELLM_PROXY_MODEL")) or "gpt-oss:20b"

    if use_proxy and proxy_api_key and proxy_api_base:
        return {
            "provider": "litellm",
            "api_key": proxy_api_key,
            "api_base": proxy_api_base,
            "model": proxy_model,
            "timeout": timeout,
        }

    return None


def _clean_json_blob(text: str) -> str:
    """Strip common markdown fences around JSON payloads."""
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        for part in parts:
            chunk = part.strip()
            if not chunk:
                continue
            if chunk.lower().startswith("json"):
                return chunk[4:].strip()
            return chunk
    return cleaned


def _fallback_duckduckgo_html_search(query: str, max_urls: int) -> List[Dict[str, Any]]:
    """Simple HTML scraping fallback when DDGS API returns nothing."""
    logger.info("Falling back to DuckDuckGo HTML scraping")

    try:
        response = requests.get(
            "https://duckduckgo.com/html/",
            params={"q": query},
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; DisasterAgent/1.0)",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=20,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error(f"Fallback DuckDuckGo request failed: {exc}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    results: List[Dict[str, Any]] = []

    for result in soup.select(".result"):
        if len(results) >= max_urls:
            break

        link = result.select_one(".result__a")
        snippet_el = result.select_one(".result__snippet")
        if not link:
            continue

        href = link.get("href")
        if not href:
            continue

        # DuckDuckGo wraps outbound links through /l/?uddg=...
        if href.startswith("/l/?") or "uddg=" in href:
            parsed = parse_qs(href.split("?", 1)[-1])
            uddg = parsed.get("uddg")
            if uddg:
                href = unquote(uddg[0])

        domain = urlparse(href).netloc
        results.append(
            {
                "url": href,
                "title": link.get_text(strip=True),
                "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
                "domain": domain,
            }
        )

    logger.info(f"Fallback search produced {len(results)} URLs")
    return results


def _generate_llm_response(prompt: str, llm_config: Dict[str, Any]) -> str:
    """Call the configured LLM backend and return the raw response text."""
    provider = (llm_config or {}).get("provider")

    if provider == "google":
        client = setup_gemini_client(llm_config["api_key"], llm_config.get("timeout"))
        model = llm_config.get("model", "gemini-2.0-flash-exp")
        response = client.models.generate_content(
            model=model,
            contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
        )
        return response.candidates[0].content.parts[0].text

    if provider == "litellm":
        api_base = llm_config.get("api_base")
        api_key = llm_config.get("api_key")
        if not (api_base and api_key):
            raise ValueError("LiteLLM proxy configuration is incomplete")

        url = api_base.rstrip("/") + "/v1/chat/completions"
        payload = {
            "model": llm_config.get("model", "gpt-oss:20b"),
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an AI assistant specialized in extracting discrete "
                        "disaster events from unstructured web content. "
                        "Always respond with a valid JSON array describing the events."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        timeout = llm_config.get("timeout", 120)
        try:
            response = requests.post(
                url, headers=headers, json=payload, timeout=timeout
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"LiteLLM proxy request failed: {exc}") from exc

        data = response.json()
        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("LiteLLM proxy returned no choices")

        message = choices[0].get("message", {})
        content = message.get("content")
        if not content:
            raise RuntimeError("LiteLLM proxy response missing content")

        return content

    raise ValueError(f"Unsupported LLM provider: {provider}")


class WebAgentCoreError(Exception):
    """Base exception for web agent core errors"""

    pass


def setup_gemini_client(api_key: str, timeout: Optional[int] = None) -> genai.Client:
    """Initialize Google Gemini client

    Args:
        api_key: Google API key

    Returns:
        Configured Gemini client
    """
    client_kwargs: Dict[str, Any] = {"api_key": api_key}
    if timeout:
        client_kwargs["http_options"] = {"timeout": timeout}
    client = genai.Client(**client_kwargs)
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

        if not results:
            logger.warning("Primary DuckDuckGo search returned no results, using fallback")
            results = _fallback_duckduckgo_html_search(base_query, max_urls)

        logger.info(f"Found {len(results)} URLs from search")
        return results

    except Exception as e:
        logger.error(f"Search failed: {e}")
        # Return empty list instead of failing completely
        return _fallback_duckduckgo_html_search(base_query, max_urls)


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
    llm_config: Dict[str, Any],
    disaster_type: str,
    user_query: str,
) -> List[Dict[str, Any]]:
    """Use an LLM backend to cluster content into discrete events."""
    if not llm_config:
        logger.warning("LLM configuration missing, skipping clustering")
        return []

    provider = llm_config.get("provider", "unknown")
    logger.info(f"Clustering content into discrete events using {provider} backend")

    try:
        all_content = []
        for data in validated_data:
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

        raw_text = _generate_llm_response(prompt, llm_config)
        cleaned = _clean_json_blob(raw_text)
        events = json.loads(cleaned or "[]")

        if isinstance(events, dict) and "events" in events:
            events = events["events"]

        logger.info(f"LLM extracted {len(events)} discrete events")
        return events

    except json.JSONDecodeError as exc:
        logger.error(f"Failed to decode LLM output as JSON: {exc}")
        return []
    except Exception as exc:
        logger.error(f"LLM clustering failed: {exc}")
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
    llm_config: Optional[Dict[str, Any]] = None,
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
        # Resolve LLM configuration if not provided
        llm_config = llm_config or _load_llm_config_from_env()
        if not llm_config:
            logger.error("No LLM configuration available for clustering")
            return {
                "status": "error",
                "error": "LLM backend not configured (set GOOGLE_API_KEY or LiteLLM proxy vars)",
                "summary": {
                    "urls_searched": 0,
                    "urls_crawled": 0,
                    "discrete_events_found": 0,
                },
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
            validated_data, llm_config, disaster_type, user_query
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
