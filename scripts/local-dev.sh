#!/bin/bash
set -euo pipefail

# ============================================================================
# Isol8 Local Development Environment
# Deploys real CDK infrastructure to LocalStack + runs Ollama for local LLM.
#
# Usage: ./scripts/local-dev.sh [--reset] [--seed-only] [--stop]
#
# Prerequisites:
#   - Docker Desktop running
#   - export LOCALSTACK_AUTH_TOKEN=<from https://app.localstack.cloud>
#   - export CLERK_ISSUER=https://up-moth-55.clerk.accounts.dev
#   - export CLERK_SECRET_KEY=sk_test_...
#   - export NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...
#   - npm install -g aws-cdk-local aws-cdk
#   - brew install localstack/tap/localstack-cli
#   - localstack auth set-token <your-token>
# ============================================================================

COMPOSE_FILE="docker-compose.localstack.yml"
GENERATED_ENV="localstack/generated.env"
INFRA_DIR="apps/infra"
LOG_PREFIX="[isol8]"

log() { echo "$LOG_PREFIX $1"; }
err() { echo "$LOG_PREFIX ERROR: $1" >&2; }

# Parse flags
FLAG_RESET=false
FLAG_SEED_ONLY=false
FLAG_STOP=false
for arg in "$@"; do
    case "$arg" in
        --reset) FLAG_RESET=true ;;
        --seed-only) FLAG_SEED_ONLY=true ;;
        --stop) FLAG_STOP=true ;;
        *) err "Unknown flag: $arg"; exit 1 ;;
    esac
done

# Handle --stop
if $FLAG_STOP; then
    log "Stopping all services..."
    docker compose -f "$COMPOSE_FILE" down
    log "Done."
    exit 0
fi

# --------------------------------------------------------------------------
# Check prerequisites
# --------------------------------------------------------------------------
log "Checking prerequisites..."
docker info > /dev/null 2>&1 || { err "Docker is not running."; exit 1; }
log "  ✓ Docker running"
[ -n "${LOCALSTACK_AUTH_TOKEN:-}" ] || { err "LOCALSTACK_AUTH_TOKEN is not set. Get it from https://app.localstack.cloud"; exit 1; }
log "  ✓ LOCALSTACK_AUTH_TOKEN set"
command -v pnpm > /dev/null 2>&1 || { err "pnpm not found."; exit 1; }
log "  ✓ pnpm available"
command -v uv > /dev/null 2>&1 || { err "uv not found."; exit 1; }
log "  ✓ uv available"
command -v cdklocal > /dev/null 2>&1 || { err "cdklocal not found. Install with: npm install -g aws-cdk-local aws-cdk"; exit 1; }
log "  ✓ cdklocal available"

# --------------------------------------------------------------------------
# Handle --reset
# --------------------------------------------------------------------------
if $FLAG_RESET; then
    log "Resetting: wiping all LocalStack data..."
    docker compose -f "$COMPOSE_FILE" down -v
    rm -f "$GENERATED_ENV"
fi

# --------------------------------------------------------------------------
# 1. Start LocalStack + Ollama
# --------------------------------------------------------------------------
log "Starting LocalStack and Ollama..."
docker compose -f "$COMPOSE_FILE" up -d localstack ollama

# Wait for LocalStack health
log "Waiting for LocalStack to be healthy..."
TIMEOUT=120
ELAPSED=0
while ! curl -sf http://localhost:4566/_localstack/health > /dev/null 2>&1; do
    if [ $ELAPSED -ge $TIMEOUT ]; then
        err "LocalStack failed to become healthy within ${TIMEOUT}s"
        docker compose -f "$COMPOSE_FILE" logs localstack
        exit 1
    fi
    ELAPSED=$((ELAPSED + 2))
    sleep 2
done
log "  ✓ LocalStack healthy (localhost:4566)"

# --------------------------------------------------------------------------
# 2. Deploy CDK infrastructure to LocalStack
# --------------------------------------------------------------------------
log "Deploying CDK infrastructure to LocalStack..."
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_DEFAULT_REGION=us-east-1

cd "$INFRA_DIR"

# Install CDK deps if needed
if [ ! -d "node_modules" ]; then
    log "  Installing CDK dependencies..."
    npm ci
fi

# Bootstrap CDK (idempotent — targets LocalStack account 000000000000)
log "  Bootstrapping CDK..."
CDK_DISABLE_LEGACY_EXPORT_WARNING=1 cdklocal bootstrap aws://000000000000/us-east-1 --quiet 2>&1 | grep -v "WARNING\|DeprecationWarning\|trace-deprecation" | while read -r line; do echo "  $line"; done || true

# Deploy all stacks via Stage glob pattern
log "  Deploying all stacks (this may take 1-2 minutes)..."
CDK_DISABLE_LEGACY_EXPORT_WARNING=1 cdklocal deploy "local/*" \
    --require-approval never \
    --app "npx ts-node --prefer-ts-exts lib/local.ts" \
    --outputs-file /tmp/isol8-cdk-outputs.json \
    2>&1 | grep -E "✅|❌|Error|Total time|Outputs:" | while read -r line; do echo "  $line"; done

cd ../..
log "  ✓ CDK infrastructure deployed"

# --------------------------------------------------------------------------
# 3. Extract resource IDs from CDK outputs → generated.env
# --------------------------------------------------------------------------
log "Extracting resource IDs from CDK outputs..."
mkdir -p localstack

python3 -c "
import json, subprocess, os

env_lines = ['# Auto-generated from CDK stack outputs + RDS credentials — do not edit']

# 1. CDK stack outputs
if os.path.exists('/tmp/isol8-cdk-outputs.json'):
    with open('/tmp/isol8-cdk-outputs.json') as f:
        outputs = json.load(f)
    for stack_name, stack_outputs in outputs.items():
        for key, value in stack_outputs.items():
            env_key = key.replace('-', '_').upper()
            env_lines.append(f'{env_key}={value}')

# 2. RDS credentials (dynamic port from LocalStack)
try:
    rds_secret = subprocess.run(
        ['docker', 'exec', 'isol8-localstack', 'awslocal', 'secretsmanager',
         'get-secret-value', '--secret-id', 'isol8/local/rds-credentials',
         '--query', 'SecretString', '--output', 'text'],
        capture_output=True, text=True, check=True
    ).stdout.strip()
    creds = json.loads(rds_secret)
    db_url = f\"postgresql+asyncpg://{creds['username']}:{creds['password']}@localstack:{creds['port']}/{creds['dbname']}\"
    env_lines.append(f'DATABASE_URL={db_url}')
    # Also write a host-accessible version (for running init_db from host)
    db_url_host = f\"postgresql+asyncpg://{creds['username']}:{creds['password']}@localhost:{creds['port']}/{creds['dbname']}\"
    env_lines.append(f'DATABASE_URL_HOST={db_url_host}')
    print(f'  RDS: port={creds[\"port\"]}, db={creds[\"dbname\"]}, user={creds[\"username\"]}')
except Exception as e:
    print(f'  ⚠ Could not read RDS credentials: {e}')

with open('localstack/generated.env', 'w') as f:
    f.write('\n'.join(env_lines) + '\n')
print(f'  Wrote {len(env_lines)} vars to localstack/generated.env')
"

# --------------------------------------------------------------------------
# 3b. Populate DATABASE_URL secret from RDS credentials
# --------------------------------------------------------------------------
# Same as dev/prod where you manually set this secret after deploy.
# We automate it by reading the RDS-generated credentials and constructing the URL.
log "Populating DATABASE_URL secret..."
docker exec isol8-localstack bash -c '
RDS_CREDS=$(awslocal secretsmanager get-secret-value --secret-id "isol8/local/rds-credentials" --query "SecretString" --output text)
DB_URL=$(python3 -c "import json; c=json.loads('"'"'${RDS_CREDS}'"'"'); print(f\"postgresql+asyncpg://{c[\"username\"]}:{c[\"password\"]}@localhost.localstack.cloud:{c[\"port\"]}/{c[\"dbname\"]}\")")
awslocal secretsmanager put-secret-value --secret-id "isol8/local/database_url" --secret-string "$DB_URL"
echo "  DATABASE_URL=$DB_URL"
' 2>&1
log "  ✓ DATABASE_URL secret populated"

# --------------------------------------------------------------------------
# 3c. Restart the ECS backend service (picks up updated secrets)
# --------------------------------------------------------------------------
log "Restarting ECS backend service..."
docker exec isol8-localstack bash -c '
CLUSTER=$(awslocal ecs list-clusters --query "clusterArns[0]" --output text)
SERVICE=$(awslocal ecs list-services --cluster "$CLUSTER" --query "serviceArns[0]" --output text)
awslocal ecs update-service --cluster "$CLUSTER" --service "$SERVICE" --force-new-deployment > /dev/null
echo "  Service redeployed"
' 2>&1
log "  ✓ ECS backend restarting with correct secrets"

# --------------------------------------------------------------------------
# 4. Pull Ollama model (first time only)
# --------------------------------------------------------------------------
log "Checking Ollama model..."
if ! docker exec isol8-ollama ollama list 2>/dev/null | grep -q "qwen2.5:3b"; then
    log "  Pulling qwen2.5:3b (this may take a few minutes on first run)..."
    docker exec isol8-ollama ollama pull qwen2.5:3b
    log "  ✓ Model pulled"
else
    log "  ✓ qwen2.5:3b already available"
fi

if $FLAG_SEED_ONLY; then
    log "=========================================="
    log "  Infrastructure deployed (--seed-only)."
    log "  LocalStack and Ollama are running."
    log "=========================================="
    exit 0
fi

# --------------------------------------------------------------------------
# 5. Run database migrations (fresh tables every time)
# --------------------------------------------------------------------------
log "Running database migrations..."
docker compose -f "$COMPOSE_FILE" run --rm backend uv run python init_db.py --reset 2>&1 | tail -5
log "  ✓ Database tables ready"

# --------------------------------------------------------------------------
# 6. Start backend (in Docker on isol8-local network)
# --------------------------------------------------------------------------
log "Starting backend..."
docker compose -f "$COMPOSE_FILE" up -d backend

BACKEND_TIMEOUT=60
BACKEND_ELAPSED=0
while ! curl -sf http://localhost:8000/health > /dev/null 2>&1; do
    if [ $BACKEND_ELAPSED -ge $BACKEND_TIMEOUT ]; then
        err "Backend failed to become healthy within ${BACKEND_TIMEOUT}s"
        docker compose -f "$COMPOSE_FILE" logs backend --tail 30
        exit 1
    fi
    BACKEND_ELAPSED=$((BACKEND_ELAPSED + 2))
    sleep 2
done
log "  ✓ Backend healthy (http://localhost:8000)"

# --------------------------------------------------------------------------
# 7. Start frontend (on host)
# --------------------------------------------------------------------------
log "Starting frontend..."
source "$GENERATED_ENV" 2>/dev/null || true
cd apps/frontend
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1 \
NEXT_PUBLIC_WS_URL="${WEBSOCKETURLOUTPUT:-}" \
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY="${NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY:-}" \
pnpm dev &
FRONTEND_PID=$!
cd ../..
log "  ✓ Frontend starting (http://localhost:3000)"

log "=========================================="
log "  Ready!"
log "  Backend:  http://localhost:8000"
log "  Frontend: http://localhost:3000"
log ""
log "  Press Ctrl+C to stop frontend."
log "  Run ./scripts/local-dev.sh --stop to stop everything."
log "=========================================="

trap 'log "Stopping frontend..."; kill $FRONTEND_PID 2>/dev/null; log "Frontend stopped. Backend + LocalStack still running."; exit 0' INT TERM
wait $FRONTEND_PID
