"""Database connection and utilities"""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager
from loguru import logger
import psycopg2
from typing import Optional

from src.config import DB_CONFIG, DB_URL


# SQLAlchemy engine
engine = create_engine(
    DB_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@contextmanager
def get_db_session():
    """Context manager for database sessions"""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Database session error: {e}")
        raise
    finally:
        session.close()


def get_raw_connection():
    """Get a raw psycopg2 connection"""
    return psycopg2.connect(**DB_CONFIG)


def test_connection() -> bool:
    """Test database connection"""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.fetchone()[0]
            logger.info(f"Database connected: {version}")
            return True
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return False


def check_extensions() -> dict:
    """Check if required extensions are installed"""
    extensions = {}
    try:
        with engine.connect() as conn:
            # Check TimescaleDB
            result = conn.execute(
                text("SELECT COUNT(*) FROM pg_extension WHERE extname = 'timescaledb'")
            )
            extensions["timescaledb"] = result.fetchone()[0] > 0

            # Check PostGIS
            result = conn.execute(
                text("SELECT COUNT(*) FROM pg_extension WHERE extname = 'postgis'")
            )
            extensions["postgis"] = result.fetchone()[0] > 0

            logger.info(f"Extensions status: {extensions}")
    except Exception as e:
        logger.error(f"Failed to check extensions: {e}")

    return extensions
