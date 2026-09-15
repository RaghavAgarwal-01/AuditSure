"""
API tests - GET /api/ontology, GET /api/ontology/thresholds,
GET /api/ontology/sections. Asserts against the real, live-loaded
ontology rather than duplicating its constants.
"""

from fastapi.testclient import TestClient

from api.main import app
from app.ontology.ontology_loader import get_default_loader

client = TestClient(app)


def test_ontology_metadata():
    onto = get_default_loader()
    response = client.get("/api/ontology")
    assert response.status_code == 200
    body = response.json()

    assert body["ontology_version"] == onto.get_version()
    assert len(body["states"]) == len(onto.get_all_states())
    assert set(body["business_types"]) == set(onto.get_business_type_names())
    assert set(body["supply_types"]) == set(onto.get_supply_type_names())
    assert body["threshold_count"] == len(onto.get_all_thresholds())
    assert body["section_count"] == len(onto.get_all_sections())
    assert {m["phase"] for m in body["modules"]} == {2, 3, 4, 5, 6}


def test_ontology_thresholds():
    onto = get_default_loader()
    response = client.get("/api/ontology/thresholds")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == len(onto.get_all_thresholds())
    for threshold in body:
        assert {"id", "amount", "unit", "label", "citation", "source_note"} <= set(threshold)


def test_ontology_sections():
    onto = get_default_loader()
    response = client.get("/api/ontology/sections")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == len(onto.get_all_sections())
    for section in body:
        assert {"id", "number", "title", "act"} <= set(section)


def test_ontology_error_returns_503(monkeypatch):
    def _boom():
        raise FileNotFoundError("ontology missing")

    monkeypatch.setattr("api.routes.ontology.get_default_loader", _boom)
    response = client.get("/api/ontology")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ONTOLOGY_ERROR"
