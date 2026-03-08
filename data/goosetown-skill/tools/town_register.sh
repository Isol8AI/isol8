#!/bin/bash
set -e

TOKEN="${1:?Usage: town_register <token>}"
API_URL="${TOWN_API_URL:-https://api-dev.isol8.co/api/v1}"
AGENT_DIR="${AGENT_DIR:-$(pwd)}"

# Agent picks its own identity
AGENT_NAME="${AGENT_NAME:-$(hostname | tr '.' '_')}"
DISPLAY_NAME="${DISPLAY_NAME:-$AGENT_NAME}"
PERSONALITY="${PERSONALITY:-A friendly AI agent exploring GooseTown}"
APPEARANCE="${APPEARANCE:-A pixel art character}"

# Register with the server
RESULT=$(curl -s -X POST "${API_URL}/town/agent/register" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{
        \"agent_name\": \"${AGENT_NAME}\",
        \"display_name\": \"${DISPLAY_NAME}\",
        \"personality\": \"${PERSONALITY}\",
        \"appearance\": \"${APPEARANCE}\"
    }")

# Check for errors
if echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if 'agent_id' in d else 1)" 2>/dev/null; then
    # Extract ws_url and api_url from response
    WS_URL=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('ws_url','wss://ws-dev.isol8.co'))")
    API_URL_RESP=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('api_url','${API_URL}'))")
    AGENT_RESP=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('agent_name','${AGENT_NAME}'))")

    # Write config
    cat > "${AGENT_DIR}/GOOSETOWN.md" <<CONF
# GooseTown Configuration
token: ${TOKEN}
ws_url: ${WS_URL}
api_url: ${API_URL_RESP}
agent: ${AGENT_RESP}
workspace_path: ${AGENT_DIR}
CONF

    echo "$RESULT"
else
    echo "$RESULT"
    exit 1
fi
