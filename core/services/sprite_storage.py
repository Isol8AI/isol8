"""Sprite storage service: download from PixelLab, composite, upload to S3."""

import io
import logging
from typing import Optional

import boto3
import httpx
from PIL import Image

from core.services.pixellab_service import PIXELLAB_API_URL

logger = logging.getLogger(__name__)

# Sprite sheet layout: 6 frames x 48px wide, 4 directions x 48px tall
FRAME_COUNT = 6
FRAME_SIZE = 48
SHEET_WIDTH = FRAME_COUNT * FRAME_SIZE  # 288
SHEET_HEIGHT = 4 * FRAME_SIZE  # 192

# Row index for each direction
DIRECTION_ROWS = {"south": 0, "west": 1, "east": 2, "north": 3}


async def download_walk_spritesheet(pixellab_api_key: str, character_id: str) -> Optional[bytes]:
    """Download walk animation from PixelLab and composite into a single spritesheet.

    Returns PNG bytes of a 288x192 spritesheet (6 frames x 4 directions),
    or None if the walk animation is not ready.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Fetch character data
        resp = await client.get(
            f"{PIXELLAB_API_URL}/characters/{character_id}",
            headers={"Authorization": f"Bearer {pixellab_api_key}"},
        )
        resp.raise_for_status()
        character = resp.json()

        # Find the walk animation
        animations = character.get("animations", [])
        walk_anim = None
        for anim in animations:
            if anim.get("template_animation_id") == "walk":
                walk_anim = anim
                break

        if walk_anim is None:
            logger.info("No walk animation found for character %s", character_id)
            return None

        if walk_anim.get("status") != "completed":
            logger.info(
                "Walk animation not completed for character %s (status=%s)",
                character_id,
                walk_anim.get("status"),
            )
            return None

        # Create composite spritesheet
        sheet = Image.new("RGBA", (SHEET_WIDTH, SHEET_HEIGHT), (0, 0, 0, 0))

        directions = walk_anim.get("directions", {})
        for direction_name, row_index in DIRECTION_ROWS.items():
            direction_data = directions.get(direction_name)
            if direction_data is None:
                logger.warning(
                    "Missing direction %s for character %s",
                    direction_name,
                    character_id,
                )
                continue

            image_url = direction_data.get("url") or direction_data.get("image_url")
            if not image_url:
                logger.warning(
                    "No image URL for direction %s, character %s",
                    direction_name,
                    character_id,
                )
                continue

            # Download the direction's sprite strip
            img_resp = await client.get(image_url)
            img_resp.raise_for_status()
            strip = Image.open(io.BytesIO(img_resp.content)).convert("RGBA")

            # Validate strip dimensions
            if strip.size != (SHEET_WIDTH, FRAME_SIZE):
                logger.warning(
                    "Unexpected strip size %s for direction %s, character %s",
                    strip.size,
                    direction_name,
                    character_id,
                )
                continue

            # Paste the strip into the correct row
            sheet.paste(strip, (0, row_index * FRAME_SIZE))

        # Export as PNG bytes
        buf = io.BytesIO()
        sheet.save(buf, format="PNG")
        return buf.getvalue()


def upload_sprite_to_s3(png_bytes: bytes, agent_id: str, bucket: str) -> str:
    """Upload a sprite PNG to S3 and return the S3 key.

    Key pattern: sprites/{agent_id}/walk.png
    """
    s3 = boto3.client("s3")
    key = f"sprites/{agent_id}/walk.png"
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=png_bytes,
        ContentType="image/png",
        CacheControl="public, max-age=31536000",
    )
    logger.info("Uploaded sprite to s3://%s/%s", bucket, key)
    return key
