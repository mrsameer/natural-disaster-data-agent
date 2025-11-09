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
        # Check if configuration already exists, if not create it
        if Configuration._configuration is None:
            try:
                Configuration.create(
                    hdx_site=self.hdx_site,
                    user_agent="disaster-agent-v1",
                    hdx_read_only=True
                )
                self.logger.info("HDX API initialized")
            except Exception as e:
                self.logger.error(f"Failed to initialize HDX: {e}")
                raise
        else:
            self.logger.info("HDX API already configured")

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

            # Process each resource (CSV or XLSX files)
            for resource in resources:
                try:
                    resource_name = resource.get("name", "unknown")
                    resource_format = resource.get("format", "").upper()
                    self.logger.info(
                        f"Processing resource: {resource_name} ({resource_format})"
                    )

                    # Download the resource
                    url, path = resource.download(folder=tempfile.gettempdir())
                    self.logger.info(f"Downloaded to: {path}")

                    # Read file based on format
                    if resource_format == "XLSX":
                        df = pd.read_excel(path, engine="openpyxl")
                    elif resource_format == "CSV":
                        df = pd.read_csv(
                            path, encoding="utf-8", encoding_errors="replace"
                        )
                    else:
                        self.logger.warning(
                            f"Unsupported format {resource_format}, "
                            f"attempting CSV read"
                        )
                        df = pd.read_csv(
                            path, encoding="utf-8", encoding_errors="replace"
                        )

                    self.logger.info(f"Loaded {len(df)} rows from {resource_name}")

                    # Convert DataFrame to records
                    records = self._parse_emdat_data(df, start_date, end_date)
                    all_records.extend(records)

                    # Cleanup
                    Path(path).unlink(missing_ok=True)

                except Exception as e:
                    self.logger.error(
                        f"Failed to process resource {resource_name}: {e}"
                    )
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
        end_date: Optional[str],
    ) -> List[Dict]:
        """Parse EM-DAT country profiles DataFrame into standardized records

        Note: EM-DAT country profiles contain aggregated statistics by country/year,
        not individual disaster events. Each record represents aggregated data for
        a specific country, year, and disaster type.
        """

        records = []

        for idx, row in df.iterrows():
            try:
                # Skip header row (contains hashtag annotations)
                year_val = row.get("Year")
                if pd.isna(year_val) or str(year_val).startswith("#"):
                    continue

                # Extract year
                try:
                    year = int(year_val)
                except (ValueError, TypeError):
                    self.logger.debug(
                        f"Skipping row {idx}: invalid year '{year_val}'"
                    )
                    continue

                # Create date as mid-year since we only have year granularity
                event_time = datetime(year, 6, 15)

                # Filter by date range if specified
                if start_date:
                    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
                    if event_time < start_dt:
                        continue

                if end_date:
                    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
                    if event_time > end_dt:
                        continue

                # Extract location (country-level data)
                country = row.get("Country")
                iso = row.get("ISO")
                if pd.isna(country) or country == "":
                    continue
                location_text = f"{country} ({iso})" if pd.notna(iso) else str(country)

                # Extract disaster classification
                disaster_group = row.get("Disaster Group", "")
                disaster_subgroup = row.get("Disaster Subroup", "")  # Note: typo in original
                disaster_type = row.get("Disaster Type", "")
                disaster_subtype = row.get("Disaster Subtype", "")

                # Build disaster type string
                disaster_type_str = disaster_type
                if pd.notna(disaster_subtype) and disaster_subtype != "":
                    disaster_type_str = f"{disaster_type} - {disaster_subtype}"

                if pd.isna(disaster_type_str) or disaster_type_str == "":
                    disaster_type_str = "Unknown"

                # Extract impact data
                total_deaths = row.get("Total Deaths")
                fatalities = None
                if pd.notna(total_deaths):
                    try:
                        fatalities = int(float(total_deaths))
                    except (ValueError, TypeError):
                        pass

                total_affected = row.get("Total Affected")
                affected = None
                if pd.notna(total_affected):
                    try:
                        affected = int(float(total_affected))
                    except (ValueError, TypeError):
                        pass

                # Extract economic losses (use adjusted USD if available)
                total_damage = row.get("Total Damage (USD, adjusted)") or row.get(
                    "Total Damage (USD, original)"
                )
                economic_loss = None
                if pd.notna(total_damage):
                    try:
                        damage_value = float(total_damage)
                        # Convert to M or B notation
                        if damage_value >= 1_000_000_000:
                            economic_loss = f"{damage_value / 1_000_000_000:.2f}B"
                        elif damage_value >= 1_000_000:
                            economic_loss = f"{damage_value / 1_000_000:.2f}M"
                        elif damage_value >= 1000:
                            economic_loss = f"{damage_value / 1000:.2f}K"
                        else:
                            economic_loss = f"{damage_value:.2f}"
                    except (ValueError, TypeError):
                        pass

                # Create unique event ID for aggregated data
                # Format: EMDAT-[ISO]-[YEAR]-[DISASTER_TYPE]
                iso_code = iso if pd.notna(iso) else "UNK"
                disaster_code = disaster_type[:3].upper() if disaster_type else "UNK"
                event_id = f"EMDAT-{iso_code}-{year}-{disaster_code}"

                # Create record
                # Convert row to dict and replace NaN with None for JSON serialization
                raw_dict = row.to_dict()
                for key, value in raw_dict.items():
                    if pd.isna(value):
                        raw_dict[key] = None

                record = {
                    "source_event_id": event_id,
                    "event_time": event_time,
                    "location_text": location_text,
                    "latitude": None,  # EM-DAT country profiles don't provide coordinates
                    "longitude": None,
                    "disaster_type": disaster_type_str,
                    "magnitude_value": None,
                    "magnitude_unit": None,
                    "fatalities": fatalities,
                    "economic_loss": economic_loss,
                    "affected": affected,
                    "raw_json": raw_dict,
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
