"""Tests for PixelLabService."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from core.services.pixellab_service import PixelLabService


class TestPixelLabService:
    @pytest.mark.asyncio
    async def test_create_character_returns_id(self):
        service = PixelLabService(api_key="test-key")

        mock_response = MagicMock()
        mock_response.json.return_value = {"character_id": "char_123"}
        mock_response.raise_for_status = MagicMock()

        with patch("core.services.pixellab_service.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await service.create_character(
                description="A blue robot",
                name="BlueBot",
            )
            assert result == "char_123"
            mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_character_returns_data(self):
        service = PixelLabService(api_key="test-key")

        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "completed", "download_url": "https://example.com/sprite.zip"}
        mock_response.raise_for_status = MagicMock()

        with patch("core.services.pixellab_service.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await service.get_character("char_123")
            assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_animate_character(self):
        service = PixelLabService(api_key="test-key")

        mock_response = MagicMock()
        mock_response.json.return_value = {"job_id": "job_456"}
        mock_response.raise_for_status = MagicMock()

        with patch("core.services.pixellab_service.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await service.animate_character("char_123", "walk")
            assert result == "job_456"

    @pytest.mark.asyncio
    async def test_generate_all_animations_calls_walk_and_idle(self):
        service = PixelLabService(api_key="test-key")
        service.animate_character = AsyncMock(return_value="job_id")

        await service.generate_all_animations("char_123")

        assert service.animate_character.call_count == 2
        calls = service.animate_character.call_args_list
        assert calls[0].args == ("char_123", "walk")
        assert calls[1].args[0] == "char_123"
        assert calls[1].args[1] == "breathing-idle"
