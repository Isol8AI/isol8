# Agent Catalog — One-Click Deploy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a curated agent catalog users can browse in a sidebar Gallery and deploy into their own container with one click, plus a CLI publish flow that promotes agents from the Isol8 admin's prod EFS to S3.

**Architecture:** Backend reads agent files from an admin's EFS, slices user/tier-specific fields out of their `openclaw.json` entry, tars the workspace, and uploads the package to `s3://isol8-agent-catalog/<slug>/v<n>/`. A user-facing deploy endpoint downloads the package, extracts into the user's EFS under a fresh UUID, deep-merges the openclaw slice into the user's config (via the existing Track-1 config-patch pipeline), and writes a `.template` sidecar for provenance. The frontend adds a permanent Gallery section to the sidebar below the user's agents, hides already-deployed templates, and opens a right-side info panel on the `[i]` affordance.

**Tech Stack:** FastAPI (backend), boto3 S3 client, Python tarfile, existing `config_patcher.py` + `workspace.py` infrastructure, Next.js 16 + React 19 + SWR (frontend), AWS CDK (infra), pytest + vitest + Playwright (tests).

---

## File structure

**New backend files:**
- `apps/backend/core/services/catalog_slice.py` — pure functions to strip user/tier fields from a publisher's openclaw.json agent slice
- `apps/backend/core/services/catalog_package.py` — pure functions to build/parse manifest, tar/untar workspace directories
- `apps/backend/core/services/catalog_s3_client.py` — thin boto3 wrapper for catalog bucket reads/writes + `catalog.json` atomic rewrite
- `apps/backend/core/services/catalog_service.py` — orchestration: publish / list / deploy
- `apps/backend/routers/catalog.py` — `GET /catalog`, `POST /catalog/deploy`, `GET /catalog/deployed`
- `apps/backend/routers/admin_catalog.py` — `POST /admin/catalog/publish`
- `apps/backend/tests/unit/test_catalog_slice.py`
- `apps/backend/tests/unit/test_catalog_package.py`
- `apps/backend/tests/unit/test_catalog_s3_client.py`
- `apps/backend/tests/unit/test_catalog_service.py`
- `apps/backend/tests/unit/test_routers_catalog.py`

**Modified backend files:**
- `apps/backend/core/config.py` — add `AGENT_CATALOG_BUCKET` and `PLATFORM_ADMIN_USER_IDS` settings
- `apps/backend/core/auth.py` — add `require_platform_admin` dependency
- `apps/backend/core/containers/workspace.py` — add `extract_tarball_to_workspace` and `read_template_sidecar` helpers
- `apps/backend/main.py` — register the two new routers

**New frontend files:**
- `apps/frontend/src/hooks/useCatalog.ts` — SWR hook for list + deploy mutation
- `apps/frontend/src/components/chat/GallerySection.tsx` — sidebar section container
- `apps/frontend/src/components/chat/GalleryItemRow.tsx` — single row with `[+]` and `[i]`
- `apps/frontend/src/components/chat/AgentDetailPanel.tsx` — right-side info panel
- `apps/frontend/tests/unit/hooks/useCatalog.test.ts`
- `apps/frontend/tests/unit/components/chat/GalleryItemRow.test.tsx`
- `apps/frontend/tests/unit/components/chat/GallerySection.test.tsx`

**Modified frontend files:**
- `apps/frontend/src/components/chat/ChatLayout.tsx` — render `<GallerySection />` below the user's agents list
- `apps/frontend/tests/e2e/journey.spec.ts` — add "deploy an agent from the gallery" step

**New infra file:**
- (modify) `apps/infra/lib/stacks/service-stack.ts` — provision S3 bucket, grant backend task role read/write

**New script:**
- `scripts/publish-agent.sh` — shell wrapper that POSTs to `/admin/catalog/publish` with admin's Clerk token

---

## Task 1: CDK — provision the agent catalog S3 bucket

**Files:**
- Modify: `apps/infra/lib/stacks/service-stack.ts`

- [ ] **Step 1: Add the bucket + grant to `service-stack.ts`**

Locate the class that constructs the backend service + task role (grep for `taskRole` and `grantRead` usage in the file). Near the other bucket/IAM grants, add:

```typescript
import * as s3 from "aws-cdk-lib/aws-s3";

// Inside the stack class, after taskRole is defined:
const agentCatalogBucket = new s3.Bucket(this, "AgentCatalogBucket", {
  bucketName: `isol8-${props.env}-agent-catalog`,
  versioned: true,
  encryption: s3.BucketEncryption.S3_MANAGED,
  blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
  removalPolicy:
    props.env === "prod" ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY,
  autoDeleteObjects: props.env !== "prod",
});

agentCatalogBucket.grantReadWrite(this.taskRole);

// Expose the name to the backend via environment:
this.backendTaskDef.defaultContainer?.addEnvironment(
  "AGENT_CATALOG_BUCKET",
  agentCatalogBucket.bucketName,
);
```

If the stack already has a pattern for exposing bucket names via env vars (e.g., `S3_CONFIG_BUCKET`), follow that pattern exactly — consistency matters more than the snippet above. Look at how `S3_CONFIG_BUCKET` is wired and mirror it.

- [ ] **Step 2: Synth to verify the template is valid**

Run: `cd apps/infra && pnpm cdk synth --quiet`
Expected: exits 0, no errors.

- [ ] **Step 3: Commit**

```bash
git add apps/infra/lib/stacks/service-stack.ts
git commit -m "infra: add agent catalog S3 bucket"
```

---

## Task 2: Backend config — add the two new settings

**Files:**
- Modify: `apps/backend/core/config.py`

- [ ] **Step 1: Add settings**

Near the existing `S3_CONFIG_BUCKET` line in `core/config.py`, add:

```python
AGENT_CATALOG_BUCKET: str = os.getenv("AGENT_CATALOG_BUCKET", "")

# Comma-separated Clerk user IDs allowed to call /admin/catalog/publish.
# v1 is env-driven rather than org-role-driven because "platform admin"
# (Isol8 team publishing curated agents) is distinct from "org admin"
# (customer admin of a customer org).
PLATFORM_ADMIN_USER_IDS: str = os.getenv("PLATFORM_ADMIN_USER_IDS", "")
```

- [ ] **Step 2: Commit**

```bash
git add apps/backend/core/config.py
git commit -m "backend: add catalog bucket and platform-admin settings"
```

---

## Task 3: Backend — `require_platform_admin` auth dependency

**Files:**
- Modify: `apps/backend/core/auth.py`
- Test: `apps/backend/tests/unit/test_auth_platform_admin.py` (new)

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/unit/test_auth_platform_admin.py`:

```python
import pytest
from fastapi import HTTPException

from core.auth import AuthContext, require_platform_admin


def _make_auth(user_id: str) -> AuthContext:
    return AuthContext(user_id=user_id)


def test_require_platform_admin_allows_listed_user(monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_USER_IDS", "user_alpha,user_beta")
    # Re-import settings so it picks up the env change.
    from core import config
    config.settings.PLATFORM_ADMIN_USER_IDS = "user_alpha,user_beta"

    auth = _make_auth("user_alpha")
    assert require_platform_admin(auth) is auth


def test_require_platform_admin_rejects_unlisted_user(monkeypatch):
    from core import config
    config.settings.PLATFORM_ADMIN_USER_IDS = "user_alpha"

    auth = _make_auth("user_outsider")
    with pytest.raises(HTTPException) as exc:
        require_platform_admin(auth)
    assert exc.value.status_code == 403


def test_require_platform_admin_rejects_when_allowlist_empty():
    from core import config
    config.settings.PLATFORM_ADMIN_USER_IDS = ""

    auth = _make_auth("anyone")
    with pytest.raises(HTTPException) as exc:
        require_platform_admin(auth)
    assert exc.value.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && uv run pytest tests/unit/test_auth_platform_admin.py -v`
Expected: FAIL with `ImportError: cannot import name 'require_platform_admin'`.

- [ ] **Step 3: Implement**

Add to `apps/backend/core/auth.py` after the `require_org_admin` function:

```python
def require_platform_admin(auth: AuthContext = Depends(get_current_user)) -> AuthContext:
    """
    Allow only platform admins (Isol8 team) — distinct from customer org admins.

    Allowlist is driven by the PLATFORM_ADMIN_USER_IDS env var (comma-separated
    Clerk user IDs). Returns 403 if the current user is not in the list.
    """
    from core.config import settings

    raw = settings.PLATFORM_ADMIN_USER_IDS or ""
    allowed = {u.strip() for u in raw.split(",") if u.strip()}
    if auth.user_id not in allowed:
        raise HTTPException(status_code=403, detail="Platform admin access required")
    return auth
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && uv run pytest tests/unit/test_auth_platform_admin.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/auth.py apps/backend/tests/unit/test_auth_platform_admin.py
git commit -m "backend(auth): add require_platform_admin dependency"
```

---

## Task 4: Backend — catalog slice (strip user/tier fields)

**Files:**
- Create: `apps/backend/core/services/catalog_slice.py`
- Test: `apps/backend/tests/unit/test_catalog_slice.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/unit/test_catalog_slice.py`:

```python
import pytest

from core.services.catalog_slice import (
    extract_agent_slice,
    strip_user_specific_fields,
)


FULL_OPENCLAW_JSON = {
    "defaultAgentId": "agent_abc",
    "agents": [
        {
            "id": "agent_abc",
            "workspace": ".openclaw/workspaces/agent_abc",
            "name": "Pitch",
            "model": "qwen/qwen3-vl-235b",
            "thinkingDefault": True,
            "skills": ["web-search", "email-send"],
            "channels": {"telegram": {"bot_token": "SECRET"}},
            "cron": [{"schedule": "0 8 * * *", "workflow": "morning-briefing"}],
        },
        {"id": "agent_zzz", "name": "Other"},
    ],
    "plugins": {"memory": {"enabled": True}},
    "tools": {"allowed": ["web-search", "email-send"]},
}


def test_extract_agent_slice_returns_only_named_agent():
    slice_ = extract_agent_slice(FULL_OPENCLAW_JSON, "agent_abc")
    assert slice_["agent"]["id"] == "agent_abc"
    assert slice_["agent"]["name"] == "Pitch"


def test_extract_agent_slice_includes_required_plugins_and_tools():
    slice_ = extract_agent_slice(FULL_OPENCLAW_JSON, "agent_abc")
    assert slice_["plugins"] == {"memory": {"enabled": True}}
    assert slice_["tools"] == {"allowed": ["web-search", "email-send"]}


def test_extract_agent_slice_missing_agent_raises():
    with pytest.raises(KeyError):
        extract_agent_slice(FULL_OPENCLAW_JSON, "agent_does_not_exist")


def test_strip_user_specific_fields_removes_model():
    agent = dict(FULL_OPENCLAW_JSON["agents"][0])
    cleaned = strip_user_specific_fields(agent)
    assert "model" not in cleaned


def test_strip_user_specific_fields_removes_channels():
    agent = dict(FULL_OPENCLAW_JSON["agents"][0])
    cleaned = strip_user_specific_fields(agent)
    assert "channels" not in cleaned


def test_strip_user_specific_fields_removes_workspace_path():
    agent = dict(FULL_OPENCLAW_JSON["agents"][0])
    cleaned = strip_user_specific_fields(agent)
    assert "workspace" not in cleaned


def test_strip_user_specific_fields_removes_id():
    # The id is regenerated on deploy; publisher's id must not leak.
    agent = dict(FULL_OPENCLAW_JSON["agents"][0])
    cleaned = strip_user_specific_fields(agent)
    assert "id" not in cleaned


def test_strip_user_specific_fields_keeps_behavioral_flags():
    agent = dict(FULL_OPENCLAW_JSON["agents"][0])
    cleaned = strip_user_specific_fields(agent)
    assert cleaned["thinkingDefault"] is True
    assert cleaned["skills"] == ["web-search", "email-send"]
    assert cleaned["cron"] == [
        {"schedule": "0 8 * * *", "workflow": "morning-briefing"}
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && uv run pytest tests/unit/test_catalog_slice.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.services.catalog_slice'`.

- [ ] **Step 3: Implement**

Create `apps/backend/core/services/catalog_slice.py`:

```python
"""Pure functions for slicing an agent's entry out of an openclaw.json and
stripping user/tier-specific fields that must not leak into the catalog.

User/tier-specific fields never go in a catalog package:
  - model (user's tier picks a default at runtime)
  - channels (per-user credentials)
  - workspace (path; the deploy generates a new one)
  - id (regenerated per-deploy)

Behavioral fields stay:
  - skills list, plugins config, tools allowlist, cron, thinkingDefault, etc.
"""
from __future__ import annotations

import copy
from typing import Any

_STRIPPED_KEYS = frozenset({"model", "channels", "workspace", "id"})


def strip_user_specific_fields(agent_entry: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(agent_entry)
    for key in _STRIPPED_KEYS:
        result.pop(key, None)
    return result


def extract_agent_slice(openclaw_json: dict[str, Any], agent_id: str) -> dict[str, Any]:
    """Return a dict with the sliced agent entry plus the required plugins/tools
    from the publisher's config. Raises KeyError if the agent_id isn't present.
    """
    agents = openclaw_json.get("agents") or []
    matching = [a for a in agents if a.get("id") == agent_id]
    if not matching:
        raise KeyError(f"agent {agent_id!r} not found in openclaw.json")
    agent_entry = matching[0]

    return {
        "agent": strip_user_specific_fields(agent_entry),
        "plugins": copy.deepcopy(openclaw_json.get("plugins") or {}),
        "tools": copy.deepcopy(openclaw_json.get("tools") or {}),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && uv run pytest tests/unit/test_catalog_slice.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/services/catalog_slice.py apps/backend/tests/unit/test_catalog_slice.py
git commit -m "backend(catalog): slice agent entry and strip user-specific fields"
```

---

## Task 5: Backend — catalog package (manifest + tar helpers)

**Files:**
- Create: `apps/backend/core/services/catalog_package.py`
- Test: `apps/backend/tests/unit/test_catalog_package.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/unit/test_catalog_package.py`:

```python
import io
import json
from pathlib import Path

import pytest

from core.services.catalog_package import (
    build_manifest,
    tar_directory,
    untar_to_directory,
)


def test_build_manifest_populates_required_fields():
    manifest = build_manifest(
        slug="pitch",
        version=3,
        name="Pitch",
        emoji="🎯",
        vibe="Direct, data-driven",
        description="Runs outbound sales sequences",
        suggested_model="qwen/qwen3-vl-235b",
        suggested_channels=["telegram"],
        required_skills=["web-search"],
        required_plugins=["memory"],
        required_tools=["web-search"],
        published_by="user_admin_123",
    )
    assert manifest["slug"] == "pitch"
    assert manifest["version"] == 3
    assert manifest["name"] == "Pitch"
    assert manifest["suggested_model"] == "qwen/qwen3-vl-235b"
    assert manifest["published_by"] == "user_admin_123"
    assert "published_at" in manifest  # ISO timestamp set by function


def test_tar_and_untar_roundtrip(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "IDENTITY.md").write_text("name: Pitch\n")
    (src / "uploads").mkdir()
    (src / "uploads" / "hello.txt").write_text("world")

    tar_bytes = tar_directory(src)
    assert isinstance(tar_bytes, bytes)
    assert len(tar_bytes) > 0

    dst = tmp_path / "dst"
    dst.mkdir()
    untar_to_directory(io.BytesIO(tar_bytes), dst)

    assert (dst / "IDENTITY.md").read_text() == "name: Pitch\n"
    assert (dst / "uploads" / "hello.txt").read_text() == "world"


def test_untar_rejects_absolute_paths(tmp_path: Path):
    # Craft a malicious tar with an absolute member path; untar must refuse.
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        data = b"malicious"
        info = tarfile.TarInfo(name="/etc/evil")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    buf.seek(0)

    dst = tmp_path / "dst"
    dst.mkdir()
    with pytest.raises(ValueError):
        untar_to_directory(buf, dst)


def test_untar_rejects_parent_traversal(tmp_path: Path):
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        data = b"payload"
        info = tarfile.TarInfo(name="../escape")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    buf.seek(0)

    dst = tmp_path / "dst"
    dst.mkdir()
    with pytest.raises(ValueError):
        untar_to_directory(buf, dst)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && uv run pytest tests/unit/test_catalog_package.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

Create `apps/backend/core/services/catalog_package.py`:

```python
"""Manifest construction and safe tar/untar helpers for catalog packages."""
from __future__ import annotations

import io
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO


def build_manifest(
    *,
    slug: str,
    version: int,
    name: str,
    emoji: str,
    vibe: str,
    description: str,
    suggested_model: str,
    suggested_channels: list[str],
    required_skills: list[str],
    required_plugins: list[str],
    required_tools: list[str],
    published_by: str,
) -> dict[str, Any]:
    return {
        "slug": slug,
        "version": version,
        "name": name,
        "emoji": emoji,
        "vibe": vibe,
        "description": description,
        "suggested_model": suggested_model,
        "suggested_channels": suggested_channels,
        "required_skills": required_skills,
        "required_plugins": required_plugins,
        "required_tools": required_tools,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "published_by": published_by,
    }


def tar_directory(src: Path) -> bytes:
    """Tar (gzip) a directory's contents with paths relative to src."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        tf.add(src, arcname=".")
    return buf.getvalue()


def untar_to_directory(tar_stream: BinaryIO, dst: Path) -> None:
    """Extract a tar.gz stream into dst, rejecting any member whose resolved
    path escapes dst (absolute paths or `..` traversal). Raises ValueError on
    a suspicious member.
    """
    dst_resolved = dst.resolve()
    with tarfile.open(fileobj=tar_stream, mode="r:gz") as tf:
        members = tf.getmembers()
        for m in members:
            # Reject absolute paths outright.
            if m.name.startswith("/"):
                raise ValueError(f"tar member has absolute path: {m.name!r}")
            # Resolve the target and ensure it's within dst.
            target = (dst / m.name).resolve()
            try:
                target.relative_to(dst_resolved)
            except ValueError as exc:
                raise ValueError(
                    f"tar member escapes extraction directory: {m.name!r}"
                ) from exc
        tf.extractall(dst)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && uv run pytest tests/unit/test_catalog_package.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/services/catalog_package.py apps/backend/tests/unit/test_catalog_package.py
git commit -m "backend(catalog): manifest builder and safe tar/untar helpers"
```

---

## Task 6: Backend — S3 client for catalog bucket

**Files:**
- Create: `apps/backend/core/services/catalog_s3_client.py`
- Test: `apps/backend/tests/unit/test_catalog_s3_client.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/unit/test_catalog_s3_client.py`:

```python
import json

import boto3
import pytest
from moto import mock_aws

from core.services.catalog_s3_client import CatalogS3Client


@pytest.fixture
def bucket_name() -> str:
    return "isol8-test-agent-catalog"


@pytest.fixture
def s3_backend(bucket_name: str):
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=bucket_name)
        yield client


def test_put_and_get_object_roundtrip(s3_backend, bucket_name: str):
    c = CatalogS3Client(bucket_name=bucket_name)
    c.put_bytes("pitch/v1/manifest.json", b'{"slug":"pitch"}')
    got = c.get_bytes("pitch/v1/manifest.json")
    assert got == b'{"slug":"pitch"}'


def test_get_json_parses(s3_backend, bucket_name: str):
    c = CatalogS3Client(bucket_name=bucket_name)
    c.put_bytes("catalog.json", json.dumps({"agents": []}).encode())
    assert c.get_json("catalog.json") == {"agents": []}


def test_get_json_missing_returns_default(s3_backend, bucket_name: str):
    c = CatalogS3Client(bucket_name=bucket_name)
    assert c.get_json("missing.json", default={"x": 1}) == {"x": 1}


def test_put_json_writes_json(s3_backend, bucket_name: str):
    c = CatalogS3Client(bucket_name=bucket_name)
    c.put_json("catalog.json", {"agents": [{"slug": "pitch"}]})
    body = s3_backend.get_object(Bucket=bucket_name, Key="catalog.json")["Body"].read()
    assert json.loads(body) == {"agents": [{"slug": "pitch"}]}


def test_list_versions_returns_version_numbers(s3_backend, bucket_name: str):
    c = CatalogS3Client(bucket_name=bucket_name)
    c.put_bytes("pitch/v1/manifest.json", b"{}")
    c.put_bytes("pitch/v2/manifest.json", b"{}")
    c.put_bytes("pitch/v5/manifest.json", b"{}")
    assert c.list_versions("pitch") == [1, 2, 5]


def test_list_versions_empty_for_unknown_slug(s3_backend, bucket_name: str):
    c = CatalogS3Client(bucket_name=bucket_name)
    assert c.list_versions("unknown") == []
```

Make sure `moto` is a dev dependency. If `uv run pytest` reports `ModuleNotFoundError: moto`, run `cd apps/backend && uv add --dev moto` before proceeding.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && uv run pytest tests/unit/test_catalog_s3_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.services.catalog_s3_client'`.

- [ ] **Step 3: Implement**

Create `apps/backend/core/services/catalog_s3_client.py`:

```python
"""Thin S3 wrapper for the agent catalog bucket."""
from __future__ import annotations

import json
import re
from typing import Any

import boto3
from botocore.exceptions import ClientError

_VERSION_KEY_RE = re.compile(r"^[^/]+/v(\d+)/")


class CatalogS3Client:
    def __init__(self, bucket_name: str, region_name: str = "us-east-1"):
        if not bucket_name:
            raise ValueError("bucket_name is required")
        self._bucket = bucket_name
        self._s3 = boto3.client("s3", region_name=region_name)

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self._s3.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)

    def get_bytes(self, key: str) -> bytes:
        resp = self._s3.get_object(Bucket=self._bucket, Key=key)
        return resp["Body"].read()

    def put_json(self, key: str, obj: Any) -> None:
        self.put_bytes(key, json.dumps(obj).encode("utf-8"), content_type="application/json")

    def get_json(self, key: str, default: Any = None) -> Any:
        try:
            return json.loads(self.get_bytes(key).decode("utf-8"))
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                return default
            raise

    def list_versions(self, slug: str) -> list[int]:
        """Return sorted list of published version numbers for a slug."""
        prefix = f"{slug}/"
        paginator = self._s3.get_paginator("list_objects_v2")
        versions: set[int] = set()
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            for obj in page.get("Contents", []) or []:
                m = _VERSION_KEY_RE.match(obj["Key"])
                if m:
                    versions.add(int(m.group(1)))
        return sorted(versions)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && uv run pytest tests/unit/test_catalog_s3_client.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/services/catalog_s3_client.py apps/backend/tests/unit/test_catalog_s3_client.py
git commit -m "backend(catalog): S3 client wrapper for catalog bucket"
```

---

## Task 7: Backend — workspace helpers for tarball extraction and template sidecar

**Files:**
- Modify: `apps/backend/core/containers/workspace.py`
- Test: `apps/backend/tests/unit/test_workspace_catalog_helpers.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/unit/test_workspace_catalog_helpers.py`:

```python
import io
import tarfile
from pathlib import Path

import pytest

from core.containers.workspace import Workspace


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    # Point EFS_MOUNT_PATH at tmp_path for this test.
    from core import config
    config.settings.EFS_MOUNT_PATH = str(tmp_path)
    return Workspace(mount_path=str(tmp_path))


def _make_tar_with(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_extract_tarball_to_workspace_writes_files(workspace: Workspace, tmp_path: Path):
    tar_bytes = _make_tar_with({
        "./IDENTITY.md": b"name: Pitch\n",
        "./uploads/hello.txt": b"world",
    })
    workspace.extract_tarball_to_workspace(
        user_id="user_abc",
        agent_id="agent_new",
        tar_bytes=tar_bytes,
    )
    base = tmp_path / "user_abc" / "workspaces" / "agent_new"
    assert (base / "IDENTITY.md").read_text() == "name: Pitch\n"
    assert (base / "uploads" / "hello.txt").read_text() == "world"


def test_read_template_sidecar_returns_none_when_absent(workspace: Workspace, tmp_path: Path):
    (tmp_path / "user_abc" / "workspaces" / "agent_new").mkdir(parents=True)
    assert workspace.read_template_sidecar("user_abc", "agent_new") is None


def test_read_template_sidecar_returns_parsed_json(workspace: Workspace, tmp_path: Path):
    base = tmp_path / "user_abc" / "workspaces" / "agent_new"
    base.mkdir(parents=True)
    (base / ".template").write_text(
        '{"template_slug":"pitch","template_version":3}'
    )
    assert workspace.read_template_sidecar("user_abc", "agent_new") == {
        "template_slug": "pitch",
        "template_version": 3,
    }


def test_read_template_sidecar_returns_none_on_corrupt_json(workspace: Workspace, tmp_path: Path):
    base = tmp_path / "user_abc" / "workspaces" / "agent_new"
    base.mkdir(parents=True)
    (base / ".template").write_text("{not-json")
    assert workspace.read_template_sidecar("user_abc", "agent_new") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && uv run pytest tests/unit/test_workspace_catalog_helpers.py -v`
Expected: FAIL with `AttributeError: 'Workspace' object has no attribute 'extract_tarball_to_workspace'`.

- [ ] **Step 3: Implement**

Add to `apps/backend/core/containers/workspace.py` (below the existing `write_file` / `cleanup_agent_dirs` methods; reuse the existing `_chown_for_access_point` helper for post-extract ownership):

```python
import io
import json
from core.services.catalog_package import untar_to_directory


def extract_tarball_to_workspace(
    self,
    user_id: str,
    agent_id: str,
    tar_bytes: bytes,
) -> None:
    """Extract a workspace tarball into {mount}/{user_id}/workspaces/{agent_id}/.
    Rejects path traversal via catalog_package.untar_to_directory.
    """
    target = self.user_path(user_id) / "workspaces" / agent_id
    target.mkdir(parents=True, exist_ok=True)
    untar_to_directory(io.BytesIO(tar_bytes), target)

    # chown every extracted path to UID 1000 so OpenClaw (node user) can read.
    for path in target.rglob("*"):
        self._chown_for_access_point(path, user_id)
    self._chown_for_access_point(target, user_id)


def read_template_sidecar(self, user_id: str, agent_id: str) -> dict | None:
    sidecar = self.user_path(user_id) / "workspaces" / agent_id / ".template"
    if not sidecar.exists():
        return None
    try:
        return json.loads(sidecar.read_text())
    except (json.JSONDecodeError, OSError):
        return None
```

Place these as instance methods on the `Workspace` class (match the indentation of the other methods).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && uv run pytest tests/unit/test_workspace_catalog_helpers.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/containers/workspace.py apps/backend/tests/unit/test_workspace_catalog_helpers.py
git commit -m "backend(workspace): add tarball extract and .template sidecar helpers"
```

---

## Task 8: Backend — catalog service `list()` and `deploy()`

**Files:**
- Create: `apps/backend/core/services/catalog_service.py`
- Test: `apps/backend/tests/unit/test_catalog_service.py`

- [ ] **Step 1: Write the failing test (list + deploy only — publish next task)**

Create `apps/backend/tests/unit/test_catalog_service.py`:

```python
import io
import json
import tarfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.services.catalog_service import CatalogService


def _tar_with(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.fixture
def mock_s3():
    m = MagicMock()
    m.get_json.return_value = {
        "updated_at": "2026-04-19T00:00:00Z",
        "agents": [{"slug": "pitch", "current_version": 3, "manifest_url": "pitch/v3/manifest.json"}],
    }
    return m


@pytest.fixture
def mock_workspace():
    m = MagicMock()
    m.read_openclaw_config.return_value = {}
    return m


@pytest.fixture
def mock_patch_config():
    return AsyncMock()


@pytest.fixture
def service(mock_s3, mock_workspace, mock_patch_config):
    return CatalogService(
        s3=mock_s3,
        workspace=mock_workspace,
        patch_openclaw_config=mock_patch_config,
    )


def test_list_returns_entries_with_manifest_preview(service, mock_s3):
    def _get_json(key, default=None):
        if key == "catalog.json":
            return {"agents": [{"slug": "pitch", "current_version": 3, "manifest_url": "pitch/v3/manifest.json"}]}
        if key == "pitch/v3/manifest.json":
            return {
                "slug": "pitch", "version": 3, "name": "Pitch", "emoji": "🎯",
                "vibe": "Direct", "description": "Sales",
                "suggested_model": "qwen", "suggested_channels": ["telegram"],
                "required_skills": ["web-search"], "required_plugins": ["memory"],
                "required_tools": ["web-search"],
                "published_at": "2026-04-19T00:00:00Z", "published_by": "admin",
            }
        return default
    mock_s3.get_json.side_effect = _get_json

    entries = service.list()
    assert len(entries) == 1
    assert entries[0]["slug"] == "pitch"
    assert entries[0]["name"] == "Pitch"
    assert entries[0]["version"] == 3


@pytest.mark.asyncio
async def test_deploy_extracts_tar_merges_config_writes_sidecar(
    service, mock_s3, mock_workspace, mock_patch_config
):
    def _get_json(key, default=None):
        if key == "catalog.json":
            return {"agents": [{"slug": "pitch", "current_version": 3, "manifest_url": "pitch/v3/manifest.json"}]}
        if key == "pitch/v3/manifest.json":
            return {"slug": "pitch", "version": 3, "name": "Pitch"}
        if key == "pitch/v3/openclaw-slice.json":
            return {
                "agent": {"name": "Pitch", "skills": ["web-search"]},
                "plugins": {"memory": {"enabled": True}},
                "tools": {"allowed": ["web-search"]},
            }
        return default
    mock_s3.get_json.side_effect = _get_json
    mock_s3.get_bytes.return_value = _tar_with({"./IDENTITY.md": b"name: Pitch\n"})

    result = await service.deploy(user_id="user_u", slug="pitch")

    assert result["slug"] == "pitch"
    assert result["agent_id"]  # UUID generated
    assert result["skills_added"] == ["web-search"]

    mock_workspace.extract_tarball_to_workspace.assert_called_once()
    _, kwargs = mock_workspace.extract_tarball_to_workspace.call_args
    assert kwargs["user_id"] == "user_u"

    mock_patch_config.assert_awaited_once()
    args, _ = mock_patch_config.call_args
    owner_id, patch = args
    assert owner_id == "user_u"
    # Patch adds the agent to the agents list and merges plugins/tools.
    assert patch["agents"][0]["name"] == "Pitch"
    assert patch["agents"][0]["id"] == result["agent_id"]
    assert patch["agents"][0]["workspace"] == f".openclaw/workspaces/{result['agent_id']}"
    assert patch["plugins"] == {"memory": {"enabled": True}}


@pytest.mark.asyncio
async def test_deploy_unknown_slug_raises(service, mock_s3):
    mock_s3.get_json.return_value = {"agents": []}
    with pytest.raises(KeyError):
        await service.deploy(user_id="user_u", slug="ghost")


@pytest.mark.asyncio
async def test_deploy_writes_template_sidecar(
    service, mock_s3, mock_workspace, mock_patch_config, tmp_path
):
    def _get_json(key, default=None):
        if key == "catalog.json":
            return {"agents": [{"slug": "pitch", "current_version": 3, "manifest_url": "pitch/v3/manifest.json"}]}
        if key == "pitch/v3/manifest.json":
            return {"slug": "pitch", "version": 3, "name": "Pitch"}
        if key == "pitch/v3/openclaw-slice.json":
            return {"agent": {"name": "Pitch"}, "plugins": {}, "tools": {}}
        return default
    mock_s3.get_json.side_effect = _get_json
    mock_s3.get_bytes.return_value = _tar_with({"./IDENTITY.md": b"hi"})

    # Capture sidecar write
    sidecar_written = {}
    def _write_sidecar(user_id, agent_id, content):
        sidecar_written["user_id"] = user_id
        sidecar_written["agent_id"] = agent_id
        sidecar_written["content"] = content
    mock_workspace.write_template_sidecar = _write_sidecar

    result = await service.deploy(user_id="user_u", slug="pitch")
    assert sidecar_written["user_id"] == "user_u"
    assert sidecar_written["agent_id"] == result["agent_id"]
    assert sidecar_written["content"]["template_slug"] == "pitch"
    assert sidecar_written["content"]["template_version"] == 3
```

This test assumes a `Workspace.write_template_sidecar(user_id, agent_id, content: dict)` helper which we'll add in Step 3 below.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && uv run pytest tests/unit/test_catalog_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.services.catalog_service'`.

- [ ] **Step 3: Add `Workspace.write_template_sidecar` helper**

In `apps/backend/core/containers/workspace.py`, alongside `read_template_sidecar`:

```python
def write_template_sidecar(
    self,
    user_id: str,
    agent_id: str,
    content: dict,
) -> None:
    sidecar = self.user_path(user_id) / "workspaces" / agent_id / ".template"
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(json.dumps(content))
    self._chown_for_access_point(sidecar, user_id)
```

- [ ] **Step 4: Implement the service**

Create `apps/backend/core/services/catalog_service.py`:

```python
"""Catalog service — publish, list, deploy.

Depends on injected collaborators so unit tests can mock them:
  - s3: CatalogS3Client
  - workspace: Workspace (from core.containers.workspace)
  - patch_openclaw_config: async callable (from core.services.config_patcher)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable


class CatalogService:
    def __init__(
        self,
        *,
        s3,
        workspace,
        patch_openclaw_config: Callable[[str, dict], Awaitable[None]],
    ):
        self._s3 = s3
        self._workspace = workspace
        self._patch = patch_openclaw_config

    # ---- list ----

    def list(self) -> list[dict[str, Any]]:
        catalog = self._s3.get_json("catalog.json", default={"agents": []})
        entries: list[dict[str, Any]] = []
        for item in catalog.get("agents") or []:
            manifest = self._s3.get_json(item["manifest_url"], default=None)
            if not manifest:
                continue
            entries.append({
                "slug": manifest["slug"],
                "version": manifest["version"],
                "name": manifest.get("name", manifest["slug"]),
                "emoji": manifest.get("emoji", ""),
                "vibe": manifest.get("vibe", ""),
                "description": manifest.get("description", ""),
                "suggested_model": manifest.get("suggested_model", ""),
                "suggested_channels": manifest.get("suggested_channels", []),
                "required_skills": manifest.get("required_skills", []),
                "required_plugins": manifest.get("required_plugins", []),
            })
        return entries

    # ---- deploy ----

    async def deploy(self, *, user_id: str, slug: str) -> dict[str, Any]:
        catalog = self._s3.get_json("catalog.json", default={"agents": []})
        match = next((a for a in catalog.get("agents") or [] if a.get("slug") == slug), None)
        if not match:
            raise KeyError(f"catalog entry not found: {slug!r}")

        manifest = self._s3.get_json(match["manifest_url"])
        slice_key = match["manifest_url"].replace("manifest.json", "openclaw-slice.json")
        slice_ = self._s3.get_json(slice_key)

        workspace_key = match["manifest_url"].replace("manifest.json", "workspace.tar.gz")
        tar_bytes = self._s3.get_bytes(workspace_key)

        new_agent_id = f"agent_{uuid.uuid4().hex[:12]}"

        self._workspace.extract_tarball_to_workspace(
            user_id=user_id,
            agent_id=new_agent_id,
            tar_bytes=tar_bytes,
        )

        # Build the openclaw.json patch: append the agent entry with its new id
        # and workspace path; merge plugins/tools.
        agent_entry = dict(slice_.get("agent") or {})
        agent_entry["id"] = new_agent_id
        agent_entry["workspace"] = f".openclaw/workspaces/{new_agent_id}"
        patch: dict[str, Any] = {
            "agents": [agent_entry],
            "plugins": slice_.get("plugins") or {},
            "tools": slice_.get("tools") or {},
        }

        await self._patch(user_id, patch)

        self._workspace.write_template_sidecar(
            user_id=user_id,
            agent_id=new_agent_id,
            content={
                "template_slug": slug,
                "template_version": manifest["version"],
                "deployed_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        return {
            "slug": slug,
            "version": manifest["version"],
            "agent_id": new_agent_id,
            "name": manifest.get("name", slug),
            "skills_added": list(agent_entry.get("skills") or []),
            "plugins_enabled": list((slice_.get("plugins") or {}).keys()),
        }
```

Important: the existing `config_patcher._deep_merge` replaces lists rather than concatenating (`result[key] = copy.deepcopy(value)` for non-dict values). So passing `{"agents": [new_entry]}` would wipe the user's existing agents. To avoid this, we read the current config, compute the merged agents list ourselves, and pass the full list in the patch — `_deep_merge` stays untouched.

Add a `Workspace.read_openclaw_config` helper **in this task** (Task 8, not deferred to Task 9) in `apps/backend/core/containers/workspace.py` next to `read_template_sidecar`:

```python
def read_openclaw_config(self, user_id: str) -> dict | None:
    path = self.user_path(user_id) / "openclaw.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
```

Then adjust the `deploy()` body just before calling `self._patch`:

```python
current = self._workspace.read_openclaw_config(user_id) or {}
existing_agents = list(current.get("agents") or [])
patch["agents"] = existing_agents + [agent_entry]
```

The test in Step 1 asserts `patch["agents"][0]["name"] == "Pitch"` — with an empty mocked `read_openclaw_config` (which MagicMock returns by default as a MagicMock object, truthy, with `.get("agents")` → MagicMock). Update the `mock_workspace` fixture to make that return `{}`:

```python
mock_workspace.read_openclaw_config.return_value = {}
```

Add this line inside `mock_workspace` fixture so every test starts clean.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd apps/backend && uv run pytest tests/unit/test_catalog_service.py -v`
Expected: 4 passed. (You may need to add `pytest-asyncio` if not already a dep: `uv add --dev pytest-asyncio` and mark tests with `@pytest.mark.asyncio`.)

- [ ] **Step 6: Commit**

```bash
git add apps/backend/core/services/catalog_service.py apps/backend/core/containers/workspace.py apps/backend/tests/unit/test_catalog_service.py
git commit -m "backend(catalog): service with list and deploy"
```

---

## Task 9: Backend — catalog service `publish()`

**Files:**
- Modify: `apps/backend/core/services/catalog_service.py`
- Modify: `apps/backend/tests/unit/test_catalog_service.py`

- [ ] **Step 1: Write the failing test**

Append to `apps/backend/tests/unit/test_catalog_service.py`:

```python
@pytest.mark.asyncio
async def test_publish_reads_admin_efs_and_uploads_package(
    service, mock_s3, mock_workspace, tmp_path
):
    # Admin's openclaw.json returned by workspace.
    mock_workspace.read_openclaw_config.return_value = {
        "agents": [
            {
                "id": "agent_admin_pitch",
                "workspace": ".openclaw/workspaces/agent_admin_pitch",
                "name": "Pitch",
                "emoji": "🎯",
                "vibe": "Direct",
                "model": "qwen/qwen3-vl-235b",
                "skills": ["web-search"],
                "channels": {"telegram": {"bot_token": "SECRET"}},
            }
        ],
        "plugins": {"memory": {"enabled": True}},
        "tools": {"allowed": ["web-search"]},
    }
    # Admin's agent workspace on disk.
    admin_workspace = tmp_path / "admin_ws"
    admin_workspace.mkdir()
    (admin_workspace / "IDENTITY.md").write_text(
        "name: Pitch\nemoji: 🎯\nvibe: Direct\n"
    )
    mock_workspace.agent_workspace_path.return_value = admin_workspace

    # No prior versions published.
    mock_s3.list_versions.return_value = []
    mock_s3.get_json.return_value = {"agents": []}

    result = await service.publish(
        admin_user_id="user_admin",
        agent_id="agent_admin_pitch",
        description_override=None,
    )

    assert result["slug"] == "pitch"
    assert result["version"] == 1

    # Manifest was uploaded.
    put_json_keys = [c.args[0] for c in mock_s3.put_json.call_args_list]
    assert "pitch/v1/manifest.json" in put_json_keys
    assert "pitch/v1/openclaw-slice.json" in put_json_keys
    assert "catalog.json" in put_json_keys

    # Tarball was uploaded.
    put_bytes_keys = [c.args[0] for c in mock_s3.put_bytes.call_args_list]
    assert "pitch/v1/workspace.tar.gz" in put_bytes_keys

    # Slice stripped channels/model/workspace/id.
    slice_call = next(c for c in mock_s3.put_json.call_args_list if c.args[0] == "pitch/v1/openclaw-slice.json")
    slice_json = slice_call.args[1]
    assert "model" not in slice_json["agent"]
    assert "channels" not in slice_json["agent"]
    assert "workspace" not in slice_json["agent"]
    assert "id" not in slice_json["agent"]


@pytest.mark.asyncio
async def test_publish_bumps_version_when_prior_exists(service, mock_s3, mock_workspace, tmp_path):
    mock_workspace.read_openclaw_config.return_value = {
        "agents": [{"id": "a1", "name": "Pitch", "skills": []}],
        "plugins": {}, "tools": {},
    }
    admin_workspace = tmp_path / "admin_ws"
    admin_workspace.mkdir()
    (admin_workspace / "IDENTITY.md").write_text("name: Pitch\n")
    mock_workspace.agent_workspace_path.return_value = admin_workspace
    mock_s3.list_versions.return_value = [1, 2, 5]
    mock_s3.get_json.return_value = {"agents": []}

    result = await service.publish(admin_user_id="admin", agent_id="a1")
    assert result["version"] == 6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && uv run pytest tests/unit/test_catalog_service.py::test_publish_reads_admin_efs_and_uploads_package -v`
Expected: FAIL with `AttributeError: 'CatalogService' object has no attribute 'publish'`.

- [ ] **Step 3: Add `agent_workspace_path` helper**

`read_openclaw_config` was already added in Task 8. Now add the remaining helper in `apps/backend/core/containers/workspace.py`:

```python
def agent_workspace_path(self, user_id: str, agent_id: str) -> Path:
    return self.user_path(user_id) / "workspaces" / agent_id
```

- [ ] **Step 4: Implement `publish()`**

Add to `apps/backend/core/services/catalog_service.py` (imports at the top, method inside the class):

```python
# Top of file, new imports:
from core.services.catalog_package import build_manifest, tar_directory
from core.services.catalog_slice import extract_agent_slice


# Inside the CatalogService class:
async def publish(
    self,
    *,
    admin_user_id: str,
    agent_id: str,
    slug_override: str | None = None,
    description_override: str | None = None,
) -> dict[str, Any]:
    config = self._workspace.read_openclaw_config(admin_user_id)
    if not config:
        raise FileNotFoundError(f"admin {admin_user_id} has no openclaw.json")

    slice_ = extract_agent_slice(config, agent_id)
    agent_entry_raw = next(
        a for a in config["agents"] if a.get("id") == agent_id
    )

    # Pull identity metadata from the raw (pre-strip) entry for the manifest.
    name = agent_entry_raw.get("name") or agent_id
    slug = (slug_override or name).strip().lower().replace(" ", "-")

    prior_versions = self._s3.list_versions(slug)
    next_version = (max(prior_versions) + 1) if prior_versions else 1

    manifest = build_manifest(
        slug=slug,
        version=next_version,
        name=name,
        emoji=agent_entry_raw.get("emoji", ""),
        vibe=agent_entry_raw.get("vibe", ""),
        description=description_override or agent_entry_raw.get("description", ""),
        suggested_model=agent_entry_raw.get("model", ""),
        suggested_channels=list((agent_entry_raw.get("channels") or {}).keys()),
        required_skills=list(agent_entry_raw.get("skills") or []),
        required_plugins=list((slice_.get("plugins") or {}).keys()),
        required_tools=list((slice_.get("tools") or {}).get("allowed") or []),
        published_by=admin_user_id,
    )

    workspace_dir = self._workspace.agent_workspace_path(admin_user_id, agent_id)
    tar_bytes = tar_directory(workspace_dir)

    prefix = f"{slug}/v{next_version}"
    self._s3.put_bytes(f"{prefix}/workspace.tar.gz", tar_bytes, content_type="application/gzip")
    self._s3.put_json(f"{prefix}/manifest.json", manifest)
    self._s3.put_json(f"{prefix}/openclaw-slice.json", slice_)

    # Update catalog.json atomically.
    catalog = self._s3.get_json("catalog.json", default={"agents": []})
    entries = [e for e in (catalog.get("agents") or []) if e.get("slug") != slug]
    entries.append({
        "slug": slug,
        "current_version": next_version,
        "manifest_url": f"{prefix}/manifest.json",
    })
    self._s3.put_json(
        "catalog.json",
        {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "agents": entries,
        },
    )

    return {"slug": slug, "version": next_version, "s3_prefix": prefix}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd apps/backend && uv run pytest tests/unit/test_catalog_service.py -v`
Expected: 6 passed (4 existing + 2 new).

- [ ] **Step 6: Commit**

```bash
git add apps/backend/core/services/catalog_service.py apps/backend/core/containers/workspace.py apps/backend/tests/unit/test_catalog_service.py
git commit -m "backend(catalog): service publish flow"
```

---

## Task 10: Backend — wire a singleton and construct it from settings

**Files:**
- Modify: `apps/backend/core/services/catalog_service.py`

- [ ] **Step 1: Add module-level `get_catalog_service()` singleton**

Append to `apps/backend/core/services/catalog_service.py`:

```python
_catalog_service: CatalogService | None = None


def get_catalog_service() -> CatalogService:
    global _catalog_service
    if _catalog_service is not None:
        return _catalog_service

    from core.config import settings
    from core.containers import get_workspace
    from core.services.catalog_s3_client import CatalogS3Client
    from core.services.config_patcher import patch_openclaw_config

    if not settings.AGENT_CATALOG_BUCKET:
        raise RuntimeError("AGENT_CATALOG_BUCKET is not configured")

    _catalog_service = CatalogService(
        s3=CatalogS3Client(bucket_name=settings.AGENT_CATALOG_BUCKET),
        workspace=get_workspace(),
        patch_openclaw_config=patch_openclaw_config,
    )
    return _catalog_service
```

- [ ] **Step 2: Commit**

```bash
git add apps/backend/core/services/catalog_service.py
git commit -m "backend(catalog): service singleton constructor"
```

---

## Task 11: Backend — catalog routers (user-facing + admin)

**Files:**
- Create: `apps/backend/routers/catalog.py`
- Create: `apps/backend/routers/admin_catalog.py`
- Test: `apps/backend/tests/unit/test_routers_catalog.py`
- Modify: `apps/backend/main.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/unit/test_routers_catalog.py`:

```python
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from main import app
from core.auth import AuthContext, get_current_user, require_platform_admin
from core.services.catalog_service import get_catalog_service


def _override_user(user_id: str):
    def _dep() -> AuthContext:
        return AuthContext(user_id=user_id)
    return _dep


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def mock_service():
    svc = MagicMock()
    app.dependency_overrides[get_catalog_service] = lambda: svc
    yield svc
    app.dependency_overrides.pop(get_catalog_service, None)


def test_list_returns_catalog_entries(client, mock_service):
    app.dependency_overrides[get_current_user] = _override_user("user_a")
    mock_service.list.return_value = [
        {"slug": "pitch", "name": "Pitch", "version": 3, "emoji": "🎯", "vibe": "Direct",
         "description": "Sales", "suggested_model": "qwen", "suggested_channels": [],
         "required_skills": ["web-search"], "required_plugins": ["memory"]}
    ]
    r = client.get("/api/v1/catalog")
    assert r.status_code == 200
    assert r.json()["agents"][0]["slug"] == "pitch"
    app.dependency_overrides.pop(get_current_user, None)


def test_deploy_returns_new_agent_id(client, mock_service):
    app.dependency_overrides[get_current_user] = _override_user("user_a")
    mock_service.deploy = AsyncMock(return_value={
        "slug": "pitch", "version": 3, "agent_id": "agent_xyz",
        "name": "Pitch", "skills_added": ["web-search"], "plugins_enabled": ["memory"],
    })
    r = client.post("/api/v1/catalog/deploy", json={"slug": "pitch"})
    assert r.status_code == 200
    assert r.json()["agent_id"] == "agent_xyz"
    mock_service.deploy.assert_awaited_once_with(user_id="user_a", slug="pitch")
    app.dependency_overrides.pop(get_current_user, None)


def test_deploy_missing_slug_400(client, mock_service):
    app.dependency_overrides[get_current_user] = _override_user("user_a")
    r = client.post("/api/v1/catalog/deploy", json={})
    assert r.status_code == 422  # FastAPI body validation
    app.dependency_overrides.pop(get_current_user, None)


def test_deployed_lists_user_agent_template_provenance(client, mock_service):
    app.dependency_overrides[get_current_user] = _override_user("user_a")
    mock_service.list_deployed_for_user = MagicMock(return_value=[
        {"agent_id": "agent_1", "template_slug": "pitch", "template_version": 3},
    ])
    r = client.get("/api/v1/catalog/deployed")
    assert r.status_code == 200
    assert r.json()["deployed"][0]["template_slug"] == "pitch"
    app.dependency_overrides.pop(get_current_user, None)


def test_publish_requires_platform_admin(client, mock_service):
    # Non-admin → 403. Override require_platform_admin to raise.
    from fastapi import HTTPException

    def _deny() -> AuthContext:
        raise HTTPException(status_code=403, detail="Platform admin access required")
    app.dependency_overrides[require_platform_admin] = _deny

    r = client.post("/api/v1/admin/catalog/publish", json={"agent_id": "a1"})
    assert r.status_code == 403
    app.dependency_overrides.pop(require_platform_admin, None)


def test_publish_happy_path(client, mock_service):
    app.dependency_overrides[require_platform_admin] = lambda: AuthContext(user_id="user_admin")
    mock_service.publish = AsyncMock(return_value={"slug": "pitch", "version": 4, "s3_prefix": "pitch/v4"})
    r = client.post("/api/v1/admin/catalog/publish", json={"agent_id": "agent_abc"})
    assert r.status_code == 200
    assert r.json()["version"] == 4
    mock_service.publish.assert_awaited_once()
    app.dependency_overrides.pop(require_platform_admin, None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && uv run pytest tests/unit/test_routers_catalog.py -v`
Expected: FAIL with `ModuleNotFoundError` on `routers.catalog` / `routers.admin_catalog`.

- [ ] **Step 3: Add `list_deployed_for_user` to the service**

Append inside `CatalogService` in `catalog_service.py`:

```python
def list_deployed_for_user(self, user_id: str) -> list[dict[str, Any]]:
    """Scan the user's workspaces for .template sidecars; return provenance."""
    deployed = []
    for agent_id in self._workspace.list_agents(user_id):
        sidecar = self._workspace.read_template_sidecar(user_id, agent_id)
        if sidecar:
            deployed.append({
                "agent_id": agent_id,
                "template_slug": sidecar.get("template_slug"),
                "template_version": sidecar.get("template_version"),
            })
    return deployed
```

- [ ] **Step 4: Implement the user-facing router**

Create `apps/backend/routers/catalog.py`:

```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.auth import AuthContext, get_current_user
from core.services.catalog_service import CatalogService, get_catalog_service


router = APIRouter(prefix="/catalog", tags=["catalog"])


class DeployRequest(BaseModel):
    slug: str


@router.get("")
async def list_catalog(
    _: AuthContext = Depends(get_current_user),
    service: CatalogService = Depends(get_catalog_service),
) -> dict:
    return {"agents": service.list()}


@router.post("/deploy")
async def deploy(
    req: DeployRequest,
    auth: AuthContext = Depends(get_current_user),
    service: CatalogService = Depends(get_catalog_service),
) -> dict:
    return await service.deploy(user_id=auth.user_id, slug=req.slug)


@router.get("/deployed")
async def list_deployed(
    auth: AuthContext = Depends(get_current_user),
    service: CatalogService = Depends(get_catalog_service),
) -> dict:
    return {"deployed": service.list_deployed_for_user(auth.user_id)}
```

- [ ] **Step 5: Implement the admin router**

Create `apps/backend/routers/admin_catalog.py`:

```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.auth import AuthContext, require_platform_admin
from core.services.catalog_service import CatalogService, get_catalog_service


router = APIRouter(prefix="/admin/catalog", tags=["admin", "catalog"])


class PublishRequest(BaseModel):
    agent_id: str
    slug: str | None = None
    description: str | None = None


@router.post("/publish")
async def publish(
    req: PublishRequest,
    auth: AuthContext = Depends(require_platform_admin),
    service: CatalogService = Depends(get_catalog_service),
) -> dict:
    return await service.publish(
        admin_user_id=auth.user_id,
        agent_id=req.agent_id,
        slug_override=req.slug,
        description_override=req.description,
    )
```

- [ ] **Step 6: Register both routers in `main.py`**

Locate the existing `app.include_router(...)` calls in `apps/backend/main.py` and add:

```python
from routers import catalog as catalog_router
from routers import admin_catalog as admin_catalog_router

app.include_router(catalog_router.router, prefix="/api/v1")
app.include_router(admin_catalog_router.router, prefix="/api/v1")
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd apps/backend && uv run pytest tests/unit/test_routers_catalog.py -v`
Expected: 6 passed.

- [ ] **Step 8: Commit**

```bash
git add apps/backend/routers/catalog.py apps/backend/routers/admin_catalog.py apps/backend/core/services/catalog_service.py apps/backend/main.py apps/backend/tests/unit/test_routers_catalog.py
git commit -m "backend(catalog): user-facing and admin routers"
```

---

## Task 12: Publish script

**Files:**
- Create: `scripts/publish-agent.sh`

- [ ] **Step 1: Write the script**

Create `scripts/publish-agent.sh`:

```bash
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
```

- [ ] **Step 2: Make executable**

Run: `chmod +x scripts/publish-agent.sh`

- [ ] **Step 3: Commit**

```bash
git add scripts/publish-agent.sh
git commit -m "scripts: publish-agent.sh calling /admin/catalog/publish"
```

---

## Task 13: Frontend — `useCatalog` hook

**Files:**
- Create: `apps/frontend/src/hooks/useCatalog.ts`
- Test: `apps/frontend/tests/unit/hooks/useCatalog.test.ts`

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/tests/unit/hooks/useCatalog.test.ts`:

```typescript
import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { SWRConfig } from "swr";

import { useCatalog } from "@/hooks/useCatalog";

const mockGet = vi.fn();
const mockPost = vi.fn();

vi.mock("@/lib/api", () => ({
  useApi: () => ({ get: mockGet, post: mockPost }),
}));

function wrapper({ children }: { children: React.ReactNode }) {
  return <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>{children}</SWRConfig>;
}

describe("useCatalog", () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPost.mockReset();
  });

  it("fetches catalog agents and deployed provenance in parallel", async () => {
    mockGet.mockImplementation((path: string) => {
      if (path === "/catalog") {
        return Promise.resolve({
          agents: [{ slug: "pitch", name: "Pitch", version: 3, emoji: "🎯",
                     vibe: "Direct", description: "Sales", suggested_model: "qwen",
                     suggested_channels: [], required_skills: [], required_plugins: [] }],
        });
      }
      if (path === "/catalog/deployed") {
        return Promise.resolve({ deployed: [] });
      }
      throw new Error(`Unexpected GET ${path}`);
    });

    const { result } = renderHook(() => useCatalog(), { wrapper });
    await waitFor(() => expect(result.current.agents.length).toBe(1));
    expect(result.current.agents[0].slug).toBe("pitch");
  });

  it("filters out agents already deployed", async () => {
    mockGet.mockImplementation((path: string) => {
      if (path === "/catalog") {
        return Promise.resolve({
          agents: [
            { slug: "pitch", name: "Pitch", version: 3, emoji: "", vibe: "",
              description: "", suggested_model: "", suggested_channels: [],
              required_skills: [], required_plugins: [] },
            { slug: "echo", name: "Echo", version: 1, emoji: "", vibe: "",
              description: "", suggested_model: "", suggested_channels: [],
              required_skills: [], required_plugins: [] },
          ],
        });
      }
      if (path === "/catalog/deployed") {
        return Promise.resolve({
          deployed: [{ agent_id: "agent_1", template_slug: "pitch", template_version: 3 }],
        });
      }
      throw new Error();
    });

    const { result } = renderHook(() => useCatalog(), { wrapper });
    await waitFor(() => expect(result.current.agents.length).toBe(1));
    expect(result.current.agents[0].slug).toBe("echo");
  });

  it("deploy() posts and triggers revalidation", async () => {
    mockGet.mockImplementation((path: string) => {
      if (path === "/catalog") return Promise.resolve({ agents: [] });
      if (path === "/catalog/deployed") return Promise.resolve({ deployed: [] });
      throw new Error();
    });
    mockPost.mockResolvedValue({ agent_id: "agent_new", slug: "pitch", version: 3, skills_added: [] });

    const { result } = renderHook(() => useCatalog(), { wrapper });
    await waitFor(() => expect(result.current.agents).toBeDefined());

    let deployResult;
    await act(async () => {
      deployResult = await result.current.deploy("pitch");
    });
    expect(mockPost).toHaveBeenCalledWith("/catalog/deploy", { slug: "pitch" });
    expect(deployResult).toMatchObject({ agent_id: "agent_new" });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/frontend && pnpm test tests/unit/hooks/useCatalog.test.ts`
Expected: FAIL with module resolution error on `@/hooks/useCatalog`.

- [ ] **Step 3: Implement**

Create `apps/frontend/src/hooks/useCatalog.ts`:

```typescript
import useSWR from "swr";
import { useCallback, useMemo } from "react";

import { useApi } from "@/lib/api";

export interface CatalogAgent {
  slug: string;
  name: string;
  version: number;
  emoji: string;
  vibe: string;
  description: string;
  suggested_model: string;
  suggested_channels: string[];
  required_skills: string[];
  required_plugins: string[];
}

export interface DeployedAgent {
  agent_id: string;
  template_slug: string;
  template_version: number;
}

export interface DeployResult {
  slug: string;
  version: number;
  agent_id: string;
  name: string;
  skills_added: string[];
  plugins_enabled: string[];
}

export function useCatalog() {
  const api = useApi();

  const { data: catalogData, mutate: mutateCatalog } = useSWR<{ agents: CatalogAgent[] }>(
    "/catalog",
    () => api.get("/catalog") as Promise<{ agents: CatalogAgent[] }>,
  );
  const { data: deployedData, mutate: mutateDeployed } = useSWR<{ deployed: DeployedAgent[] }>(
    "/catalog/deployed",
    () => api.get("/catalog/deployed") as Promise<{ deployed: DeployedAgent[] }>,
  );

  const deployedSlugs = useMemo(
    () => new Set((deployedData?.deployed ?? []).map((d) => d.template_slug)),
    [deployedData],
  );

  const visibleAgents = useMemo(
    () => (catalogData?.agents ?? []).filter((a) => !deployedSlugs.has(a.slug)),
    [catalogData, deployedSlugs],
  );

  const deploy = useCallback(
    async (slug: string): Promise<DeployResult> => {
      const result = (await api.post("/catalog/deploy", { slug })) as DeployResult;
      await Promise.all([mutateCatalog(), mutateDeployed()]);
      return result;
    },
    [api, mutateCatalog, mutateDeployed],
  );

  return {
    agents: visibleAgents,
    isLoading: !catalogData || !deployedData,
    deploy,
    refresh: () => Promise.all([mutateCatalog(), mutateDeployed()]),
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/frontend && pnpm test tests/unit/hooks/useCatalog.test.ts`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/hooks/useCatalog.ts apps/frontend/tests/unit/hooks/useCatalog.test.ts
git commit -m "frontend(catalog): useCatalog hook"
```

---

## Task 14: Frontend — `GalleryItemRow` component

**Files:**
- Create: `apps/frontend/src/components/chat/GalleryItemRow.tsx`
- Test: `apps/frontend/tests/unit/components/chat/GalleryItemRow.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/tests/unit/components/chat/GalleryItemRow.test.tsx`:

```tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { GalleryItemRow } from "@/components/chat/GalleryItemRow";

const baseAgent = {
  slug: "pitch",
  name: "Pitch",
  version: 3,
  emoji: "🎯",
  vibe: "Direct",
  description: "Sales",
  suggested_model: "qwen",
  suggested_channels: [],
  required_skills: [],
  required_plugins: [],
};

describe("GalleryItemRow", () => {
  it("renders name and emoji", () => {
    render(<GalleryItemRow agent={baseAgent} onDeploy={vi.fn()} onOpenInfo={vi.fn()} />);
    expect(screen.getByText("Pitch")).toBeInTheDocument();
    expect(screen.getByText("🎯")).toBeInTheDocument();
  });

  it("calls onDeploy when + clicked", async () => {
    const onDeploy = vi.fn().mockResolvedValue(undefined);
    render(<GalleryItemRow agent={baseAgent} onDeploy={onDeploy} onOpenInfo={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: /deploy/i }));
    expect(onDeploy).toHaveBeenCalledWith("pitch");
  });

  it("calls onOpenInfo when i clicked", async () => {
    const onOpenInfo = vi.fn();
    render(<GalleryItemRow agent={baseAgent} onDeploy={vi.fn()} onOpenInfo={onOpenInfo} />);
    await userEvent.click(screen.getByRole("button", { name: /info/i }));
    expect(onOpenInfo).toHaveBeenCalledWith(baseAgent);
  });

  it("disables deploy button while in-flight", async () => {
    let resolve!: () => void;
    const onDeploy = vi.fn(() => new Promise<void>((r) => { resolve = r; }));
    render(<GalleryItemRow agent={baseAgent} onDeploy={onDeploy} onOpenInfo={vi.fn()} />);
    const btn = screen.getByRole("button", { name: /deploy/i });
    userEvent.click(btn);
    await vi.waitFor(() => expect(btn).toBeDisabled());
    resolve();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/frontend && pnpm test tests/unit/components/chat/GalleryItemRow.test.tsx`
Expected: module not found.

- [ ] **Step 3: Implement**

Create `apps/frontend/src/components/chat/GalleryItemRow.tsx`:

```tsx
"use client";

import { Info, Loader2, Plus } from "lucide-react";
import { useState } from "react";

import type { CatalogAgent } from "@/hooks/useCatalog";

interface GalleryItemRowProps {
  agent: CatalogAgent;
  onDeploy: (slug: string) => Promise<unknown>;
  onOpenInfo: (agent: CatalogAgent) => void;
}

export function GalleryItemRow({ agent, onDeploy, onOpenInfo }: GalleryItemRowProps) {
  const [deploying, setDeploying] = useState(false);

  const handleDeploy = async () => {
    setDeploying(true);
    try {
      await onDeploy(agent.slug);
    } finally {
      setDeploying(false);
    }
  };

  return (
    <div className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-neutral-800">
      <span className="text-lg" aria-hidden>{agent.emoji || "🤖"}</span>
      <span className="flex-1 text-sm text-neutral-200 truncate">{agent.name}</span>
      <button
        type="button"
        aria-label={`Deploy ${agent.name}`}
        onClick={handleDeploy}
        disabled={deploying}
        className="p-1 rounded hover:bg-neutral-700 disabled:opacity-50"
      >
        {deploying ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
      </button>
      <button
        type="button"
        aria-label={`Info about ${agent.name}`}
        onClick={() => onOpenInfo(agent)}
        className="p-1 rounded hover:bg-neutral-700"
      >
        <Info className="w-4 h-4" />
      </button>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/frontend && pnpm test tests/unit/components/chat/GalleryItemRow.test.tsx`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/components/chat/GalleryItemRow.tsx apps/frontend/tests/unit/components/chat/GalleryItemRow.test.tsx
git commit -m "frontend(catalog): GalleryItemRow component"
```

---

## Task 15: Frontend — `AgentDetailPanel` component

**Files:**
- Create: `apps/frontend/src/components/chat/AgentDetailPanel.tsx`

- [ ] **Step 1: Implement**

Create `apps/frontend/src/components/chat/AgentDetailPanel.tsx`:

```tsx
"use client";

import { X } from "lucide-react";

import type { CatalogAgent } from "@/hooks/useCatalog";

interface AgentDetailPanelProps {
  agent: CatalogAgent | null;
  onClose: () => void;
  onDeploy: (slug: string) => Promise<unknown>;
}

export function AgentDetailPanel({ agent, onClose, onDeploy }: AgentDetailPanelProps) {
  if (!agent) return null;

  return (
    <aside className="fixed right-0 top-0 h-full w-96 bg-neutral-900 border-l border-neutral-800 p-6 overflow-y-auto">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-4xl mb-2">{agent.emoji || "🤖"}</div>
          <h2 className="text-xl font-semibold text-neutral-100">{agent.name}</h2>
          <p className="text-sm text-neutral-400 mt-1">v{agent.version}</p>
        </div>
        <button
          type="button"
          aria-label="Close"
          onClick={onClose}
          className="p-1 rounded hover:bg-neutral-800"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      {agent.vibe && (
        <section className="mt-6">
          <h3 className="text-xs uppercase tracking-wide text-neutral-500 mb-1">Vibe</h3>
          <p className="text-sm text-neutral-200">{agent.vibe}</p>
        </section>
      )}

      {agent.description && (
        <section className="mt-4">
          <h3 className="text-xs uppercase tracking-wide text-neutral-500 mb-1">About</h3>
          <p className="text-sm text-neutral-200">{agent.description}</p>
        </section>
      )}

      {agent.suggested_model && (
        <section className="mt-4">
          <h3 className="text-xs uppercase tracking-wide text-neutral-500 mb-1">Designed for</h3>
          <p className="text-sm text-neutral-200">
            Model: {agent.suggested_model}
            <br />
            <span className="text-xs text-neutral-500">
              Your tier's default model will be used when you deploy.
            </span>
          </p>
        </section>
      )}

      {agent.suggested_channels.length > 0 && (
        <section className="mt-4">
          <h3 className="text-xs uppercase tracking-wide text-neutral-500 mb-1">Suggested channels</h3>
          <div className="flex flex-wrap gap-1">
            {agent.suggested_channels.map((c) => (
              <span key={c} className="text-xs px-2 py-0.5 rounded bg-neutral-800 text-neutral-300">{c}</span>
            ))}
          </div>
        </section>
      )}

      {agent.required_skills.length > 0 && (
        <section className="mt-4">
          <h3 className="text-xs uppercase tracking-wide text-neutral-500 mb-1">Skills it will enable</h3>
          <div className="flex flex-wrap gap-1">
            {agent.required_skills.map((s) => (
              <span key={s} className="text-xs px-2 py-0.5 rounded bg-neutral-800 text-neutral-300">{s}</span>
            ))}
          </div>
        </section>
      )}

      <button
        type="button"
        onClick={() => onDeploy(agent.slug).then(onClose)}
        className="mt-6 w-full py-2 rounded bg-indigo-600 hover:bg-indigo-500 text-white font-medium"
      >
        Deploy {agent.name}
      </button>
    </aside>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add apps/frontend/src/components/chat/AgentDetailPanel.tsx
git commit -m "frontend(catalog): AgentDetailPanel component"
```

---

## Task 16: Frontend — `GallerySection` component

**Files:**
- Create: `apps/frontend/src/components/chat/GallerySection.tsx`
- Test: `apps/frontend/tests/unit/components/chat/GallerySection.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/tests/unit/components/chat/GallerySection.test.tsx`:

```tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { GallerySection } from "@/components/chat/GallerySection";

const deployMock = vi.fn().mockResolvedValue({ agent_id: "agent_new", name: "Pitch" });
const refreshMock = vi.fn();

vi.mock("@/hooks/useCatalog", () => ({
  useCatalog: () => ({
    agents: [
      { slug: "pitch", name: "Pitch", version: 3, emoji: "🎯", vibe: "", description: "",
        suggested_model: "", suggested_channels: [], required_skills: [], required_plugins: [] },
    ],
    isLoading: false,
    deploy: deployMock,
    refresh: refreshMock,
  }),
}));

vi.mock("@/hooks/useAgents", () => ({
  useAgents: () => ({ refresh: refreshMock }),
}));

describe("GallerySection", () => {
  it("renders the header and each agent row", () => {
    render(<GallerySection onAgentDeployed={vi.fn()} />);
    expect(screen.getByText(/gallery/i)).toBeInTheDocument();
    expect(screen.getByText("Pitch")).toBeInTheDocument();
  });

  it("calls onAgentDeployed with new agent info after deploy", async () => {
    const onAgentDeployed = vi.fn();
    render(<GallerySection onAgentDeployed={onAgentDeployed} />);
    await userEvent.click(screen.getByRole("button", { name: /deploy pitch/i }));
    await vi.waitFor(() => expect(onAgentDeployed).toHaveBeenCalled());
    expect(onAgentDeployed.mock.calls[0][0]).toMatchObject({ agent_id: "agent_new" });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/frontend && pnpm test tests/unit/components/chat/GallerySection.test.tsx`
Expected: module resolution error.

- [ ] **Step 3: Implement**

Create `apps/frontend/src/components/chat/GallerySection.tsx`:

```tsx
"use client";

import { useState } from "react";

import { AgentDetailPanel } from "@/components/chat/AgentDetailPanel";
import { GalleryItemRow } from "@/components/chat/GalleryItemRow";
import { useAgents } from "@/hooks/useAgents";
import { useCatalog, type CatalogAgent, type DeployResult } from "@/hooks/useCatalog";

interface GallerySectionProps {
  onAgentDeployed?: (result: DeployResult) => void;
}

export function GallerySection({ onAgentDeployed }: GallerySectionProps) {
  const { agents, isLoading, deploy } = useCatalog();
  const { refresh: refreshAgents } = useAgents();
  const [selected, setSelected] = useState<CatalogAgent | null>(null);

  if (isLoading) return null;
  if (agents.length === 0) return null;

  const handleDeploy = async (slug: string) => {
    const result = await deploy(slug);
    await refreshAgents();
    onAgentDeployed?.(result);
    return result;
  };

  return (
    <>
      <div className="mt-4 border-t border-neutral-800 pt-3">
        <h3 className="px-2 text-xs uppercase tracking-wide text-neutral-500 mb-1">
          Gallery
        </h3>
        <div className="space-y-0.5">
          {agents.map((a) => (
            <GalleryItemRow
              key={a.slug}
              agent={a}
              onDeploy={handleDeploy}
              onOpenInfo={setSelected}
            />
          ))}
        </div>
      </div>
      <AgentDetailPanel
        agent={selected}
        onClose={() => setSelected(null)}
        onDeploy={handleDeploy}
      />
    </>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/frontend && pnpm test tests/unit/components/chat/GallerySection.test.tsx`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/components/chat/GallerySection.tsx apps/frontend/tests/unit/components/chat/GallerySection.test.tsx
git commit -m "frontend(catalog): GallerySection component"
```

---

## Task 17: Frontend — wire Gallery into the sidebar

**Files:**
- Modify: `apps/frontend/src/components/chat/ChatLayout.tsx`

- [ ] **Step 1: Locate the agents-list region**

Read `apps/frontend/src/components/chat/ChatLayout.tsx` end-to-end (it's ~200 lines). Find the JSX region that renders the user's agents list (look for where `useAgents()` output is mapped into icon buttons). This is where Gallery goes, immediately after.

- [ ] **Step 2: Render `<GallerySection />` below the user agents list**

Add the import at the top:

```tsx
import { GallerySection } from "@/components/chat/GallerySection";
```

Then, immediately after the closing tag of the user-agents loop in the sidebar JSX, add:

```tsx
<GallerySection
  onAgentDeployed={(result) => {
    toast.success(`Deployed ${result.name}. Enabled ${result.plugins_enabled.length} plugins.`);
    // If ChatLayout has a setActiveAgentId or equivalent, switch to the new agent:
    // setActiveAgentId(result.agent_id);
  }}
/>
```

If `toast` is not already imported in this file, use whichever toast library the app uses (grep for existing `toast(` calls; the codebase likely uses `sonner` or similar). If no toast helper exists, drop the toast and rely on the visual change in the agents list.

If there is an `onSelectAgent` / `setActiveAgentId` handler in scope, call it with `result.agent_id` so the user lands in the chat for the newly deployed agent.

- [ ] **Step 3: Smoke-check the dev server**

Run: `cd apps/frontend && pnpm run dev`

Open `http://localhost:3000/chat`, sign in, and verify: Gallery section renders under the agents list. If you have a local backend + mocked catalog (see Task 19), clicking `[+]` triggers a deploy; if the backend isn't wired yet, the click will fail but the UI will render.

Stop the dev server (Ctrl-C) after the smoke check.

- [ ] **Step 4: Commit**

```bash
git add apps/frontend/src/components/chat/ChatLayout.tsx
git commit -m "frontend(catalog): render GallerySection in sidebar"
```

---

## Task 18: Frontend — extend E2E journey with a deploy step

**Files:**
- Modify: `apps/frontend/tests/e2e/journey.spec.ts`

- [ ] **Step 1: Add the deploy step**

Open `apps/frontend/tests/e2e/journey.spec.ts` and locate the main journey test. Insert a new step after the user is signed in and their container is provisioned (grep for `container` / `onboarding` in the file to find the right place). Use the Playwright page fixture already in scope.

```typescript
// ---- Gallery deploy ----
await test.step("deploy an agent from the gallery", async () => {
  // Wait for Gallery section to render.
  await expect(page.getByText(/^gallery$/i)).toBeVisible({ timeout: 30_000 });

  // Pick the first gallery row. Deploy.
  const firstRow = page.locator('[aria-label^="Deploy "]').first();
  const deployedName = await firstRow.getAttribute("aria-label");
  await firstRow.click();

  // The row should disappear from Gallery (filtered by deployed slug).
  await expect(firstRow).toBeHidden({ timeout: 30_000 });

  // The deployed agent should appear in Your Agents.
  // The exact selector depends on how ChatLayout renders agent icons; adjust
  // accordingly once you've seen the live markup.
  if (deployedName) {
    const agentName = deployedName.replace(/^Deploy\s+/i, "");
    await expect(page.getByText(agentName)).toBeVisible();
  }
});
```

The exact selector for "agent appears in Your Agents" may need adjustment once you see the live DOM; update after the first run.

- [ ] **Step 2: Commit (don't run yet — the full E2E runs in verification)**

```bash
git add apps/frontend/tests/e2e/journey.spec.ts
git commit -m "test(e2e): add gallery deploy step to user journey"
```

---

## Task 19: Seed a local LocalStack catalog for development

**Files:**
- Create: `scripts/seed-local-catalog.py`

- [ ] **Step 1: Write the seed script**

This is a one-off convenience for local dev — lets you test the Gallery UI without running the full publish flow. Create `scripts/seed-local-catalog.py`:

```python
"""Seed the LocalStack agent catalog with a fixture agent.

Usage:
  AWS_ENDPOINT_URL=http://localhost:4566 AGENT_CATALOG_BUCKET=isol8-local-agent-catalog \
    uv run python scripts/seed-local-catalog.py

Requires LocalStack running with S3 enabled. Creates the bucket if absent.
"""
from __future__ import annotations

import io
import json
import os
import tarfile

import boto3

BUCKET = os.environ["AGENT_CATALOG_BUCKET"]
ENDPOINT = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566")

s3 = boto3.client("s3", endpoint_url=ENDPOINT, region_name="us-east-1",
                  aws_access_key_id="test", aws_secret_access_key="test")

try:
    s3.create_bucket(Bucket=BUCKET)
except s3.exceptions.BucketAlreadyOwnedByYou:
    pass

# Fixture tarball — a minimal workspace with IDENTITY.md.
buf = io.BytesIO()
with tarfile.open(fileobj=buf, mode="w:gz") as tf:
    data = b"name: Demo Pitch\nemoji: 🎯\nvibe: Direct\n"
    info = tarfile.TarInfo(name="./IDENTITY.md")
    info.size = len(data)
    tf.addfile(info, io.BytesIO(data))

s3.put_object(Bucket=BUCKET, Key="demo-pitch/v1/workspace.tar.gz", Body=buf.getvalue())
s3.put_object(
    Bucket=BUCKET,
    Key="demo-pitch/v1/manifest.json",
    Body=json.dumps({
        "slug": "demo-pitch", "version": 1, "name": "Demo Pitch", "emoji": "🎯",
        "vibe": "Direct, data-driven", "description": "A fixture for local dev.",
        "suggested_model": "minimax/minimax-m2.5", "suggested_channels": [],
        "required_skills": [], "required_plugins": [], "required_tools": [],
        "published_at": "2026-04-19T00:00:00Z", "published_by": "local-seed",
    }).encode(),
)
s3.put_object(
    Bucket=BUCKET,
    Key="demo-pitch/v1/openclaw-slice.json",
    Body=json.dumps({
        "agent": {"name": "Demo Pitch", "emoji": "🎯", "skills": []},
        "plugins": {}, "tools": {},
    }).encode(),
)
s3.put_object(
    Bucket=BUCKET,
    Key="catalog.json",
    Body=json.dumps({
        "updated_at": "2026-04-19T00:00:00Z",
        "agents": [
            {"slug": "demo-pitch", "current_version": 1, "manifest_url": "demo-pitch/v1/manifest.json"},
        ],
    }).encode(),
)
print("Seeded catalog in bucket", BUCKET)
```

- [ ] **Step 2: Commit**

```bash
git add scripts/seed-local-catalog.py
git commit -m "scripts: seed local LocalStack agent catalog"
```

---

## Task 20: Full verification

Verification task — no new code. Run the whole suite end-to-end to catch anything the per-task runs missed.

- [ ] **Step 1: Backend full test suite**

Run: `cd apps/backend && uv run pytest tests/ -v`
Expected: all green. If any unrelated tests fail, inspect — it may be a real regression from changes to `workspace.py` or `config_patcher.py` interactions.

- [ ] **Step 2: Frontend unit tests**

Run: `cd apps/frontend && pnpm test`
Expected: all green.

- [ ] **Step 3: Frontend lint**

Run: `cd apps/frontend && pnpm run lint`
Expected: exits 0.

- [ ] **Step 4: Frontend type-check**

Run: `cd apps/frontend && pnpm run build`
Expected: build succeeds. (TypeScript errors would block here.)

- [ ] **Step 5: Local E2E smoke**

With LocalStack running (`./scripts/local-dev.sh`), seed the catalog:

```bash
AWS_ENDPOINT_URL=http://localhost:4566 \
  AGENT_CATALOG_BUCKET=isol8-local-agent-catalog \
  uv run python scripts/seed-local-catalog.py
```

Ensure the backend env has `AGENT_CATALOG_BUCKET=isol8-local-agent-catalog`. Open the app, sign in, confirm Gallery shows "Demo Pitch", click `[+]`, confirm it deploys and appears in Your Agents.

- [ ] **Step 6: Playwright E2E**

Run: `cd apps/frontend && pnpm run test:e2e`
Expected: journey.spec.ts passes including the new deploy step.

- [ ] **Step 7: Final commit (if lint auto-fixed anything)**

```bash
git status
# If there are auto-fix changes:
git add -A && git commit -m "chore: lint autofix"
```

---

## Rollout notes (post-merge, out of scope for the plan)

1. Merge this branch.
2. Deploy CDK first (`cd apps/infra && pnpm cdk deploy ServiceStack`) to provision the S3 bucket and wire `AGENT_CATALOG_BUCKET` env var into the backend task definition.
3. Set `PLATFORM_ADMIN_USER_IDS` in AWS Secrets Manager / backend env — comma-separated Clerk user IDs of Isol8 team members who can publish.
4. Backend auto-deploys on merge.
5. Run `scripts/publish-agent.sh <agent_id>` for each of the 5 polished agents on the prod workbench account.
6. Verify the catalog in S3 and the Gallery UI for a non-admin user.
