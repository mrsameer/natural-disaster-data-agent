"""ETL Pipeline - Transform and load staging data into the main warehouse"""

from datetime import datetime
from typing import List, Dict, Optional
from loguru import logger
import psycopg2
import psycopg2.extras
import psycopg2.extras
import json

from src.database import get_raw_connection
from src.config import ETL_CONFIG
from src.etl.transformations import (
    parse_economic_loss,
    geocode_location,
    extract_country_iso3,
    classify_disaster_type,
    normalize_magnitude_unit
)


class ETLPipeline:
    """ETL Pipeline to transform staging data into the warehouse"""

    def __init__(self):
        self.batch_size = ETL_CONFIG["batch_size"]
        self.logger = logger.bind(component="ETL-Pipeline")

    def get_pending_records(self, limit: int = None) -> List[Dict]:
        """Fetch unprocessed records from staging"""
        conn = get_raw_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        try:
            query = """
                SELECT * FROM staging.raw_events
                WHERE processed = false
                ORDER BY ingested_at
            """
            if limit:
                query += f" LIMIT {limit}"

            cursor.execute(query)
            records = cursor.fetchall()
            self.logger.info(f"Fetched {len(records)} pending records from staging")
            return records

        finally:
            cursor.close()
            conn.close()

    def get_or_create_event_type(self, conn, disaster_group: str, disaster_type: str, disaster_subtype: Optional[str]) -> int:
        """Get or create event type dimension record"""
        cursor = conn.cursor()

        try:
            # Try to find existing
            cursor.execute(
                """
                SELECT event_type_id FROM event_type_dim
                WHERE disaster_group = %s AND disaster_type = %s
                AND (disaster_subtype = %s OR (disaster_subtype IS NULL AND %s IS NULL))
                """,
                (disaster_group, disaster_type, disaster_subtype, disaster_subtype)
            )
            result = cursor.fetchone()

            if result:
                return result[0]

            # Create new
            cursor.execute(
                """
                INSERT INTO event_type_dim (disaster_group, disaster_type, disaster_subtype)
                VALUES (%s, %s, %s)
                RETURNING event_type_id
                """,
                (disaster_group, disaster_type, disaster_subtype)
            )
            event_type_id = cursor.fetchone()[0]
            conn.commit()
            return event_type_id

        except Exception as e:
            conn.rollback()
            self.logger.error(f"Failed to get/create event type: {e}")
            raise

    def get_or_create_location(
        self,
        conn,
        latitude: Optional[float],
        longitude: Optional[float],
        location_text: Optional[str],
        country_iso3: Optional[str] = None
    ) -> int:
        """Get or create location dimension record using PostGIS function"""
        cursor = conn.cursor()

        try:
            # Use the database function
            cursor.execute(
                """
                SELECT get_or_create_location(%s, %s, %s, NULL, NULL, %s)
                """,
                (latitude, longitude, location_text, country_iso3)
            )
            location_id = cursor.fetchone()[0]
            conn.commit()
            return location_id

        except Exception as e:
            conn.rollback()
            self.logger.error(f"Failed to get/create location: {e}")
            raise

    def get_or_create_magnitude(
        self,
        conn,
        magnitude_value: Optional[float],
        magnitude_unit: Optional[str]
    ) -> Optional[int]:
        """Get or create magnitude dimension record"""
        if magnitude_value is None:
            return None

        cursor = conn.cursor()

        try:
            # Create new magnitude record (we don't deduplicate magnitudes)
            cursor.execute(
                """
                INSERT INTO magnitude_dim (primary_value, primary_unit)
                VALUES (%s, %s)
                RETURNING magnitude_id
                """,
                (magnitude_value, magnitude_unit)
            )
            magnitude_id = cursor.fetchone()[0]
            conn.commit()
            return magnitude_id

        except Exception as e:
            conn.rollback()
            self.logger.error(f"Failed to create magnitude: {e}")
            raise

    def create_source_audit(self, conn, staging_record: Dict) -> int:
        """Create source audit record"""
        cursor = conn.cursor()

        try:
            # Convert raw_json to string if needed
            raw_json = staging_record["raw_json"]
            if isinstance(raw_json, dict):
                raw_json = json.dumps(raw_json)

            cursor.execute(
                """
                INSERT INTO source_audit_dim (
                    staging_event_id, source_name, raw_data, processing_status
                ) VALUES (%s, %s, %s::jsonb, %s)
                RETURNING source_record_id
                """,
                (
                    staging_record["source_event_id"],
                    staging_record["source_name"],
                    raw_json,
                    "processed"
                )
            )
            source_record_id = cursor.fetchone()[0]
            conn.commit()
            return source_record_id

        except Exception as e:
            conn.rollback()
            self.logger.error(f"Failed to create source audit: {e}")
            raise

    def transform_and_load_record(self, conn, staging_record: Dict) -> bool:
        """Transform a single staging record and load into fact table"""
        cursor = conn.cursor()

        try:
            # === TRANSFORMATION PHASE ===

            # 1. Parse economic loss
            economic_loss_usd = parse_economic_loss(staging_record.get("economic_loss"))

            # 2. Geocode if needed
            latitude = staging_record.get("latitude")
            longitude = staging_record.get("longitude")
            location_text = staging_record.get("location_text")

            if not latitude or not longitude:
                if location_text:
                    coords = geocode_location(location_text)
                    if coords:
                        latitude, longitude = coords

            # 3. Extract country code
            country_iso3 = extract_country_iso3(location_text) if location_text else None

            # 4. Classify disaster type
            disaster_group, disaster_type, disaster_subtype = classify_disaster_type(
                staging_record.get("disaster_type", "")
            )

            # 5. Normalize magnitude
            magnitude_value = staging_record.get("magnitude_value")
            magnitude_unit = staging_record.get("magnitude_unit")

            if magnitude_value and not magnitude_unit:
                magnitude_value, magnitude_unit = normalize_magnitude_unit(
                    magnitude_value, disaster_type
                )

            # === LOAD PHASE ===

            # Create dimension records
            event_type_id = self.get_or_create_event_type(conn, disaster_group, disaster_type, disaster_subtype)
            location_id = self.get_or_create_location(conn, latitude, longitude, location_text, country_iso3)
            magnitude_id = self.get_or_create_magnitude(conn, magnitude_value, magnitude_unit)
            source_record_id = self.create_source_audit(conn, staging_record)

            # Insert into fact table
            cursor.execute(
                """
                INSERT INTO event_fact (
                    event_time, event_time_end, location_id, event_type_id,
                    magnitude_id, fatalities_total, economic_loss_usd,
                    affected_total, is_master_event
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                RETURNING event_id
                """,
                (
                    staging_record.get("event_time"),
                    None,  # event_time_end
                    location_id,
                    event_type_id,
                    magnitude_id,
                    staging_record.get("fatalities"),
                    economic_loss_usd,
                    staging_record.get("affected"),
                    True  # Initially mark as master event (deduplication happens later)
                )
            )
            event_id = cursor.fetchone()[0]

            # Create event-source junction
            cursor.execute(
                """
                INSERT INTO event_source_junction (event_id, source_record_id)
                VALUES (%s, %s)
                """,
                (event_id, source_record_id)
            )

            # Mark staging record as processed
            cursor.execute(
                """
                UPDATE staging.raw_events
                SET processed = true
                WHERE staging_id = %s
                """,
                (staging_record["staging_id"],)
            )

            conn.commit()
            self.logger.debug(f"Processed staging record {staging_record['staging_id']} -> event {event_id}")
            return True

        except Exception as e:
            conn.rollback()
            self.logger.error(f"Failed to transform/load record {staging_record.get('staging_id')}: {e}")

            # Mark as error
            try:
                cursor.execute(
                    """
                    UPDATE staging.raw_events
                    SET processed = true
                    WHERE staging_id = %s
                    """,
                    (staging_record["staging_id"],)
                )
                conn.commit()
            except:
                pass

            return False

    def run(self, batch_size: Optional[int] = None):
        """Execute ETL pipeline"""
        if not batch_size:
            batch_size = self.batch_size

        self.logger.info("Starting ETL pipeline")

        conn = get_raw_connection()

        try:
            # Fetch pending records
            records = self.get_pending_records(limit=batch_size)

            if not records:
                self.logger.info("No pending records to process")
                return

            # Process each record
            success_count = 0
            error_count = 0

            for record in records:
                if self.transform_and_load_record(conn, record):
                    success_count += 1
                else:
                    error_count += 1

            self.logger.success(
                f"ETL pipeline completed: {success_count} successful, {error_count} errors"
            )

        except Exception as e:
            self.logger.error(f"ETL pipeline failed: {e}")
            raise

        finally:
            conn.close()


if __name__ == "__main__":
    # Configure logging
    logger.add("logs/etl_pipeline.log", rotation="100 MB", retention="30 days")

    pipeline = ETLPipeline()
    pipeline.run()
