"""PixelLab sprite generation service for Bit City agents."""

import logging
import httpx

logger = logging.getLogger(__name__)

PIXELLAB_API_URL = "https://api.pixellab.ai/v1"


class PixelLabService:
    """Generates character sprites via the PixelLab API."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def create_character(
        self,
        description: str,
        name: str,
        n_directions: int = 8,
        size: int = 48,
    ) -> str:
        """Queue character creation. Returns character_id."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{PIXELLAB_API_URL}/characters",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "description": description,
                    "name": name,
                    "n_directions": n_directions,
                    "size": size,
                    "view": "low top-down",
                    "body_type": "humanoid",
                    "detail": "medium detail",
                    "outline": "single color black outline",
                    "shading": "basic shading",
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["character_id"]

    async def get_character(self, character_id: str) -> dict:
        """Get character status and sprite URLs."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{PIXELLAB_API_URL}/characters/{character_id}",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=30.0,
            )
            resp.raise_for_status()
            return resp.json()

    async def animate_character(
        self, character_id: str, animation: str = "walk", action_description: str | None = None
    ) -> str:
        """Queue animation for a character. Returns job_id."""
        async with httpx.AsyncClient() as client:
            body = {"template_animation_id": animation}
            if action_description:
                body["action_description"] = action_description
            resp = await client.post(
                f"{PIXELLAB_API_URL}/characters/{character_id}/animations",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=body,
                timeout=30.0,
            )
            resp.raise_for_status()
            return resp.json().get("job_id", "")

    async def generate_all_animations(self, character_id: str):
        """Generate walk and sleeping animations for a character."""
        await self.animate_character(character_id, "walk")
        await self.animate_character(character_id, "breathing-idle", action_description="sleeping peacefully")
