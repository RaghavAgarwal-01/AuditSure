"""
AuditSure API - Settings
============================
Centralizes environment-variable configuration for the API layer so
route modules never read os.environ directly. Keeps a single source
for CORS origins, host/port, environment name, and the API's own
version string (kept separate from ontology_version, which always
comes from the loaded ontology, never from here).
"""

from __future__ import annotations

import os
from pathlib import Path

# api/config.py -> api/ -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = PROJECT_ROOT / "examples"

# The API's own version. Deliberately NOT the ontology_version (that is
# always read live from the loaded ontology - see app.ontology.ontology_loader).
API_VERSION = "0.1.0"


def _parse_origins(raw: str | None) -> list[str]:
    if not raw:
        return ["http://localhost:5173"]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


class Settings:
    def __init__(self) -> None:
        self.environment: str = os.environ.get("AUDITSURE_ENV", "development")
        self.host: str = os.environ.get("API_HOST", "127.0.0.1")
        self.port: int = int(os.environ.get("API_PORT", "8000"))
        self.cors_origins: list[str] = _parse_origins(
            os.environ.get("AUDITSURE_CORS_ORIGINS")
        )


def get_settings() -> Settings:
    # Re-read on every call (cheap) rather than caching at import time,
    # so tests can monkeypatch environment variables per-test.
    return Settings()
