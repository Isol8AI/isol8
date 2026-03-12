"""Tests for sprite storage service."""

import io
import zipfile

from unittest.mock import MagicMock, patch

from PIL import Image

from core.services.sprite_storage import (
    extract_walk_spritesheet,
    upload_sprite_to_s3,
    SHEET_WIDTH,
    SHEET_HEIGHT,
    FRAME_SIZE,
    DIRECTION_ROWS,
)


def _make_frame_png(size: int = FRAME_SIZE, color=(255, 0, 0, 255)) -> bytes:
    """Create a single RGBA PNG frame for testing."""
    img = Image.new("RGBA", (size, size), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _build_walk_zip(
    directions: dict[str, int] | None = None,
    frame_size: int = FRAME_SIZE,
    colors: dict[str, tuple] | None = None,
) -> bytes:
    """Build a mock PixelLab character ZIP with walk animation frames.

    Args:
        directions: dict of direction_name -> frame_count. Defaults to 4 directions x 6 frames.
        frame_size: pixel size of each frame.
        colors: dict of direction_name -> RGBA color tuple for distinct colors per direction.
    """
    if directions is None:
        directions = {"south": 6, "west": 6, "east": 6, "north": 6}
    if colors is None:
        colors = {d: (255, 0, 0, 255) for d in directions}

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for direction, count in directions.items():
            color = colors.get(direction, (255, 0, 0, 255))
            for i in range(count):
                frame_path = f"animations/walk/{direction}/{i:04d}.png"
                zf.writestr(frame_path, _make_frame_png(size=frame_size, color=color))
    return buf.getvalue()


class TestExtractWalkSpritesheet:
    def test_returns_png_with_correct_dimensions(self):
        """Extracts walk frames from ZIP and composites into 288x192 spritesheet."""
        zip_bytes = _build_walk_zip()
        result = extract_walk_spritesheet(zip_bytes)

        assert result is not None
        img = Image.open(io.BytesIO(result))
        assert img.size == (SHEET_WIDTH, SHEET_HEIGHT)
        assert img.mode == "RGBA"

    def test_returns_none_for_invalid_zip(self):
        """Returns None for corrupt/invalid ZIP data."""
        result = extract_walk_spritesheet(b"not-a-zip-file")
        assert result is None

    def test_returns_none_when_no_walk_frames(self):
        """Returns None if ZIP has no walk animation directory."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            # Add non-walk animation frames
            zf.writestr("animations/idle/south/0000.png", _make_frame_png())
        result = extract_walk_spritesheet(buf.getvalue())
        assert result is None

    def test_composites_directions_in_correct_row_order(self):
        """South=row0, West=row1, East=row2, North=row3 with distinct colors."""
        colors = {
            "south": (255, 0, 0, 255),
            "west": (0, 255, 0, 255),
            "east": (0, 0, 255, 255),
            "north": (255, 255, 0, 255),
        }
        zip_bytes = _build_walk_zip(colors=colors)
        result = extract_walk_spritesheet(zip_bytes)

        assert result is not None
        img = Image.open(io.BytesIO(result))

        for direction, row in DIRECTION_ROWS.items():
            pixel = img.getpixel((FRAME_SIZE // 2, row * FRAME_SIZE + FRAME_SIZE // 2))
            assert pixel == colors[direction], f"Row {row} ({direction}) has wrong color: {pixel}"

    def test_handles_missing_direction(self):
        """Still produces spritesheet if some directions are missing."""
        zip_bytes = _build_walk_zip(directions={"south": 6, "north": 6})
        result = extract_walk_spritesheet(zip_bytes)

        assert result is not None
        img = Image.open(io.BytesIO(result))
        assert img.size == (SHEET_WIDTH, SHEET_HEIGHT)

        # South row should have content (non-transparent)
        south_pixel = img.getpixel((FRAME_SIZE // 2, FRAME_SIZE // 2))
        assert south_pixel[3] > 0  # alpha > 0

        # West row should be transparent (missing)
        west_pixel = img.getpixel((FRAME_SIZE // 2, 1 * FRAME_SIZE + FRAME_SIZE // 2))
        assert west_pixel[3] == 0  # fully transparent

    def test_returns_none_when_no_directions_match(self):
        """Returns None if walk frames exist but no recognized direction names."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            # Walk frames with unrecognized direction names
            zf.writestr("animations/walk/diagonal/0000.png", _make_frame_png())
        result = extract_walk_spritesheet(buf.getvalue())
        assert result is None

    def test_limits_to_frame_count(self):
        """Only uses first FRAME_COUNT frames per direction even if more exist."""
        zip_bytes = _build_walk_zip(directions={"south": 10, "west": 10, "east": 10, "north": 10})
        result = extract_walk_spritesheet(zip_bytes)

        assert result is not None
        img = Image.open(io.BytesIO(result))
        # Width should still be FRAME_COUNT * FRAME_SIZE, not 10 * FRAME_SIZE
        assert img.size == (SHEET_WIDTH, SHEET_HEIGHT)

    def test_resizes_oversized_frames(self):
        """Frames larger than FRAME_SIZE get resized down."""
        zip_bytes = _build_walk_zip(frame_size=96)
        result = extract_walk_spritesheet(zip_bytes)

        assert result is not None
        img = Image.open(io.BytesIO(result))
        assert img.size == (SHEET_WIDTH, SHEET_HEIGHT)


class TestUploadSpriteToS3:
    def test_uploads_to_correct_key(self):
        """Uploads PNG to sprites/{agent_id}/walk.png with correct metadata."""
        png_bytes = _make_frame_png()

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
