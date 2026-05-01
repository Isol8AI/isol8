"""End-to-end smoke test for Paperclip provisioning + proxy.

Skipped by default. Run manually against a local Paperclip + Postgres:

    # 1. Spin up Postgres + pgvector
    docker run --rm -d --name pg -p 5432:5432 \\
      -e POSTGRES_PASSWORD=paperclip -e POSTGRES_USER=paperclip \\
      -e POSTGRES_DB=paperclip pgvector/pgvector:pg16

    # 2. Spin up Paperclip
    docker run --rm -d --name paperclip-smoke \\
      -e DATABASE_URL=postgres://paperclip:paperclip@host.docker.internal:5432/paperclip \\
      -e PAPERCLIP_DEPLOYMENT_MODE=authenticated \\
      -e PAPERCLIP_DEPLOYMENT_EXPOSURE=public \\
      -e PAPERCLIP_PUBLIC_URL=http://localhost:3100 \\
      -e PAPERCLIP_AUTH_DISABLE_SIGN_UP=false \\
      -e BETTER_AUTH_SECRET=smoke-test-secret \\
      -p 3100:3100 paperclipai/paperclip:latest

    # 3. Run this test
    PAPERCLIP_SMOKE_LOCAL=1 \\
    PAPERCLIP_INTERNAL_URL=http://localhost:3100 \\
    PAPERCLIP_SERVICE_TOKEN_KEY=smoke-test-key \\
    ENCRYPTION_KEY=wHc3hAOcLlFzWyu3Ph7xIyClIdVQTrIzFOZDtu_pIEY= \\
    uv run pytest tests/integration/test_paperclip_smoke.py -v -s
"""

import os
import pytest
import httpx

pytestmark = pytest.mark.skipif(
    not os.environ.get("PAPERCLIP_SMOKE_LOCAL"),
    reason="Set PAPERCLIP_SMOKE_LOCAL=1 with local Paperclip + Postgres running",
)


@pytest.mark.asyncio
async def test_provisioning_round_trip():
    """Verify the full provisioning chain works against a real Paperclip server.

    TODO: full flow uses
      - core.services.paperclip_admin_client.PaperclipAdminClient
      - core.services.paperclip_provisioning.PaperclipProvisioning
      - core.repositories.paperclip_repo.PaperclipRepo
    Wire those once we have a local-stack DDB harness for the repo. For now,
    just verify the Paperclip server is reachable.
    """
    base_url = os.environ.get("PAPERCLIP_INTERNAL_URL", "http://localhost:3100")
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as http:
        resp = await http.get("/api/health")
        assert resp.status_code == 200, f"Paperclip /api/health returned {resp.status_code}"


@pytest.mark.asyncio
async def test_provision_org_creates_company():
    """End-to-end: provision_org -> company exists in Paperclip -> board key works."""
    pytest.skip("Requires DDB harness wiring; flesh out when first Paperclip dev deploy lands")
