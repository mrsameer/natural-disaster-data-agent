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

    def _fetch_date_range(
        self, start_date: str, end_date: str, min_magnitude: float = 4.0
    ) -> List[Dict]:
        """Fetch earthquakes for a specific date range"""
        params = {
            "format": "geojson",
            "starttime": start_date,
            "endtime": end_date,
            "minmagnitude": min_magnitude,
            "orderby": "time",
        }

        query_url = f"{self.base_url}/query"
        data = self._make_request(query_url, params)
        return data.get("features", [])

    def fetch_data(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict]:
        """Fetch earthquake data from USGS with automatic pagination

        USGS API has a limit of 20,000 events per query. This method
        automatically chunks large date ranges into smaller requests.
        """

        if not start_date:
            start_date = USGS_CONFIG["start_date"]
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")

        self.logger.info(f"Fetching USGS data from {start_date} to {end_date}")

        # Parse dates
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        # Calculate number of days
        total_days = (end_dt - start_dt).days

        # If date range is small (< 1 year), fetch directly
        if total_days <= 365:
            try:
                features = self._fetch_date_range(start_date, end_date)
                self.logger.info(f"Fetched {len(features)} earthquakes")
            except Exception as e:
                # If still too many, split into smaller chunks
                if "exceeds search limit" in str(e).lower() or "400" in str(e):
                    self.logger.warning(
                        f"Too many events in range, splitting into 6-month chunks"
                    )
                    features = []
                    chunk_size = 180  # 6 months
                    current_dt = start_dt

                    while current_dt < end_dt:
                        chunk_end = min(
                            current_dt + timedelta(days=chunk_size), end_dt
                        )
                        chunk_start_str = current_dt.strftime("%Y-%m-%d")
                        chunk_end_str = chunk_end.strftime("%Y-%m-%d")

                        self.logger.info(
                            f"Fetching chunk: {chunk_start_str} to {chunk_end_str}"
                        )
                        chunk_features = self._fetch_date_range(
                            chunk_start_str, chunk_end_str
                        )
                        features.extend(chunk_features)
                        self.logger.info(
                            f"Fetched {len(chunk_features)} earthquakes "
                            f"from chunk ({len(features)} total so far)"
                        )

                        current_dt = chunk_end + timedelta(days=1)
                else:
                    raise
        else:
            # Split into yearly chunks for large date ranges
            self.logger.info(
                f"Large date range ({total_days} days), "
                f"splitting into yearly chunks"
            )
            features = []
            current_dt = start_dt

            while current_dt < end_dt:
                # Chunk by year
                chunk_end = min(
                    datetime(current_dt.year + 1, 1, 1) - timedelta(days=1), end_dt
                )
                chunk_start_str = current_dt.strftime("%Y-%m-%d")
                chunk_end_str = chunk_end.strftime("%Y-%m-%d")

                self.logger.info(
                    f"Fetching chunk: {chunk_start_str} to {chunk_end_str}"
                )
                try:
                    chunk_features = self._fetch_date_range(
                        chunk_start_str, chunk_end_str
                    )
                    features.extend(chunk_features)
                    self.logger.info(
                        f"Fetched {len(chunk_features)} earthquakes "
                        f"from chunk ({len(features)} total so far)"
                    )
                except Exception as e:
                    # If a year still has too many events, split into months
                    if "exceeds search limit" in str(e).lower() or "400" in str(e):
                        self.logger.warning(
                            f"Year {current_dt.year} has too many events, "
                            f"splitting into monthly chunks"
                        )
                        month_dt = current_dt
                        year_end = chunk_end

                        while month_dt <= year_end:
                            # Calculate month end
                            if month_dt.month == 12:
                                month_end = datetime(month_dt.year + 1, 1, 1) - timedelta(
                                    days=1
                                )
                            else:
                                month_end = datetime(
                                    month_dt.year, month_dt.month + 1, 1
                                ) - timedelta(days=1)

                            month_end = min(month_end, year_end)

                            month_start_str = month_dt.strftime("%Y-%m-%d")
                            month_end_str = month_end.strftime("%Y-%m-%d")

                            self.logger.info(
                                f"Fetching monthly chunk: "
                                f"{month_start_str} to {month_end_str}"
                            )
                            month_features = self._fetch_date_range(
                                month_start_str, month_end_str
                            )
                            features.extend(month_features)
                            self.logger.info(
                                f"Fetched {len(month_features)} earthquakes "
                                f"from month ({len(features)} total so far)"
                            )

                            # Move to next month
                            month_dt = month_end + timedelta(days=1)
                    else:
                        raise

                # Move to next year
                current_dt = datetime(current_dt.year + 1, 1, 1)

        self.logger.info(f"Total earthquakes fetched: {len(features)}")

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
