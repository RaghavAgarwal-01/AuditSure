"""
AuditSure API - Error Model
================================
Every error response takes the shape:

    {"error": {"code": "...", "message": "...", "details": [...] | null}}

Never a raw traceback, never a bare string. AuditSureAPIError and its
subclasses carry their own HTTP status code so route code can just
`raise ProfileValidationError(...)` and let the registered handler in
api/main.py turn it into the right response.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger("auditsure.api")


class AuditSureAPIError(Exception):
    """Base class for all deliberate, structured API errors."""

    code = "INTERNAL_SERVER_ERROR"
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

    def __init__(self, message: str, details: Any = None):
        super().__init__(message)
        self.message = message
        self.details = details


class ProfileValidationError(AuditSureAPIError):
    """The request body was well-formed JSON but failed BusinessProfile
    conversion or ontology-aware validation (bad enum value, unknown
    state, malformed nested record, etc.)."""

    code = "PROFILE_VALIDATION_ERROR"
    status_code = 422  # equivalent to status.HTTP_422_UNPROCESSABLE_ENTITY, avoiding its deprecation warning


class DemoNotFoundError(AuditSureAPIError):
    code = "DEMO_NOT_FOUND"
    status_code = status.HTTP_404_NOT_FOUND


class OntologyError(AuditSureAPIError):
    """The ontology file could not be loaded or a requested ontology
    individual does not exist. This is a service-dependency failure,
    not a user input error."""

    code = "ONTOLOGY_ERROR"
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE


class ComplianceAnalysisError(AuditSureAPIError):
    """The deterministic Phase 2-6 pipeline raised something other than
    a profile validation error while producing the ProofObject."""

    code = "COMPLIANCE_ANALYSIS_ERROR"
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR


def _error_body(code: str, message: str, details: Any = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


async def auditsure_api_error_handler(request: Request, exc: AuditSureAPIError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_body(exc.code, exc.message, exc.details),
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=_error_body(
            "VALIDATION_ERROR",
            "Request body failed schema validation.",
            exc.errors(),
        ),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Full detail goes to the server log only - never to the client.
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_error_body(
            "INTERNAL_SERVER_ERROR",
            "An unexpected error occurred while processing the request.",
        ),
    )
