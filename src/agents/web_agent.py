"""AI-Powered Web Data Acquisition Agent using Google ADK

This agent implements an autonomous disaster data collection system that:
- Performs seed-query-driven web search for disaster events
- Uses AI-based web crawling (Crawl4AI) for content extraction
- Leverages LLM (Google Gemini) for event clustering and extraction
- Generates discrete event packets with temporal/spatial filtering
- Transforms data to match the staging.raw_events schema

The agent complements USGS and EM-DAT by providing:
- Real-time disaster news and updates
- Diverse source coverage (news, government sites)
- Multi-location event handling
- Recent event data (past 7-30 days)
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.agents import BaseAgent
from src.config import BASE_DIR, WEB_AGENT_CONFIG


class WebAgentError(Exception):
    """Base exception for WebAgent errors"""
    pass


class WebCrawlError(WebAgentError):
    """Raised when web crawling fails"""
    pass


class DataTransformationError(WebAgentError):
    """Raised when packet transformation fails"""
    pass


class WebAgent(BaseAgent):
    """AI-powered web crawler agent using Google ADK and Gemini LLM

    This agent fetches disaster data from web sources using:
    1. DuckDuckGo search for discovering relevant URLs
    2. Crawl4AI for content extraction
    3. Google Gemini for intelligent event clustering
    4. BeautifulSoup for structured data extraction

    The workflow follows:
    Search → Crawl → Extract → Cluster → Transform → Save to Staging
    """

    def __init__(self):
        """Initialize the Web Agent with configuration"""
        super().__init__("WEB-AI-CRAWLER")

        # Configuration
        self.max_urls = WEB_AGENT_CONFIG.get("max_urls", 3)
        self.google_api_key = WEB_AGENT_CONFIG.get("google_api_key")
        self.google_model = WEB_AGENT_CONFIG.get("google_gemini_model", "gemini-2.0-flash-exp")
        self.use_litellm_proxy = WEB_AGENT_CONFIG.get("use_litellm_proxy", False)
        self.litellm_proxy_api_key = WEB_AGENT_CONFIG.get("litellm_proxy_api_key")
        self.litellm_proxy_api_base = WEB_AGENT_CONFIG.get("litellm_proxy_api_base")
        self.litellm_proxy_model = WEB_AGENT_CONFIG.get("litellm_proxy_model", "gpt-oss:20b")
        self.timeout = WEB_AGENT_CONFIG.get("timeout", 120)
        self.llm_timeout = WEB_AGENT_CONFIG.get("llm_timeout", 1200)

        self.llm_config = self._build_llm_config()

        # Statistics tracking
        self.stats = {
            "urls_searched": 0,
            "urls_crawled": 0,
            "events_extracted": 0,
            "records_saved": 0,
            "errors": 0
        }

        self.logger.info(
            f"WebAgent initialized: max_urls={self.max_urls}, timeout={self.timeout}s"
        )

    def _build_llm_config(self) -> Dict:
        """Determine which LLM backend should power clustering."""
        vertex_location = os.getenv("GOOGLE_VERTEX_LOCATION", "asia-south1")
        gemini_model_env = (os.getenv("GOOGLE_GEMINI_MODEL") or "").strip()

        gemini_candidates = []
        gemini_key_path_env = os.getenv("GEMINI_KEY_PATH")
        if gemini_key_path_env:
            gemini_candidates.append(Path(gemini_key_path_env).expanduser())
        gemini_candidates.append(Path(BASE_DIR) / "gemini-api-key.json")
        gemini_candidates.append(Path(os.getcwd()) / "gemini-api-key.json")
        gemini_key_path = next((p for p in gemini_candidates if p.exists()), None)

        if gemini_key_path:
            try:
                with gemini_key_path.open("r") as f:
                    service_account_info = json.load(f)
                self.logger.info(f"Using Gemini Vertex via service account: {gemini_key_path}")
                return {
                    "provider": "google_vertex",
                    "service_account_info": service_account_info,
                    "project_id": service_account_info.get("project_id"),
                    "location": vertex_location,
                    "model": gemini_model_env or "gemini-2.5-flash",
                    "timeout": self.llm_timeout,
                }
            except Exception as exc:
                self.logger.error(f"Failed to load gemini-api-key.json: {exc}")

        if self.google_api_key:
            self.logger.info("Using Google Gemini API key for LLM clustering")
            return {
                "provider": "google",
                "api_key": self.google_api_key,
                "model": gemini_model_env or self.google_model or "gemini-2.0-flash-exp",
                "timeout": self.llm_timeout,
            }

        if (
            self.use_litellm_proxy
            and self.litellm_proxy_api_key
            and self.litellm_proxy_api_base
        ):
            self.logger.info("Using LiteLLM proxy for LLM clustering")
            return {
                "provider": "litellm",
                "api_key": self.litellm_proxy_api_key,
                "api_base": self.litellm_proxy_api_base,
                "model": self.litellm_proxy_model,
                "timeout": self.llm_timeout,
            }

        raise ValueError(
            "No LLM credentials configured. Provide gemini-api-key.json, a GOOGLE_API_KEY, "
            "or enable LiteLLM via USE_LITELLM_PROXY + LITELLM_PROXY_* settings."
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=4, max=30),
        retry=retry_if_exception_type((WebCrawlError, ConnectionError)),
        reraise=True
    )
    def fetch_data(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        disaster_type: str = "all"
    ) -> List[Dict]:
        """Fetch disaster data from web using AI crawling with retry logic

        Args:
            start_date: Start date filter (YYYY-MM-DD format)
            end_date: End date filter (YYYY-MM-DD format)
            disaster_type: Type of disaster to search for:
                          'floods', 'droughts', 'cyclones', 'earthquakes',
                          'landslides', or 'all'

        Returns:
            List of standardized records ready for staging table insertion

        Raises:
            WebCrawlError: If web crawling fails after retries
            DataTransformationError: If packet transformation fails
        """
        self.logger.info(
            f"Starting web data acquisition for disaster_type='{disaster_type}' "
            f"from {start_date or 'N/A'} to {end_date or 'N/A'}"
        )

        # Reset statistics
        self.stats = {
            "urls_searched": 0,
            "urls_crawled": 0,
            "events_extracted": 0,
            "records_saved": 0,
            "errors": 0
        }

        try:
            # Build user query with temporal context
            user_query = self._build_user_query(start_date, end_date, disaster_type)
            self.logger.info(f"User query: '{user_query}'")

            # Execute Google ADK workflow
            result = self._execute_adk_workflow(user_query, disaster_type)

            # Validate result
            if result.get("status") != "success":
                raise WebCrawlError(
                    f"ADK workflow failed: {result.get('error', 'Unknown error')}"
                )

            # Extract statistics
            summary = result.get("summary", {})
            self.stats.update({
                "urls_searched": summary.get("urls_searched", 0),
                "urls_crawled": summary.get("urls_crawled", 0),
                "events_extracted": summary.get("discrete_events_found", 0)
            })

            self.logger.info(
                f"ADK workflow completed: {self.stats['urls_searched']} URLs searched, "
                f"{self.stats['urls_crawled']} crawled, "
                f"{self.stats['events_extracted']} events extracted"
            )

            # Transform packets to staging format
            packets = result.get("final_packets", [])
            records = self._transform_packets_to_records(packets)

            self.stats["records_saved"] = len(records)

            self.logger.success(
                f"Successfully processed {len(records)} records from web sources"
            )

            return records

        except WebCrawlError:
            self.stats["errors"] += 1
            self.logger.error("Web crawling failed after retries")
            raise

        except DataTransformationError as e:
            self.stats["errors"] += 1
            self.logger.error(f"Data transformation failed: {e}")
            raise

        except Exception as e:
            self.stats["errors"] += 1
            self.logger.exception(f"Unexpected error in fetch_data: {e}")
            raise WebAgentError(f"Agent execution failed: {str(e)}") from e

    def _build_user_query(
        self,
        start_date: Optional[str],
        end_date: Optional[str],
        disaster_type: str
    ) -> str:
        """Build natural language query for temporal filtering

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            disaster_type: Disaster type to search for

        Returns:
            Natural language query string
        """
        disaster_label = "disasters" if disaster_type == "all" else disaster_type

        # If no dates specified, default to recent news
        if not start_date and not end_date:
            return f"Find latest {disaster_label} news from India in the past week"

        # If only start date
        if start_date and not end_date:
            try:
                start_dt = datetime.strptime(start_date, "%Y-%m-%d")
                days_ago = (datetime.now() - start_dt).days

                if days_ago <= 1:
                    return f"Find {disaster_label} news from today"
                elif days_ago <= 7:
                    return f"Find {disaster_label} news from the past {days_ago} days"
                elif days_ago <= 30:
                    return f"Find {disaster_label} news from the past month"
                else:
                    return f"Find {disaster_label} news since {start_date}"
            except ValueError:
                return f"Find {disaster_label} news since {start_date}"

        # If both dates specified
        if start_date and end_date:
            return f"Find {disaster_label} news from {start_date} to {end_date}"

        # If only end date (unusual case)
        return f"Find {disaster_label} news until {end_date}"

    def _execute_adk_workflow(self, user_query: str, disaster_type: str) -> Dict:
        """Execute the Google ADK data collection workflow

        This method imports and calls the ADK workflow dynamically to avoid
        import errors when dependencies are not installed.

        Args:
            user_query: Natural language query for temporal filtering
            disaster_type: Type of disaster to search

        Returns:
            Result dictionary from ADK workflow

        Raises:
            WebCrawlError: If workflow execution fails
        """
        try:
            # Dynamic import to avoid dependency issues
            from src.agents.web_agent_core import collect_and_process_disaster_data

            self.logger.info(f"Executing ADK workflow for: {user_query}")

            # Call the main workflow function
            result = collect_and_process_disaster_data(
                disaster_type=disaster_type,
                max_urls=self.max_urls,
                user_query=user_query,
                llm_config=self.llm_config,
            )

            return result

        except ImportError as e:
            raise WebCrawlError(
                f"Failed to import web_agent_core. Ensure dependencies are installed: {e}"
            ) from e

        except Exception as e:
            raise WebCrawlError(
                f"ADK workflow execution failed: {str(e)}"
            ) from e

    def _transform_packets_to_records(self, packets: List[Dict]) -> List[Dict]:
        """Transform Kafka-style packets to staging.raw_events format

        This is the critical transformation step that maps the AI-extracted
        discrete event packets to the standardized staging schema used by
        USGS and EM-DAT agents.

        Args:
            packets: List of discrete event packets from ADK workflow

        Returns:
            List of staging.raw_events records

        Raises:
            DataTransformationError: If transformation fails
        """
        if not packets:
            self.logger.warning("No packets to transform")
            return []

        records = []
        skipped_count = 0

        for idx, packet in enumerate(packets):
            try:
                # Validate packet type
                packet_type = packet.get("packet_type")
                if packet_type != "discrete_disaster_event":
                    self.logger.debug(
                        f"Skipping packet {idx}: type={packet_type} "
                        f"(expected discrete_disaster_event)"
                    )
                    skipped_count += 1
                    continue

                # Extract nested structures
                temporal = packet.get("temporal", {})
                spatial = packet.get("spatial", {})
                impact = packet.get("impact", {})
                event = packet.get("event", {})
                source = packet.get("source", {})
                metadata = packet.get("metadata", {})

                # Parse event time
                event_time = self._parse_event_time(temporal.get("start_date"))

                if not event_time:
                    self.logger.warning(
                        f"Skipping packet {idx}: no valid event_time "
                        f"(start_date={temporal.get('start_date')})"
                    )
                    skipped_count += 1
                    continue

                # Extract location
                location_text = spatial.get("primary_location")
                if not location_text:
                    self.logger.warning(
                        f"Packet {idx} has no primary_location, "
                        f"using first affected location"
                    )
                    affected_locs = spatial.get("affected_locations", [])
                    location_text = affected_locs[0] if affected_locs else "Unknown"

                # Calculate total affected (sum of injured + displaced)
                affected = self._calculate_total_affected(impact)

                # Extract fatalities
                fatalities = impact.get("deaths")
                if fatalities == 0:
                    fatalities = None  # Store NULL instead of 0

                # Build staging record
                record = {
                    "source_event_id": packet.get("packet_id"),
                    "event_time": event_time,
                    "location_text": location_text,
                    "latitude": None,  # Will be geocoded in ETL pipeline
                    "longitude": None,
                    "disaster_type": self._normalize_disaster_type(
                        event.get("event_type", "Unknown")
                    ),
                    "magnitude_value": None,  # Rarely available in web sources
                    "magnitude_unit": None,
                    "fatalities": fatalities,
                    "economic_loss": None,  # Rarely available in news articles
                    "affected": affected,
                    "raw_json": packet  # Store full packet for debugging
                }

                records.append(record)

                self.logger.debug(
                    f"Transformed packet {idx}: {event.get('event_type')} "
                    f"at {location_text} on {event_time.date()}"
                )

            except Exception as e:
                self.logger.error(
                    f"Failed to transform packet {idx}: {e}",
                    exc_info=True
                )
                self.stats["errors"] += 1
                continue

        if skipped_count > 0:
            self.logger.info(f"Skipped {skipped_count} packets during transformation")

        if not records:
            self.logger.warning(
                "No records generated from transformation. "
                f"Processed {len(packets)} packets, all were skipped."
            )

        return records

    def _parse_event_time(self, date_string: Optional[str]) -> Optional[datetime]:
        """Parse event date string to datetime

        Handles various date formats:
        - ISO format: "2025-11-06"
        - Relative dates: "RELATIVE:today"
        - Invalid dates: returns None

        Args:
            date_string: Date string to parse

        Returns:
            Parsed datetime or None
        """
        if not date_string:
            return None

        try:
            # Handle relative dates
            if date_string.startswith("RELATIVE:"):
                relative_part = date_string.split(":", 1)[1].lower()

                if relative_part == "today":
                    return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                elif relative_part == "yesterday":
                    return (datetime.now() - timedelta(days=1)).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )
                else:
                    self.logger.warning(f"Unknown relative date: {relative_part}")
                    return datetime.now()

            # Try standard ISO format
            return datetime.strptime(date_string, "%Y-%m-%d")

        except ValueError as e:
            self.logger.debug(f"Failed to parse date '{date_string}': {e}")
            return None

    def _calculate_total_affected(self, impact: Dict) -> Optional[int]:
        """Calculate total affected population from impact data

        Args:
            impact: Impact dictionary with deaths, injured, displaced

        Returns:
            Total affected count or None if no data
        """
        injured = impact.get("injured", 0) or 0
        displaced = impact.get("displaced", 0) or 0

        total = injured + displaced
        return total if total > 0 else None

    def _normalize_disaster_type(self, disaster_type: str) -> str:
        """Normalize disaster type to match database conventions

        Converts various formats to title case and standardized names:
        - "flood" → "Flood"
        - "earthquake" → "Earthquake"
        - "tropical cyclone" → "Tropical Cyclone"

        Args:
            disaster_type: Raw disaster type string

        Returns:
            Normalized disaster type
        """
        if not disaster_type:
            return "Unknown"

        # Mapping of common variants to standard names
        type_mapping = {
            "flood": "Flood",
            "floods": "Flood",
            "flooding": "Flood",
            "earthquake": "Earthquake",
            "quake": "Earthquake",
            "cyclone": "Cyclone",
            "tropical cyclone": "Tropical Cyclone",
            "hurricane": "Tropical Cyclone",
            "typhoon": "Tropical Cyclone",
            "storm": "Storm",
            "drought": "Drought",
            "landslide": "Landslide",
            "mudslide": "Landslide",
            "tsunami": "Tsunami",
        }

        normalized = type_mapping.get(disaster_type.lower(), disaster_type.title())
        return normalized

    def run(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        disaster_type: str = "all"
    ):
        """Execute the web agent workflow with enhanced logging

        This overrides the BaseAgent.run() to add disaster_type parameter
        and enhanced statistics reporting.

        Args:
            start_date: Start date filter (YYYY-MM-DD)
            end_date: End date filter (YYYY-MM-DD)
            disaster_type: Type of disaster to search
        """
        self.logger.info(
            f"Starting {self.agent_name} agent run: "
            f"disaster_type={disaster_type}, "
            f"date_range={start_date or 'N/A'} to {end_date or 'N/A'}"
        )

        try:
            # Fetch data from web
            data = self.fetch_data(start_date, end_date, disaster_type)

            # Save to staging
            count = self.save_to_staging(data)

            # Log statistics
            self.logger.success(
                f"Agent completed successfully:\n"
                f"  URLs searched: {self.stats['urls_searched']}\n"
                f"  URLs crawled: {self.stats['urls_crawled']}\n"
                f"  Events extracted: {self.stats['events_extracted']}\n"
                f"  Records saved: {count}\n"
                f"  Errors: {self.stats['errors']}"
            )

        except Exception as e:
            self.logger.error(f"Agent failed: {e}", exc_info=True)
            raise

    def get_statistics(self) -> Dict:
        """Get agent execution statistics

        Returns:
            Dictionary with execution metrics
        """
        return self.stats.copy()


if __name__ == "__main__":
    """CLI execution for WebAgent"""
    import argparse

    # Configure logging
    logger.add(
        "logs/web_agent.log",
        rotation="100 MB",
        retention="30 days",
        level="INFO"
    )

    # Parse arguments
    parser = argparse.ArgumentParser(
        description="AI-Powered Web Disaster Data Acquisition Agent"
    )
    parser.add_argument(
        "--disaster-type",
        type=str,
        default="all",
        choices=["all", "floods", "droughts", "cyclones", "earthquakes", "landslides"],
        help="Type of disaster to search for"
    )
    parser.add_argument(
        "--start-date",
        type=str,
        help="Start date filter (YYYY-MM-DD format)"
    )
    parser.add_argument(
        "--end-date",
        type=str,
        help="End date filter (YYYY-MM-DD format)"
    )
    parser.add_argument(
        "--max-urls",
        type=int,
        help="Maximum number of URLs to crawl (overrides config)"
    )

    args = parser.parse_args()

    # Initialize agent
    agent = WebAgent()

    # Override config if specified
    if args.max_urls:
        agent.max_urls = args.max_urls

    # Run agent
    try:
        agent.run(
            start_date=args.start_date,
            end_date=args.end_date,
            disaster_type=args.disaster_type
        )
    except Exception as e:
        logger.error(f"Agent execution failed: {e}")
        exit(1)
