#!/usr/bin/env bash
# Publish an agent from the caller's Isol8 EFS workspace to the shared S3 catalog.
#
# Usage:
#   CLERK_TOKEN=<jwt> ./scripts/publish-agent.sh <agent_id> [slug] [description]
#
# Environment:
#   CLERK_TOKEN — required; obtain from browser: `await Clerk.session.getToken()`
#   ISOL8_API   — optional; defaults to https://api-dev.isol8.co/api/v1
set -euo pipefail

if [[ -z "${CLERK_TOKEN:-}" ]]; then
  echo "Error: CLERK_TOKEN env var required" >&2
  echo "In browser console (dev.isol8.co, signed in as admin):" >&2
  echo "  await Clerk.session.getToken()" >&2
  exit 1
fi

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <agent_id> [slug] [description]" >&2
  exit 1
fi

AGENT_ID="$1"
SLUG="${2:-}"
DESCRIPTION="${3:-}"
API="${ISOL8_API:-https://api-dev.isol8.co/api/v1}"

BODY=$(jq -nc \
  --arg agent_id "$AGENT_ID" \
  --arg slug "$SLUG" \
  --arg description "$DESCRIPTION" \
  '{agent_id: $agent_id} + (if $slug == "" then {} else {slug: $slug} end) + (if $description == "" then {} else {description: $description} end)')

echo "POST $API/admin/catalog/publish"
echo "Body: $BODY"

curl --fail --show-error -sS \
  -X POST "$API/admin/catalog/publish" \
  -H "Authorization: Bearer $CLERK_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$BODY" | jq .
