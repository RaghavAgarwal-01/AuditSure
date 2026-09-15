"""
AuditSure API - Application Entry Point
=============================================
Run with:

    python -m uvicorn api.main:app --reload --port 8000
    uvicorn api.main:app --reload --port 8000

No GST compliance logic lives here or anywhere in api/ - see
app.auditsure_pipeline for the single compliance path shared by this
API and cli.py.
"""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from api.config import API_VERSION, get_settings
from api.exceptions import (
    AuditSureAPIError,
    auditsure_api_error_handler,
    unhandled_exception_handler,
    validation_error_handler,
)
from api.routes import compliance, demos, health, ontology

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("auditsure.api")

settings = get_settings()

app = FastAPI(
    title="AuditSure API",
    description=(
        "GST compliance analysis API. Deterministic verdicts come from "
        "the existing Phase 2-6 Z3 reasoning engine (app.auditsure_pipeline); "
        "the LLM (Groq) only explains an already-verified ProofObject, "
        "never decides compliance."
    ),
    version=API_VERSION,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Lightweight request ID + duration logging. Never logs request
    bodies (business profiles may contain PAN/GSTIN) or any secret."""
    request_id = str(uuid.uuid4())
    start = time.monotonic()
    response = await call_next(request)
    duration_ms = (time.monotonic() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request_id=%s method=%s path=%s status=%d duration_ms=%.1f",
        request_id, request.method, request.url.path, response.status_code, duration_ms,
    )
    return response


app.add_exception_handler(AuditSureAPIError, auditsure_api_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(health.router, prefix="/api")
app.include_router(compliance.router, prefix="/api")
app.include_router(demos.router, prefix="/api")
app.include_router(ontology.router, prefix="/api")


@app.get("/api", tags=["health"])
def api_root() -> dict:
    return {"service": "AuditSure API", "status": "ok", "docs": "/docs"}
