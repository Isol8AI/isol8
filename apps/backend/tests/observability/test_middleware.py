from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.observability.middleware import RequestContextMiddleware, REQUEST_ID_HEADER
from core.observability.logging import request_id_var


def _create_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/test")
    async def test_endpoint():
        return {"request_id": request_id_var.get()}

    return app


def test_middleware_generates_request_id():
    """When no X-Request-ID header, middleware generates one."""
    client = TestClient(_create_app())
    resp = client.get("/test")
    assert resp.status_code == 200
    assert REQUEST_ID_HEADER in resp.headers
    body = resp.json()
    assert body["request_id"] is not None
    assert body["request_id"] == resp.headers[REQUEST_ID_HEADER]


def test_middleware_honors_incoming_request_id():
    """When X-Request-ID is provided, middleware uses it."""
    client = TestClient(_create_app())
    resp = client.get("/test", headers={REQUEST_ID_HEADER: "my-custom-id"})
    assert resp.headers[REQUEST_ID_HEADER] == "my-custom-id"
    assert resp.json()["request_id"] == "my-custom-id"
