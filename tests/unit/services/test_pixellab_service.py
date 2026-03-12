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
            )
            assert result == "char_123"
            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            assert "/v2/create-character-with-8-directions" in call_args.args[0]
            body = call_args.kwargs["json"]
            assert body["description"] == "A blue robot"
            assert body["image_size"] == {"width": 48, "height": 48}

    @pytest.mark.asyncio
    async def test_get_character_returns_data(self):
        service = PixelLabService(api_key="test-key")

        mock_response = MagicMock()
        mock_response.json.return_value = {"animation_count": 6, "rotation_urls": {}}
        mock_response.raise_for_status = MagicMock()

        with patch("core.services.pixellab_service.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await service.get_character("char_123")
            assert result["animation_count"] == 6
            call_args = mock_client.get.call_args
            assert "/v2/characters/char_123" in call_args.args[0]

    @pytest.mark.asyncio
    async def test_animate_character_returns_job_ids(self):
        service = PixelLabService(api_key="test-key")

        mock_response = MagicMock()
        mock_response.json.return_value = {"background_job_ids": ["job_1", "job_2"]}
        mock_response.raise_for_status = MagicMock()
        mock_response.status_code = 200

        with patch("core.services.pixellab_service.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await service.animate_character("char_123", "walk")
            assert result == ["job_1", "job_2"]
            call_args = mock_client.post.call_args
            assert "/v2/characters/animations" in call_args.args[0]
            body = call_args.kwargs["json"]
            assert body["character_id"] == "char_123"
            assert body["template_animation_id"] == "walk"

    @pytest.mark.asyncio
    async def test_get_job_status(self):
        service = PixelLabService(api_key="test-key")

        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "completed", "id": "job_789"}
        mock_response.raise_for_status = MagicMock()

        with patch("core.services.pixellab_service.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await service.get_job_status("job_789")
            assert result["status"] == "completed"
            call_args = mock_client.get.call_args
            assert "/v2/background-jobs/job_789" in call_args.args[0]

    @pytest.mark.asyncio
    async def test_download_character_zip_returns_bytes(self):
        service = PixelLabService(api_key="test-key")

        mock_response = MagicMock()
        mock_response.content = b"fake-zip-data"
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        with patch("core.services.pixellab_service.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await service.download_character_zip("char_123")
            assert result == b"fake-zip-data"
            call_args = mock_client.get.call_args
            assert "/v2/characters/char_123/zip" in call_args.args[0]

    @pytest.mark.asyncio
    async def test_download_character_zip_returns_none_on_423(self):
        service = PixelLabService(api_key="test-key")

        mock_response = MagicMock()
        mock_response.status_code = 423

        with patch("core.services.pixellab_service.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await service.download_character_zip("char_123")
            assert result is None
