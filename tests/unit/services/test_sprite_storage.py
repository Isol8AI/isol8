"""Tests for sprite storage service."""

import io
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from PIL import Image

from core.services.sprite_storage import (
    download_walk_spritesheet,
    upload_sprite_to_s3,
    SHEET_WIDTH,
    SHEET_HEIGHT,
    FRAME_SIZE,
    FRAME_COUNT,
)


def _make_strip_png(width: int = FRAME_COUNT * FRAME_SIZE, height: int = FRAME_SIZE, color=(255, 0, 0, 255)) -> bytes:
    """Create a simple RGBA PNG strip for testing."""
    img = Image.new("RGBA", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _build_character_response(status: str = "completed", include_walk: bool = True) -> dict:
    """Build a mock PixelLab character API response."""
    animations = []
    if include_walk:
        directions = {}
        for d in ("south", "west", "east", "north"):
            directions[d] = {"url": f"https://pixellab.test/sprites/{d}.png"}
        animations.append(
            {
                "template_animation_id": "walk",
                "status": status,
                "directions": directions,
            }
        )
    return {"character_id": "char_123", "animations": animations}


class TestDownloadWalkSpritesheet:
    @pytest.mark.asyncio
    async def test_returns_png_when_walk_completed(self):
        """Downloads direction strips and composites into a 288x192 spritesheet."""
        character_data = _build_character_response(status="completed")
        strip_bytes = _make_strip_png()

        # Mock the character GET and direction image GETs
        mock_char_resp = MagicMock()
        mock_char_resp.json.return_value = character_data
        mock_char_resp.raise_for_status = MagicMock()

        mock_img_resp = MagicMock()
        mock_img_resp.content = strip_bytes
        mock_img_resp.raise_for_status = MagicMock()

        with patch("core.services.sprite_storage.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            # First call is GET character, next 4 are GET direction images
            mock_client.get.side_effect = [mock_char_resp, mock_img_resp, mock_img_resp, mock_img_resp, mock_img_resp]
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await download_walk_spritesheet("test-key", "char_123")

        assert result is not None
        # Verify it's a valid PNG of the right dimensions
        img = Image.open(io.BytesIO(result))
        assert img.size == (SHEET_WIDTH, SHEET_HEIGHT)
        assert img.mode == "RGBA"

        # Verify authorization header was sent
        first_call = mock_client.get.call_args_list[0]
        assert "Authorization" in first_call.kwargs.get("headers", {})

    @pytest.mark.asyncio
    async def test_returns_none_when_no_walk_animation(self):
        """Returns None if character has no walk animation."""
        character_data = _build_character_response(include_walk=False)

        mock_char_resp = MagicMock()
        mock_char_resp.json.return_value = character_data
        mock_char_resp.raise_for_status = MagicMock()

        with patch("core.services.sprite_storage.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_char_resp
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await download_walk_spritesheet("test-key", "char_123")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_walk_not_completed(self):
        """Returns None if walk animation status is not 'completed'."""
        character_data = _build_character_response(status="processing")

        mock_char_resp = MagicMock()
        mock_char_resp.json.return_value = character_data
        mock_char_resp.raise_for_status = MagicMock()

        with patch("core.services.sprite_storage.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_char_resp
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await download_walk_spritesheet("test-key", "char_123")

        assert result is None

    @pytest.mark.asyncio
    async def test_composites_directions_in_correct_row_order(self):
        """South=row0, West=row1, East=row2, North=row3 with distinct colors."""
        colors = {
            "south": (255, 0, 0, 255),
            "west": (0, 255, 0, 255),
            "east": (0, 0, 255, 255),
            "north": (255, 255, 0, 255),
        }
        character_data = _build_character_response(status="completed")

        mock_char_resp = MagicMock()
        mock_char_resp.json.return_value = character_data
        mock_char_resp.raise_for_status = MagicMock()

        # Create distinct color strips for each direction
        direction_order = ["south", "west", "east", "north"]
        img_responses = []
        for d in direction_order:
            mock_r = MagicMock()
            mock_r.content = _make_strip_png(color=colors[d])
            mock_r.raise_for_status = MagicMock()
            img_responses.append(mock_r)

        with patch("core.services.sprite_storage.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.side_effect = [mock_char_resp] + img_responses
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await download_walk_spritesheet("test-key", "char_123")

        assert result is not None
        img = Image.open(io.BytesIO(result))

        # Check a pixel in the middle of each row to verify correct ordering
        expected_rows = {"south": 0, "west": 1, "east": 2, "north": 3}
        for direction, row in expected_rows.items():
            pixel = img.getpixel((FRAME_SIZE // 2, row * FRAME_SIZE + FRAME_SIZE // 2))
            assert pixel == colors[direction], f"Row {row} ({direction}) has wrong color: {pixel}"

    @pytest.mark.asyncio
    async def test_uses_image_url_fallback(self):
        """Falls back to 'image_url' key when 'url' is not present."""
        character_data = _build_character_response(status="completed")
        # Replace url with image_url
        for d in character_data["animations"][0]["directions"].values():
            d["image_url"] = d.pop("url")

        strip_bytes = _make_strip_png()

        mock_char_resp = MagicMock()
        mock_char_resp.json.return_value = character_data
        mock_char_resp.raise_for_status = MagicMock()

        mock_img_resp = MagicMock()
        mock_img_resp.content = strip_bytes
        mock_img_resp.raise_for_status = MagicMock()

        with patch("core.services.sprite_storage.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.side_effect = [mock_char_resp, mock_img_resp, mock_img_resp, mock_img_resp, mock_img_resp]
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await download_walk_spritesheet("test-key", "char_123")

        assert result is not None
        img = Image.open(io.BytesIO(result))
        assert img.size == (SHEET_WIDTH, SHEET_HEIGHT)


class TestUploadSpriteToS3:
    def test_uploads_to_correct_key(self):
        """Uploads PNG to sprites/{agent_id}/walk.png with correct metadata."""
        png_bytes = _make_strip_png()

        with patch("core.services.sprite_storage.boto3.client") as mock_boto3:
            mock_s3 = MagicMock()
            mock_boto3.return_value = mock_s3

            key = upload_sprite_to_s3(png_bytes, "agent-uuid-123", "my-sprite-bucket")

        assert key == "sprites/agent-uuid-123/walk.png"
        mock_s3.put_object.assert_called_once_with(
            Bucket="my-sprite-bucket",
            Key="sprites/agent-uuid-123/walk.png",
            Body=png_bytes,
            ContentType="image/png",
            CacheControl="public, max-age=31536000",
        )

    def test_returns_s3_key(self):
        """Returns the S3 object key."""
        with patch("core.services.sprite_storage.boto3.client") as mock_boto3:
            mock_boto3.return_value = MagicMock()
            key = upload_sprite_to_s3(b"fake-png", "abc-def", "bucket")

        assert key == "sprites/abc-def/walk.png"
