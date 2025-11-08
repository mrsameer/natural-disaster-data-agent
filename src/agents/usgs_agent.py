"""USGS Earthquake Data Acquisition Agent

This agent fetches earthquake data from the USGS FDSN Event Web Service API,
including PAGER loss estimates when available.
"""

import requests
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from tenacity import retry, stop_after_attempt, wait_exponential
from loguru import logger

from src.agents import BaseAgent
from src.config import USGS_CONFIG


class USGSAgent(BaseAgent):
    """Agent for acquiring USGS earthquake data with PAGER loss estimates"""

    def __init__(self):
        super().__init__("USGS-EARTHQUAKE")
        self.base_url = USGS_CONFIG["base_url"]
        self.timeout = USGS_CONFIG["timeout"]
        self.session = requests.Session()

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=2, min=2, max=16),
        reraise=True
    )
    def _make_request(self, url: str, params: Optional[Dict] = None) -> Dict:
        """Make HTTP request with retry logic"""
        response = self.session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def _fetch_pager_losses(self, event_detail_url: str) -> Optional[Dict]:
        """Fetch PAGER loss estimates for an event"""
        try:
            # Get event detail
            event_detail = self._make_request(event_detail_url)

            # Check if losspager product exists
            products = event_detail.get("properties", {}).get("products", {})
            losspager = products.get("losspager", [])

            if not losspager:
                return None

            # Get the most recent PAGER product
            pager_product = losspager[0]
            contents = pager_product.get("contents", {})

            # Look for json/losses.json
            if "json/losses.json" in contents:
                losses_url = contents["json/losses.json"]["url"]
                losses_data = self._make_request(losses_url)
                return losses_data

            return None

        except Exception as e:
            self.logger.debug(f"Failed to fetch PAGER data: {e}")
            return None

    def fetch_data(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> List[Dict]:
        """Fetch earthquake data from USGS"""

        if not start_date:
            start_date = USGS_CONFIG["start_date"]
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")

        self.logger.info(f"Fetching USGS data from {start_date} to {end_date}")

        # Build query parameters
        params = {
            "format": "geojson",
            "starttime": start_date,
            "endtime": end_date,
            "minmagnitude": 4.0,  # Only significant earthquakes
            "orderby": "time"
        }

        # Fetch earthquake data
        query_url = f"{self.base_url}/query"
        data = self._make_request(query_url, params)

        features = data.get("features", [])
        self.logger.info(f"Fetched {len(features)} earthquakes")

        records = []
        for feature in features:
            try:
                props = feature.get("properties", {})
                geom = feature.get("geometry", {})
                coords = geom.get("coordinates", [None, None, None])

                # Basic event data
                event_id = feature.get("id")
                magnitude = props.get("mag")
                event_time = None
                if props.get("time"):
                    event_time = datetime.fromtimestamp(props["time"] / 1000.0)

                # Location
                location = props.get("place", "")
                longitude = coords[0]
                latitude = coords[1]

                # Initialize fatalities and economic loss
                fatalities = None
                economic_loss = None

                # Try to fetch PAGER data
                detail_url = props.get("detail")
                if detail_url:
                    pager_data = self._fetch_pager_losses(detail_url)
                    if pager_data:
                        # Extract fatalities
                        fatalities_data = pager_data.get("fatalities", {})
                        if fatalities_data:
                            # Use the "estimated" fatalities value
                            fatalities = fatalities_data.get("estimated")

                        # Extract economic losses
                        econ_data = pager_data.get("economic", {})
                        if econ_data:
                            # Use the "estimated" economic loss (in USD millions)
                            econ_loss_millions = econ_data.get("estimated")
                            if econ_loss_millions:
                                economic_loss = f"{econ_loss_millions}M"

                # Create record
                record = {
                    "source_event_id": event_id,
                    "event_time": event_time,
                    "location_text": location,
                    "latitude": latitude,
                    "longitude": longitude,
                    "disaster_type": "Earthquake",
                    "magnitude_value": magnitude,
                    "magnitude_unit": "Richter",
                    "fatalities": fatalities,
                    "economic_loss": economic_loss,
                    "affected": None,
                    "raw_json": feature
                }

                records.append(record)

            except Exception as e:
                self.logger.error(f"Failed to parse earthquake {feature.get('id')}: {e}")
                continue

        return records


if __name__ == "__main__":
    # Configure logging
    logger.add("logs/usgs_agent.log", rotation="100 MB", retention="30 days")

    agent = USGSAgent()
    agent.run()
