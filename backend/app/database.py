"""
Database engine and session factory with startup connection retry loop.

Per DB Spec §6.3: Attempts up to 5 connections with 2-second delays
to prevent FastAPI crashes when the PostgreSQL container starts slower
than the API container.
"""

import os
import time
import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

logger = logging.getLogger(__name__)

DB_URL = os.environ.get("DB_URL", "postgresql+psycopg2://postgres:postgres@db:5432/estate")
DB_ECHO = os.environ.get("DB_ECHO", "false").lower() == "true"

_MAX_RETRIES = 5
_RETRY_DELAY_SECONDS = 2

engine = None
SessionLocal = None
Base = declarative_base()


def _build_engine() -> None:
    global engine, SessionLocal
    engine = create_engine(
        DB_URL,
        echo=DB_ECHO,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """
    Initialize database connection with retry loop.

    Attempts up to _MAX_RETRIES times with _RETRY_DELAY_SECONDS
    between attempts. Raises RuntimeError if all attempts fail.
    """
    _build_engine()

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            with engine.connect() as conn:
                # Validate connectivity with a lightweight query
                from sqlalchemy import text
                conn.execute(text("SELECT 1"))
                logger.info("Database connection established on attempt %d", attempt)
                return
        except Exception as exc:
            logger.warning(
                "Database connection attempt %d/%d failed: %s",
                attempt,
                _MAX_RETRIES,
                exc,
            )
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY_SECONDS)

    raise RuntimeError(
        f"Failed to connect to database after {_MAX_RETRIES} attempts"
    )