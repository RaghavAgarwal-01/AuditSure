"""
API tests - GET /api/health, GET /api
Offline: no network, no GROQ_API_KEY required.
"""

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_health_ok():
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "AuditSure"
    assert body["ontology_version"]  # non-empty, e.g. "1.1.0"


def test_health_degraded_when_ontology_unavailable(monkeypatch):
    def _boom():
        raise FileNotFoundError("no ontology file")

    monkeypatch.setattr("api.routes.health.get_default_loader", _boom)
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["ontology_version"] is None


def test_api_root():
    response = client.get("/api")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "AuditSure API"
    assert body["status"] == "ok"
    assert body["docs"] == "/docs"
