"""Per-member device-key + paired.json registration for NodeUpstreamConnection.

These exercise the lazy-provisioning path that lets new org members connect
without manual re-provisioning of the container: on first connect the
backend generates a fresh key AND appends a node entry to paired.json so
OpenClaw's NOT_PAIRED gate lets the handshake through.
"""

import json
from pathlib import Path

import pytest


@pytest.fixture
def efs_root(tmp_path):
    """Fake EFS mount with an existing paired.json for the owner (as would
    have been written by ensure_device_identities at provision time)."""
    root = tmp_path / "efs"
    (root / "org_1" / "devices").mkdir(parents=True)
    # Seed with an existing operator entry so we can assert we don't clobber it.
    seed = {
        "operator-device-id-seed": {
            "deviceId": "operator-device-id-seed",
            "publicKey": "seed-pub",
            "role": "operator",
            "roles": ["operator"],
            "scopes": ["chat.send", "sessions.list"],
            "approvedScopes": ["chat.send", "sessions.list"],
        }
    }
    (root / "org_1" / "devices" / "paired.json").write_text(json.dumps(seed, indent=2))
    return root


def _make_conn(user_id: str, owner_id: str, efs_root: Path):
    from core.gateway.node_connection import NodeUpstreamConnection

    return NodeUpstreamConnection(
        user_id=user_id,
        owner_id=owner_id,
        container_ip="10.0.0.1",
        node_connect_params={},
        efs_mount_path=str(efs_root),
        gateway_token="tok",
    )


def _paired(efs_root: Path, owner_id: str) -> dict:
    return json.loads((efs_root / owner_id / "devices" / "paired.json").read_text())


def test_each_member_gets_distinct_device_key(efs_root):
    """Two members of the same org must resolve to DIFFERENT private keys."""
    alice = _make_conn("user_alice", "org_1", efs_root)
    bob = _make_conn("user_bob", "org_1", efs_root)

    key_alice = alice._load_node_key()
    key_bob = bob._load_node_key()

    pub_alice = key_alice.public_key().public_bytes_raw()
    pub_bob = key_bob.public_key().public_bytes_raw()

    assert pub_alice != pub_bob, "org members must not share a device key"
    assert alice._device_key_path() != bob._device_key_path()


def test_same_member_reuses_existing_key(efs_root):
    """Reconnect as the same member returns the same key (stable nodeId)."""
    a1 = _make_conn("user_alice", "org_1", efs_root)
    a2 = _make_conn("user_alice", "org_1", efs_root)
    assert a1._load_node_key().public_key().public_bytes_raw() == a2._load_node_key().public_key().public_bytes_raw()


def test_first_connect_registers_device_in_paired_json(efs_root):
    """_load_node_key must append a node entry for the new device_id."""
    alice = _make_conn("user_alice", "org_1", efs_root)
    alice._load_node_key()

    entries = _paired(efs_root, "org_1")
    # Seed operator entry still present.
    assert "operator-device-id-seed" in entries
    # A node entry was added. Exactly one new entry beyond the seed.
    node_entries = {k: v for k, v in entries.items() if v.get("role") == "node"}
    assert len(node_entries) == 1
    entry = next(iter(node_entries.values()))
    assert entry["role"] == "node"
    assert entry["roles"] == ["node"]
    assert entry["scopes"] == []
    assert "publicKey" in entry
    assert "createdAtMs" in entry


def test_two_members_both_registered(efs_root):
    """Both Alice and Bob end up in paired.json with distinct entries."""
    _make_conn("user_alice", "org_1", efs_root)._load_node_key()
    _make_conn("user_bob", "org_1", efs_root)._load_node_key()

    entries = _paired(efs_root, "org_1")
    node_entries = {k: v for k, v in entries.items() if v.get("role") == "node"}
    assert len(node_entries) == 2
    # Seed entry preserved.
    assert "operator-device-id-seed" in entries


def test_reconnect_does_not_duplicate_paired_entry(efs_root):
    """Calling _load_node_key twice must not add two entries for the same member."""
    alice = _make_conn("user_alice", "org_1", efs_root)
    alice._load_node_key()
    alice._load_node_key()

    entries = _paired(efs_root, "org_1")
    node_entries = [k for k, v in entries.items() if v.get("role") == "node"]
    assert len(node_entries) == 1, f"unexpected duplicates: {node_entries}"


def test_missing_paired_json_gets_created(tmp_path):
    """If paired.json doesn't exist (e.g. recovery path), registration
    creates it rather than crashing."""
    root = tmp_path / "efs"
    # Note: no paired.json here, just the bare EFS root.
    root.mkdir()
    alice = _make_conn("user_alice", "org_1", root)
    alice._load_node_key()

    paired = root / "org_1" / "devices" / "paired.json"
    assert paired.exists()
    entries = json.loads(paired.read_text())
    assert any(v.get("role") == "node" for v in entries.values())


def test_key_file_has_tight_permissions(efs_root):
    """Freshly generated keys must be 0600."""
    import os

    conn = _make_conn("user_alice", "org_1", efs_root)
    conn._load_node_key()
    mode = os.stat(conn._device_key_path()).st_mode & 0o777
    assert mode & 0o077 == 0, f"key perms too loose: {oct(mode)}"


def test_key_file_only_appears_when_fully_written(tmp_path, monkeypatch):
    """Regression: the previous O_EXCL implementation created the key file
    empty on open() then wrote content afterward, so a concurrent reader
    hitting exists()==True could read zero bytes and fail PEM parse.
    The fix uses tempfile+os.link, so the target path should only ever
    appear on disk containing the complete key."""
    import os as _os

    from core.gateway import node_connection as nc

    key_path = tmp_path / "efs" / "org" / "devices" / "user" / ".node-device-key.pem"

    # Snoop on os.link: between tempfile creation and link, the target
    # path must NOT exist. After link, it must exist and parse as PEM.
    original_link = _os.link
    observations = {"path_existed_before_link": None, "path_existed_after_link": None}

    def spy_link(src, dst, *a, **kw):
        observations["path_existed_before_link"] = _os.path.exists(dst)
        result = original_link(src, dst, *a, **kw)
        observations["path_existed_after_link"] = _os.path.exists(dst)
        return result

    monkeypatch.setattr(_os, "link", spy_link)

    nc._generate_member_device_key(key_path, "user_test")

    assert observations["path_existed_before_link"] is False, (
        "target must not exist before the atomic link — readers could otherwise race and read a partial file"
    )
    assert observations["path_existed_after_link"] is True
    # And the complete PEM parses correctly.
    pem = key_path.read_text(encoding="ascii")
    key = nc._load_private_key(pem)
    assert key is not None


def test_second_generator_for_same_path_is_noop(tmp_path):
    """Two concurrent first-connects must not leave duplicate/corrupt keys."""
    from core.gateway import node_connection as nc

    key_path = tmp_path / "efs" / "org" / "devices" / "user" / ".node-device-key.pem"

    nc._generate_member_device_key(key_path, "user_test")
    first = key_path.read_bytes()

    # Second call sees existing file and returns without touching it.
    nc._generate_member_device_key(key_path, "user_test")
    second = key_path.read_bytes()

    assert first == second, "second generate must not overwrite"


def test_concurrent_paired_json_writers_all_land(tmp_path):
    """Regression: fcntl.lockf is process-scoped, not thread-scoped. Two
    asyncio.to_thread workers in the same process could both pass the fcntl
    lock simultaneously and race the RMW, with os.rename dropping the other
    writer's entry. The fix adds a per-owner threading.Lock.

    This test runs N threads concurrently against the same owner's
    paired.json. Without the threading lock the number of entries landing
    is typically < N (last-writer-wins on rename). With the lock, all N
    entries land."""
    import concurrent.futures

    from core.containers.config import ensure_node_paired_entry

    root = tmp_path / "efs"
    root.mkdir()
    owner = "org_concurrent"

    N = 20

    def register(i: int) -> bool:
        return ensure_node_paired_entry(
            efs_mount_path=str(root),
            owner_id=owner,
            device_id=f"dev-{i:04d}",
            public_key_b64=f"pub-{i:04d}",
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=N) as ex:
        results = list(ex.map(register, range(N)))

    assert all(results), "every registration should have added a new entry"

    paired = json.loads((root / owner / "devices" / "paired.json").read_text())
    registered_ids = set(paired.keys())
    expected = {f"dev-{i:04d}" for i in range(N)}
    missing = expected - registered_ids
    assert not missing, f"{len(missing)} entries lost under concurrent RMW: {sorted(missing)[:5]}..."


def test_device_id_in_paired_matches_handshake_id(efs_root):
    """The device_id we register in paired.json must equal what
    _build_device_identity will compute — the gateway compares these."""
    import hashlib

    from core.gateway.node_connection import _build_device_identity

    conn = _make_conn("user_alice", "org_1", efs_root)
    pk = conn._load_node_key()

    identity = _build_device_identity(pk, nonce="test-nonce", connect_params={})
    # What gets sent on the wire as device.id
    wire_device_id = identity["id"]

    # What we registered in paired.json for alice
    entries = _paired(efs_root, "org_1")
    node_entries = {k: v for k, v in entries.items() if v.get("role") == "node"}
    registered_ids = set(node_entries.keys())

    assert wire_device_id in registered_ids, (
        "device_id sent on handshake must match a paired.json entry; otherwise OpenClaw rejects with NOT_PAIRED"
    )

    # And re-check the derivation ourselves — SHA256 of raw Ed25519 public key.
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    raw_pub = pk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    assert wire_device_id == hashlib.sha256(raw_pub).hexdigest()
