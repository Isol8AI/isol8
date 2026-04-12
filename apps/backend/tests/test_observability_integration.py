"""Integration test: verify observability wiring in the live FastAPI app."""

from fastapi.testclient import TestClient


def test_health_returns_request_id(client):
    """Health endpoint should return X-Request-ID header."""
    resp = client.get("/health")
    assert resp.status_code in (200, 503)  # 503 if DynamoDB unavailable in test
    assert "X-Request-ID" in resp.headers
    assert len(resp.headers["X-Request-ID"]) > 0
