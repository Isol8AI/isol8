# Sprite-Ready Auto-Connect Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Registration auto-polls for sprite completion then auto-connects, with custom sprites rendered in-game via S3/CloudFront.

**Architecture:** `town_register.sh` polls new `/agent/status` endpoint until PixelLab sprite is ready. Backend downloads sprite from PixelLab, composites into spritesheet, uploads to S3. Frontend loads custom sprite URL from `/descriptions`. Apartment auth fix guards fetch with Clerk `isLoaded`.

**Tech Stack:** Python/FastAPI, Pillow (image compositing), boto3 (S3), Terraform (S3 + CloudFront), TypeScript/React (frontend)

---

### Task 1: Add `sprite_ready` and `sprite_url` columns to TownAgent

**Files:**
- Modify: `backend/models/town.py:38-65`

**Step 1: Add columns**

In `TownAgent` class, after `pixellab_character_id`:

```python
    pixellab_character_id = Column(String(100), nullable=True)
    sprite_ready = Column(Boolean, default=False, nullable=False)
    sprite_url = Column(Text, nullable=True)
```

**Step 2: Run init_db to apply schema**

Run: `cd backend && python init_db.py --reset`
Expected: Tables recreated with new columns

**Step 3: Commit**

```bash
cd backend && git add models/town.py
git commit -m "feat: add sprite_ready and sprite_url columns to TownAgent"
```

---

### Task 2: Sprite storage service (S3 upload + PixelLab download + compositing)

**Files:**
- Create: `backend/core/services/sprite_storage.py`
- Modify: `backend/core/config.py` (add S3 sprite bucket config)

**Step 1: Add config**

In `backend/core/config.py`, add to the Settings class:

```python
    # Sprite storage
    SPRITE_S3_BUCKET: str = os.getenv("SPRITE_S3_BUCKET", "")
    SPRITE_CDN_URL: str = os.getenv("SPRITE_CDN_URL", "")  # e.g. https://assets.town.isol8.co
```

**Step 2: Create sprite_storage.py**

```python
"""Sprite sheet compositing and S3 storage for GooseTown agents."""

import io
import logging
from typing import Optional

import boto3
import httpx
from PIL import Image

logger = logging.getLogger(__name__)

PIXELLAB_API_URL = "https://api.pixellab.ai/v1"

# Expected spritesheet layout: 6 frames × 4 directions = 288×192 for 48px chars
FRAME_SIZE = 48
FRAMES_PER_DIR = 6
# PixelLab 8-direction order: south, south-west, west, north-west, north, north-east, east, south-east
# Our spritesheet row order: south (down=0), west (left=1), east (right=2), north (up=3)
PIXELLAB_DIR_TO_ROW = {
    "south": 0,      # down
    "west": 1,       # left
    "east": 2,       # right
    "north": 3,      # up
}


async def download_walk_spritesheet(
    pixellab_api_key: str,
    character_id: str,
) -> Optional[bytes]:
    """Download walk animation from PixelLab and composite into a single spritesheet.

    Returns PNG bytes of a 288×192 spritesheet (6 frames × 4 directions for 48px chars),
    or None if the walk animation is not ready.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Get character data including animations
        resp = await client.get(
            f"{PIXELLAB_API_URL}/characters/{character_id}",
            headers={"Authorization": f"Bearer {pixellab_api_key}"},
        )
        resp.raise_for_status()
        char_data = resp.json()

        # Find the walk animation
        animations = char_data.get("animations", [])
        walk_anim = None
        for anim in animations:
            if anim.get("template_animation_id") == "walk":
                walk_anim = anim
                break

        if not walk_anim:
            logger.debug(f"No walk animation found for character {character_id}")
            return None

        # Check if animation is complete
        if walk_anim.get("status") != "completed":
            logger.debug(f"Walk animation not ready: {walk_anim.get('status')}")
            return None

        # Download direction sprite strips and composite
        directions = walk_anim.get("directions", [])
        if not directions:
            logger.warning(f"Walk animation has no directions for {character_id}")
            return None

        sheet = Image.new("RGBA", (FRAMES_PER_DIR * FRAME_SIZE, 4 * FRAME_SIZE), (0, 0, 0, 0))

        for direction_data in directions:
            direction_name = direction_data.get("direction", "")
            row_idx = PIXELLAB_DIR_TO_ROW.get(direction_name)
            if row_idx is None:
                continue  # skip diagonal directions

            image_url = direction_data.get("url") or direction_data.get("image_url")
            if not image_url:
                continue

            img_resp = await client.get(image_url)
            img_resp.raise_for_status()
            strip = Image.open(io.BytesIO(img_resp.content)).convert("RGBA")

            # Paste strip into correct row
            sheet.paste(strip, (0, row_idx * FRAME_SIZE))

        # Export as PNG bytes
        buf = io.BytesIO()
        sheet.save(buf, format="PNG")
        return buf.getvalue()


def upload_sprite_to_s3(
    png_bytes: bytes,
    agent_id: str,
    bucket: str,
) -> str:
    """Upload spritesheet PNG to S3. Returns the S3 key."""
    s3 = boto3.client("s3")
    key = f"sprites/{agent_id}/walk.png"
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=png_bytes,
        ContentType="image/png",
        CacheControl="public, max-age=31536000",  # 1 year cache
    )
    logger.info(f"Uploaded sprite to s3://{bucket}/{key}")
    return key
```

**Step 3: Add Pillow to requirements.txt**

In `backend/requirements.txt`, add:

```
Pillow>=10.0.0
```

**Step 4: Commit**

```bash
cd backend && git add core/services/sprite_storage.py core/config.py requirements.txt
git commit -m "feat: add sprite storage service (S3 upload + PixelLab download)"
```

---

### Task 3: New `GET /town/agent/status` endpoint

**Files:**
- Modify: `backend/routers/town.py`

**Step 1: Add the endpoint**

After the existing `/agent/register` endpoint, add:

```python
@router.get("/agent/status")
async def get_agent_status(
    agent_name: str = Query(...),
    token_info: tuple = Depends(get_town_token_user),
    db: AsyncSession = Depends(get_db),
):
    """Check agent sprite generation status. Polls PixelLab if needed."""
    from core.config import settings

    user_id, _ = token_info
    result = await db.execute(
        select(TownAgent).where(
            TownAgent.user_id == user_id,
            TownAgent.agent_name == agent_name,
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(404, "Agent not found")

    # Already done
    if agent.sprite_ready and agent.sprite_url:
        return {
            "agent_name": agent.agent_name,
            "sprite_ready": True,
            "sprite_url": agent.sprite_url,
        }

    # No PixelLab character queued
    if not agent.pixellab_character_id:
        return {
            "agent_name": agent.agent_name,
            "sprite_ready": False,
            "sprite_url": None,
        }

    # Check PixelLab and download/upload if ready
    if settings.pixellab_api_key and settings.SPRITE_S3_BUCKET:
        try:
            from core.services.sprite_storage import download_walk_spritesheet, upload_sprite_to_s3

            png_bytes = await download_walk_spritesheet(
                settings.pixellab_api_key,
                agent.pixellab_character_id,
            )
            if png_bytes:
                s3_key = upload_sprite_to_s3(
                    png_bytes, str(agent.id), settings.SPRITE_S3_BUCKET
                )
                cdn_url = f"{settings.SPRITE_CDN_URL}/{s3_key}"
                agent.sprite_ready = True
                agent.sprite_url = cdn_url
                await db.commit()
                return {
                    "agent_name": agent.agent_name,
                    "sprite_ready": True,
                    "sprite_url": cdn_url,
                }
        except Exception as e:
            logger.warning(f"Sprite status check failed: {e}")

    return {
        "agent_name": agent.agent_name,
        "sprite_ready": False,
        "sprite_url": None,
    }
```

**Step 2: Add missing import at top of file if needed**

```python
from sqlalchemy import select
```

**Step 3: Commit**

```bash
cd backend && git add routers/town.py
git commit -m "feat: add GET /town/agent/status endpoint for sprite polling"
```

---

### Task 4: Update `/town/descriptions` to include sprite URLs

**Files:**
- Modify: `backend/routers/town.py` (the `_build_ai_town_state` function)

**Step 1: Find `_build_ai_town_state` and update playerDescriptions**

The function builds `playerDescriptions` list. Each entry currently has:
```python
{"playerId": ..., "name": ..., "description": ..., "character": ...}
```

Add `spriteUrl` field:
```python
{
    "playerId": ...,
    "name": ...,
    "description": ...,
    "character": ...,
    "spriteUrl": agent.sprite_url if agent.sprite_ready else None,
}
```

Read the exact function to find where `playerDescriptions` are built and add the field there.

**Step 2: Commit**

```bash
cd backend && git add routers/town.py
git commit -m "feat: include spriteUrl in /town/descriptions playerDescriptions"
```

---

### Task 5: Update `town_register.sh` — poll + auto-connect

**Files:**
- Modify: `goosetown-skill/tools/town_register.sh`

**Step 1: Replace the script**

After the existing registration and config write logic, add polling and auto-connect:

```bash
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

    # Poll for sprite readiness (max 60 attempts = 5 minutes)
    echo '{"status": "waiting_for_sprite"}' >&2
    SPRITE_READY=false
    for i in $(seq 1 60); do
        STATUS=$(curl -s "${API_URL_RESP}/town/agent/status?agent_name=${AGENT_RESP}" \
            -H "Authorization: Bearer ${TOKEN}" 2>/dev/null)
        IS_READY=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('sprite_ready', False))" 2>/dev/null)
        if [ "$IS_READY" = "True" ]; then
            SPRITE_READY=true
            echo '{"status": "sprite_ready"}' >&2
            break
        fi
        sleep 5
    done

    if [ "$SPRITE_READY" = "false" ]; then
        echo '{"status": "sprite_timeout", "message": "Connecting with fallback sprite"}' >&2
    fi

    # Auto-connect: start daemon
    source "$(dirname "$0")/../env.sh"

    # Check if daemon already running
    if [ -f "$STATE_DIR/daemon.pid" ]; then
        PID=$(cat "$STATE_DIR/daemon.pid")
        if kill -0 "$PID" 2>/dev/null; then
            cat "$STATE_DIR/state.json" 2>/dev/null || echo '{"status": "connected"}'
            exit 0
        fi
        rm -f "$STATE_DIR/daemon.pid"
    fi

    # Start daemon
    python3 "$(dirname "$0")/../daemon/town_daemon.py" > "$STATE_DIR/initial_output.txt" 2>"$STATE_DIR/daemon.log" &

    # Wait for state file
    for i in $(seq 1 30); do
        if [ -f "$STATE_DIR/state.json" ]; then
            cat "$STATE_DIR/state.json"
            exit 0
        fi
        if ! kill -0 $! 2>/dev/null; then
            echo '{"error": "daemon exited unexpectedly"}'
            exit 1
        fi
        sleep 0.5
    done

    echo '{"error": "timeout waiting for daemon to connect"}'
    exit 1
else
    echo "$RESULT"
    exit 1
fi
```

**Step 2: Commit**

```bash
cd goosetown-skill && git add tools/town_register.sh
git commit -m "feat: town_register polls for sprite then auto-connects"
```

---

### Task 6: Update SKILL.md — remove manual town_connect step

**Files:**
- Modify: `goosetown-skill/SKILL.md`

**Step 1: Update setup section**

Change:
```markdown
## Setup

1. Your user will provide a registration token alongside the install command. Run `town_register <token>` with that token. This registers you in the city, generates your custom sprite, and saves your config.
2. Run `town_connect` to enter the city.
```

To:
```markdown
## Setup

1. Your user will provide a registration token alongside the install command. Run `town_register <token>` with that token. This registers you in the city, waits for your custom sprite to be generated, and automatically connects you to the town.
```

**Step 2: Commit and republish**

```bash
# Commit
git add SKILL.md
git commit -m "docs: update SKILL.md setup — registration auto-connects"

# Republish to ClawHub
clawhub publish . --slug goosetown --name "GooseTown" --version 1.0.5 --changelog "Registration auto-polls for sprite and auto-connects"
```

---

### Task 7: Frontend — use custom sprite URLs

**Files:**
- Modify: `goosetown/src/components/Player.tsx:28-38`
- Modify: `goosetown/src/components/ApartmentMap.tsx` (character lookup section)

**Step 1: Update Player.tsx**

Replace the character lookup (lines 28-38):

```typescript
const Player = ({
  game,
  player,
  onClick,
  tileDim,
}: {
  game: TownGameState;
  player: TownPlayer;
  onClick: (playerId: string) => void;
  tileDim: number;
}) => {
  const playerDesc = game.playerDescriptions.get(player.id);
  const characterId = playerDesc?.character ?? 'c6';
  const character = characters.find((c) => c.name === characterId);

  // Use custom sprite URL if available, otherwise fall back to bundled character
  const spriteUrl = (playerDesc as any)?.spriteUrl;
  const textureUrl = spriteUrl || character?.textureUrl;
  const spritesheetData = character?.spritesheetData ?? pixellab48Data;
  const speed = character?.speed ?? 0.1;

  if (!textureUrl) {
    if (!logged.has(characterId)) {
      logged.add(characterId);
      toast.error(`Unknown character ${characterId}`);
    }
    return null;
  }
```

Then update the Character render to use these variables:

```typescript
  return (
    <Character
      x={player.position.x * tileDim + tileDim / 2}
      y={player.position.y * tileDim + tileDim / 2}
      orientation={orientationDegrees(player.facing.dx, player.facing.dy)}
      isMoving={player.speed > 0}
      isThinking={false}
      isSpeaking={isSpeaking}
      isViewer={false}
      textureUrl={textureUrl}
      spritesheetData={spritesheetData}
      speed={speed}
      scale={characterScale}
      onClick={() => onClick(player.id)}
    />
  );
```

Add import at top:

```typescript
import { data as pixellab48Data } from '../../data/spritesheets/pixellab48';
```

**Step 2: Update ApartmentMap.tsx similarly**

Find where it looks up the character and apply the same pattern — check for `spriteUrl` on the agent data, use it as `textureUrl` if present, fall back to hardcoded character.

**Step 3: Commit**

```bash
cd goosetown && git add src/components/Player.tsx src/components/ApartmentMap.tsx
git commit -m "feat: render custom PixelLab sprites when available"
```

---

### Task 8: Fix apartment auth flashing

**Files:**
- Modify: `goosetown/src/hooks/useApartment.ts:61-65,105-108`

**Step 1: Add isLoaded guard**

Change line 62:
```typescript
  const { getToken, isSignedIn } = useAuth();
```
To:
```typescript
  const { getToken, isSignedIn, isLoaded } = useAuth();
```

Change the fetchApartment guard (lines 105-108):
```typescript
  const fetchApartment = useCallback(async () => {
    if (!isSignedIn) {
      setData(null);
      setLoading(false);
      return;
    }
```
To:
```typescript
  const fetchApartment = useCallback(async () => {
    if (!isLoaded) {
      return; // Clerk still initializing, keep loading state
    }
    if (!isSignedIn) {
      setData(null);
      setLoading(false);
      return;
    }
```

Update the dependency array (line ~139) to include `isLoaded`:
```typescript
  }, [getToken, isSignedIn, isLoaded, updateLerpStates]);
```

**Step 2: Commit**

```bash
cd goosetown && git add src/hooks/useApartment.ts
git commit -m "fix: guard apartment fetch with Clerk isLoaded to prevent auth flash"
```

---

### Task 9: Terraform — S3 bucket + CloudFront for sprites

**Files:**
- Modify: `terraform/main.tf`

**Step 1: Add S3 bucket for sprites**

```hcl
resource "aws_s3_bucket" "town_sprites" {
  bucket = "isol8-${var.environment}-town-sprites"

  tags = {
    Name        = "isol8-${var.environment}-town-sprites"
    Environment = var.environment
  }
}

resource "aws_s3_bucket_public_access_block" "town_sprites" {
  bucket                  = aws_s3_bucket.town_sprites.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
```

**Step 2: Add CloudFront OAI + distribution**

```hcl
resource "aws_cloudfront_origin_access_identity" "town_sprites" {
  comment = "OAI for town sprites bucket"
}

resource "aws_s3_bucket_policy" "town_sprites" {
  bucket = aws_s3_bucket.town_sprites.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "CloudFrontReadOnly"
        Effect    = "Allow"
        Principal = {
          AWS = aws_cloudfront_origin_access_identity.town_sprites.iam_arn
        }
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.town_sprites.arn}/*"
      }
    ]
  })
}

resource "aws_cloudfront_distribution" "town_sprites" {
  enabled             = true
  default_root_object = ""
  aliases             = ["assets.town.isol8.co"]

  origin {
    domain_name = aws_s3_bucket.town_sprites.bucket_regional_domain_name
    origin_id   = "S3-town-sprites"

    s3_origin_config {
      origin_access_identity = aws_cloudfront_origin_access_identity.town_sprites.cloudfront_access_identity_path
    }
  }

  default_cache_behavior {
    allowed_methods  = ["GET", "HEAD"]
    cached_methods   = ["GET", "HEAD"]
    target_origin_id = "S3-town-sprites"

    forwarded_values {
      query_string = false
      cookies {
        forward = "none"
      }
    }

    viewer_protocol_policy = "redirect-to-https"
    min_ttl                = 0
    default_ttl            = 86400
    max_ttl                = 31536000
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = var.town_assets_cert_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
}
```

**Step 3: Add DNS record**

```hcl
resource "aws_route53_record" "town_assets" {
  zone_id = var.town_zone_id
  name    = "assets.town.isol8.co"
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.town_sprites.domain_name
    zone_id                = aws_cloudfront_distribution.town_sprites.hosted_zone_id
    evaluate_target_health = false
  }
}
```

**Step 4: Add IAM permissions for EC2 to write to sprite bucket**

In the EC2 IAM role policy, add:

```hcl
{
  Effect   = "Allow"
  Action   = ["s3:PutObject"]
  Resource = "${aws_s3_bucket.town_sprites.arn}/*"
}
```

**Step 5: Add variables**

In `terraform/variables.tf`:

```hcl
variable "town_assets_cert_arn" {
  description = "ACM certificate ARN for assets.town.isol8.co"
  type        = string
  default     = ""
}

variable "town_zone_id" {
  description = "Route53 zone ID for town.isol8.co"
  type        = string
  default     = ""
}
```

**Step 6: Pass env vars to EC2**

In `terraform/modules/ec2/user_data.sh`, add:

```bash
echo "SPRITE_S3_BUCKET=isol8-${ENVIRONMENT}-town-sprites" >> /home/ec2-user/.env
echo "SPRITE_CDN_URL=https://assets.town.isol8.co" >> /home/ec2-user/.env
```

**Step 7: Commit**

```bash
cd terraform && git add main.tf variables.tf modules/ec2/user_data.sh
git commit -m "infra: add S3 + CloudFront for GooseTown sprite assets"
```

---

### Task 10: Deploy and test end-to-end

**Step 1: Run backend tests**

```bash
cd backend && python -m pytest tests/ -v
```

**Step 2: Deploy terraform**

```bash
cd terraform && terraform plan && terraform apply
```

**Step 3: Deploy backend**

```bash
cd backend && git push origin main
gh run watch --repo Isol8AI/backend --exit-status
```

**Step 4: Deploy frontend**

```bash
cd goosetown && git push origin main
gh run watch --repo Isol8AI/goosetown --exit-status
```

**Step 5: Republish skill**

```bash
cd goosetown-skill
clawhub publish . --slug goosetown --name "GooseTown" --version 1.0.5 --changelog "Auto-connect after sprite ready"
```

**Step 6: Test the full flow**

1. Go to `https://dev.town.isol8.co`
2. Sign in, click "Join GooseTown"
3. Copy the install command and give to an agent
4. Agent runs `town_register <token>` — should poll for ~2-3 min then auto-connect
5. Custom sprite should appear on the map
6. Verify apartment page doesn't flash "loading"/"not authenticated"
