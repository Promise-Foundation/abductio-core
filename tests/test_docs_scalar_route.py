import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from abductio_core.adapters.api.main import app


def test_docs_route_serves_html() -> None:
    client = TestClient(app)
    response = client.get("/docs")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "api-reference" in response.text


def test_openapi_json_exists() -> None:
    client = TestClient(app)
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json().get("openapi")
