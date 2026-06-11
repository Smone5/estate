"""
The Estate Steward — FastAPI application entry point.

Per DB Spec §6.3: init_db() is called at startup with a retry loop
that prevents crashes when the PostgreSQL container starts slower
than the API container.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .database import init_db
from .rate_limiter import init_rate_limiting

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Perform startup database initialization with retry loop."""
    logger.info("Starting Estate Steward backend...")
    init_db()
    logger.info("Startup complete.")
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title="The Estate Steward",
    version="0.1.0",
    lifespan=lifespan,
)
init_rate_limiting(app)



@app.get("/health")
async def health_check():
    """Liveness probe endpoint."""
    return {"status": "ok"}