"""Integration test: publish → list → buy → install → revoke flow.

Runs against LocalStack (env var LOCALSTACK_ENDPOINT_URL set) and the
real backend in Docker compose. The full LocalStack fixture wiring is
out of scope for Plan 2; the test below documents the intended
end-to-end flow that the LocalStack-fixture work will exercise.
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("LOCALSTACK_ENDPOINT_URL"),
    reason="integration test requires LocalStack",
)


@pytest.mark.asyncio
async def test_publish_list_buy_install_revoke_flow():
    """Smoke test the entire happy path. Uses LocalStack-backed DDB + S3.

    Documented flow (TODO when LocalStack fixture lands):
      1. Seed admin → seller mapping (pre-existing in fixtures).
      2. Create draft via POST /api/v1/marketplace/listings.
      3. Submit via POST /api/v1/marketplace/listings/{id}/submit.
      4. Approve via POST /api/v1/admin/marketplace/listings/{id}/approve.
      5. Browse via GET /api/v1/marketplace/listings → assert published listing visible.
      6. Free-listing path: download via /install/validate → assert signed URL works.
      7. Refund via POST /api/v1/marketplace/refund (requires a paid listing
         + Stripe test-mode webhook event simulation).
      8. /install/validate → 401 (revoked).

    The LocalStack fixture infrastructure (creating tables, seeding rows,
    wiring the boto3 client to localhost:4566) is the bulk of work; this
    function is the destination spec.
    """
    pytest.skip("LocalStack fixture not yet wired (Plan 2 scaffold only)")
