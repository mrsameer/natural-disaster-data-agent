"""Data acquisition agents for various disaster data sources"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from loguru import logger
from datetime import datetime
import json

from src.database import get_raw_connection


class BaseAgent(ABC):
    """Base class for all data acquisition agents"""

    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.logger = logger.bind(agent=agent_name)

    @abstractmethod
    def fetch_data(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict]:
        """Fetch data from the source"""
        pass

    def save_to_staging(self, records: List[Dict]) -> int:
        """Save fetched records to staging table"""
        if not records:
            self.logger.warning("No records to save")
            return 0

        conn = get_raw_connection()
        cursor = conn.cursor()

        try:
            insert_query = """
                INSERT INTO staging.raw_events (
                    source_name, source_event_id, event_time, location_text,
                    latitude, longitude, disaster_type, magnitude_value,
                    magnitude_unit, fatalities, economic_loss, affected, raw_json
                ) VALUES (
                    %(source_name)s, %(source_event_id)s, %(event_time)s,
                    %(location_text)s, %(latitude)s, %(longitude)s,
                    %(disaster_type)s, %(magnitude_value)s, %(magnitude_unit)s,
                    %(fatalities)s, %(economic_loss)s, %(affected)s, %(raw_json)s
                )
                ON CONFLICT DO NOTHING
            """

            for record in records:
                # Add source name
                record["source_name"] = self.agent_name
                # Convert raw_json to string if dict
                if isinstance(record.get("raw_json"), dict):
                    record["raw_json"] = json.dumps(record["raw_json"])

                cursor.execute(insert_query, record)

            conn.commit()
            count = cursor.rowcount
            self.logger.info(f"Saved {count} records to staging")
            return count

        except Exception as e:
            conn.rollback()
            self.logger.error(f"Failed to save records: {e}")
            raise
        finally:
            cursor.close()
            conn.close()

    def run(self, start_date: Optional[str] = None, end_date: Optional[str] = None):
        """Execute the agent workflow"""
        self.logger.info(f"Starting {self.agent_name} agent")
        try:
            data = self.fetch_data(start_date, end_date)
            count = self.save_to_staging(data)
            self.logger.success(f"Agent completed successfully. Processed {count} records")
        except Exception as e:
            self.logger.error(f"Agent failed: {e}")
            raise
