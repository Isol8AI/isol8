"""
Tests for health check endpoint.

The health endpoint must return:
- HTTP 200 with {"status": "healthy"} when DynamoDB is reachable
- HTTP 503 with {"status": "unhealthy"} when DynamoDB is not reachable

This is critical for ALB health checks - returning 200 on failure
would cause ALB to route traffic to unhealthy instances.
"""

import pytest
from unittest.mock import MagicMock, patch
from httpx import AsyncClient, ASGITransport


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    @pytest.mark.asyncio
    async def test_health_returns_200_when_dynamodb_connected(self):
        """Health endpoint returns 200 when DynamoDB is reachable."""
        from main import app

        mock_table = MagicMock()
        mock_table.load = MagicMock()  # table.load() succeeds

        with (
            patch("core.dynamodb.get_table", return_value=mock_table),
            patch("core.dynamodb.run_in_thread", return_value=None),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/health")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["database"] == "dynamodb"

    @pytest.mark.asyncio
    async def test_health_returns_503_when_dynamodb_unreachable(self):
        """Health endpoint returns 503 when DynamoDB check fails."""
        from main import app

        async def failing_run_in_thread(func, *args, **kwargs):
            raise Exception("Could not connect to DynamoDB")

        mock_table = MagicMock()

        with (
            patch("core.dynamodb.get_table", return_value=mock_table),
            patch("core.dynamodb.run_in_thread", side_effect=failing_run_in_thread),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/health")

            # ALB expects 503 for unhealthy instances
            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "unhealthy"
            assert "error" in data
