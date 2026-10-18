from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}


def test_openapi_describes_health() -> None:
    schema = client.get("/openapi.json").json()
    assert schema["info"]["title"] == "Recipe Hub API"
    assert "/health" in schema["paths"]
    assert "Health" in schema["components"]["schemas"]


def test_cors_allows_web_app_origin() -> None:
    response = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
