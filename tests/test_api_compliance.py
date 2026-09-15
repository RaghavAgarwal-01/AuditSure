"""
API tests - POST /api/compliance/check
Uses dry-run Layer 3 (no GROQ_API_KEY needed/used) and a real demo
profile loaded through the actual demo endpoint, so the request body
is a real, previously-validated BusinessProfile - not an invented one.
"""

from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app
from app.llm.layer3_explainer import Layer3ConfigurationError

client = TestClient(app)


def _demo_profile(name: str = "growing_manufacturer") -> dict:
    response = client.get(f"/api/demos/{name}")
    assert response.status_code == 200
    return response.json()["profile"]


def test_compliance_check_happy_path():
    profile = _demo_profile()
    response = client.post(
        "/api/compliance/check", json={"profile": profile, "as_of": "2026-09-10"}
    )
    assert response.status_code == 200
    body = response.json()

    assert "proof" in body and body["proof"]["evaluations"]
    assert "summary" in body
    assert set(body["summary"]) == {"SATISFIED", "VIOLATED", "INDETERMINATE", "NOT_APPLICABLE"}
    assert "phases" in body and len(body["phases"]) == 5
    assert {p["phase"] for p in body["phases"]} == {2, 3, 4, 5, 6}
    assert body["metadata"]["ontology_version"]
    assert body["metadata"]["as_of"] == "2026-09-10"

    valid_statuses = {"SATISFIED", "VIOLATED", "INDETERMINATE", "NOT_APPLICABLE"}
    for evaluation in body["proof"]["evaluations"]:
        assert evaluation["status"] in valid_statuses

    # No "overall score"/percentage should ever be invented.
    assert "overall_score" not in body
    assert "compliance_score" not in body


def test_compliance_check_defaults_as_of_to_today():
    profile = _demo_profile()
    response = client.post("/api/compliance/check", json={"profile": profile})
    assert response.status_code == 200
    assert response.json()["metadata"]["as_of"]  # present, some ISO date


def test_compliance_check_dry_run_explanation_without_groq_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    profile = _demo_profile()
    response = client.post("/api/compliance/check", json={"profile": profile})
    assert response.status_code == 200
    body = response.json()
    assert body["explanation_error"] is None
    assert "DRY RUN" in body["explanation"]


def test_compliance_check_groq_failure_preserves_proof():
    """A Layer 3 (Groq) failure must not discard the deterministic proof."""
    profile = _demo_profile()
    with patch("api.routes.compliance.Layer3Explainer") as mock_explainer_cls:
        mock_explainer_cls.return_value.explain.side_effect = Layer3ConfigurationError(
            "Groq API request failed: simulated network error"
        )
        response = client.post("/api/compliance/check", json={"profile": profile})

    assert response.status_code == 200
    body = response.json()
    assert body["explanation"] is None
    assert body["explanation_error"]["code"] == "EXPLANATION_UNAVAILABLE"
    assert body["proof"]["evaluations"]  # deterministic proof still present


def test_compliance_check_invalid_state_returns_422():
    response = client.post(
        "/api/compliance/check",
        json={"profile": {"name": "Bad Co", "state": "not a real state"}},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "PROFILE_VALIDATION_ERROR"
    assert "not a real state" in body["error"]["message"]


def test_compliance_check_malformed_date_returns_422():
    response = client.post(
        "/api/compliance/check",
        json={"profile": {"name": "X"}, "as_of": "not-a-date"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_compliance_check_missing_required_field_returns_422():
    response = client.post("/api/compliance/check", json={"profile": {}})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert any(err["loc"][-1] == "name" for err in body["error"]["details"])


def test_compliance_check_unknown_field_rejected():
    response = client.post(
        "/api/compliance/check",
        json={"profile": {"name": "X", "not_a_real_field": True}},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_compliance_check_malformed_nested_record_returns_422():
    response = client.post(
        "/api/compliance/check",
        json={
            "profile": {
                "name": "X",
                "inward_invoices": [
                    {
                        "invoice_number": "i1",
                        "invoice_date": "not-a-date",
                        "taxable_value": "1",
                        "tax_amount": "1",
                    }
                ],
            }
        },
    )
    assert response.status_code == 422


def test_compliance_check_no_traceback_leaked():
    response = client.post(
        "/api/compliance/check",
        json={"profile": {"name": "Bad Co", "state": "not a real state"}},
    )
    assert "Traceback" not in response.text
    assert "File \"" not in response.text
