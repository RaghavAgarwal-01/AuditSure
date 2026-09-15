"""
API tests - GET /api/demos, GET /api/demos/{name}
Asserts against the actual repository examples/*.json files, not
invented personas.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from api.config import EXAMPLES_DIR
from api.main import app

client = TestClient(app)


def test_list_demos_matches_actual_example_files():
    response = client.get("/api/demos")
    assert response.status_code == 200
    ids = {d["id"] for d in response.json()}
    expected = {p.stem for p in Path(EXAMPLES_DIR).glob("*.json")}
    assert ids == expected
    assert ids  # the repository ships at least one example


def test_get_demo_growing_manufacturer():
    response = client.get("/api/demos/growing_manufacturer")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "growing_manufacturer"
    assert body["profile"]["name"]  # canonical BusinessProfile.to_dict() shape
    assert body["profile"]["state"] == "Karnataka"


def test_get_demo_not_found():
    response = client.get("/api/demos/does_not_exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DEMO_NOT_FOUND"


def test_get_demo_rejects_path_traversal():
    # Note: "/api/demos/.." is normalized by the ASGI router itself to
    # "/api/demos" (the list endpoint) before ever reaching our handler,
    # so it is not a traversal case to test here. These are the payloads
    # that DO reach get_demo()'s {name} path parameter.
    for attempt in ("..%2F..%2F.env", "..%2Fapp", "%2e%2e%2fapp", "....//....//app"):
        response = client.get(f"/api/demos/{attempt}")
        assert response.status_code == 404
        # never a directory listing or file content from outside examples/
        assert "GROQ_API_KEY" not in response.text
