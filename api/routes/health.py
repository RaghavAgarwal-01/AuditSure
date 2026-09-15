"""
GET /api/health
====================
Deliberately lightweight: verifies the application loads and the
ontology is reachable. Never calls Groq (see item 84 - health/readiness
should not depend on a paid external LLM call).
"""

from __future__ import annotations

from fastapi import APIRouter

from api.config import API_VERSION
from api.schemas import HealthResponse
from app.ontology.ontology_loader import get_default_loader

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    try:
        ontology_version = get_default_loader().get_version()
    except Exception as exc:  # ontology missing/corrupt is a degraded state, not a crash
        return HealthResponse(
            status="degraded",
            service="AuditSure",
            version=API_VERSION,
            ontology_version=None,
            detail=f"Ontology unavailable: {exc}",
        )

    return HealthResponse(
        status="ok",
        service="AuditSure",
        version=API_VERSION,
        ontology_version=ontology_version,
    )
