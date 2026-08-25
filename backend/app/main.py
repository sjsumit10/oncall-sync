"""FastAPI application entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.v1 import router as v1_router
from app.api.v1.webhooks import router as webhooks_router
from app.config import get_settings
from app.core.logging import configure_logging
from app.core.middleware import SecurityHeadersMiddleware
from app.services.health import refresh_gauges

settings = get_settings()
log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    yield


app = FastAPI(
    title="On-Call Sync",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_base_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(v1_router)
# Signature-authenticated, so deliberately outside the CSRF-guarded router.
app.include_router(webhooks_router, prefix="/api/v1")


@app.get("/health", tags=["ops"])
async def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    # Gauges are read at scrape time so a restarted process reports the truth
    # immediately rather than zeros until something moves a counter.
    try:
        await refresh_gauges()
    except Exception:
        log.warning("metrics.gauge_refresh_failed", exc_info=True)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
