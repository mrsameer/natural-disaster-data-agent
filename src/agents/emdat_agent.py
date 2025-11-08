"""EM-DAT Data Acquisition Agent via HDX Platform

This agent fetches disaster data from the EM-DAT database using the
Humanitarian Data Exchange (HDX) Python API.
"""

from typing import Dict, List, Optional
from datetime import datetime
from hdx.api.configuration import Configuration
from hdx.data.dataset import Dataset
from loguru import logger
import pandas as pd
import tempfile
from pathlib import Path

from src.agents import BaseAgent
from src.config import HDX_CONFIG


class EMDATAgent(BaseAgent):
    """Agent for acquiring EM-DAT disaster data via HDX"""

    def __init__(self):
        super().__init__("EM-DAT-HDX")
        self.dataset_name = HDX_CONFIG["dataset_name"]
        self.hdx_site = HDX_CONFIG["site"]

        # Initialize HDX configuration
        try:
            Configuration.create(hdx_site=self.hdx_site, user_agent="disaster-agent-v1")
            self.logger.info("HDX API initialized")
        except Exception as e:
            self.logger.warning(f"HDX already configured: {e}")

    def fetch_data(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> List[Dict]:
        """Fetch EM-DAT data from HDX"""

        self.logger.info(f"Fetching EM-DAT data from HDX: {self.dataset_name}")

        try:
            # Read dataset from HDX
            dataset = Dataset.read_from_hdx(self.dataset_name)

            if not dataset:
                self.logger.error(f"Dataset '{self.dataset_name}' not found on HDX")
                return []

            resources = dataset.get_resources()
            self.logger.info(f"Found {len(resources)} resources in dataset")

            all_records = []

            # Process each resource (usually CSV files)
            for resource in resources:
                try:
                    resource_name = resource.get("name", "unknown")
                    self.logger.info(f"Processing resource: {resource_name}")

                    # Download resource to temporary file
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
                        tmp_path = tmp.name

                    # Download the resource
                    url, path = resource.download(folder=tempfile.gettempdir())
                    self.logger.info(f"Downloaded to: {path}")

                    # Read CSV file
                    df = pd.read_csv(path, encoding='utf-8', encoding_errors='replace')
                    self.logger.info(f"Loaded {len(df)} rows from {resource_name}")

                    # Convert DataFrame to records
                    records = self._parse_emdat_data(df, start_date, end_date)
                    all_records.extend(records)

                    # Cleanup
                    Path(path).unlink(missing_ok=True)

                except Exception as e:
                    self.logger.error(f"Failed to process resource {resource_name}: {e}")
                    continue

            self.logger.info(f"Total records fetched: {len(all_records)}")
            return all_records

        except Exception as e:
            self.logger.error(f"Failed to fetch EM-DAT data: {e}")
            return []

    def _parse_emdat_data(
        self,
        df: pd.DataFrame,
        start_date: Optional[str],
        end_date: Optional[str]
    ) -> List[Dict]:
        """Parse EM-DAT DataFrame into standardized records"""

        records = []

        # EM-DAT column mappings (adjust based on actual column names)
        # Common EM-DAT columns: Year, Disaster Type, Country, Start Year, Total Deaths, Total Affected, etc.

        for idx, row in df.iterrows():
            try:
                # Extract year/date information
                year = row.get("Year") or row.get("Start Year")
                if pd.isna(year):
                    continue

                # Create approximate date (use mid-year if month not available)
                month = row.get("Start Month", 6)
                day = row.get("Start Day", 15)
                try:
                    event_time = datetime(int(year), int(month) if not pd.isna(month) else 6, int(day) if not pd.isna(day) else 15)
                except:
                    event_time = datetime(int(year), 6, 15)

                # Filter by date range if specified
                if start_date:
                    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
                    if event_time < start_dt:
                        continue

                if end_date:
                    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
                    if event_time > end_dt:
                        continue

                # Extract disaster type
                disaster_type = row.get("Disaster Type") or row.get("Disaster Subtype") or "Unknown"

                # Extract location
                country = row.get("Country") or row.get("ISO") or "Unknown"
                location_text = row.get("Location", country)

                # Extract impact data
                total_deaths = row.get("Total Deaths") or row.get("No Killed")
                if pd.notna(total_deaths):
                    try:
                        total_deaths = int(float(total_deaths))
                    except:
                        total_deaths = None
                else:
                    total_deaths = None

                total_affected = row.get("Total Affected") or row.get("No Affected")
                if pd.notna(total_affected):
                    try:
                        total_affected = int(float(total_affected))
                    except:
                        total_affected = None
                else:
                    total_affected = None

                # Extract economic losses
                total_damage = row.get("Total Damage ('000 US$)") or row.get("Total Damages ('000 US$)")
                economic_loss = None
                if pd.notna(total_damage):
                    try:
                        # Convert from thousands to actual value
                        damage_value = float(total_damage) * 1000
                        # Convert to M or B notation
                        if damage_value >= 1_000_000_000:
                            economic_loss = f"{damage_value / 1_000_000_000:.2f}B"
                        elif damage_value >= 1_000_000:
                            economic_loss = f"{damage_value / 1_000_000:.2f}M"
                        else:
                            economic_loss = f"{damage_value / 1000:.2f}K"
                    except:
                        economic_loss = None

                # Create disaster event ID
                dis_no = row.get("Dis No") or f"EMDAT-{year}-{idx}"

                # Create record
                record = {
                    "source_event_id": str(dis_no),
                    "event_time": event_time,
                    "location_text": str(location_text),
                    "latitude": None,  # EM-DAT doesn't provide coordinates
                    "longitude": None,
                    "disaster_type": str(disaster_type),
                    "magnitude_value": None,
                    "magnitude_unit": None,
                    "fatalities": total_deaths,
                    "economic_loss": economic_loss,
                    "affected": total_affected,
                    "raw_json": row.to_dict()
                }

                records.append(record)

            except Exception as e:
                self.logger.debug(f"Failed to parse row {idx}: {e}")
                continue

        return records


if __name__ == "__main__":
    # Configure logging
    logger.add("logs/emdat_agent.log", rotation="100 MB", retention="30 days")

    agent = EMDATAgent()
    agent.run()
