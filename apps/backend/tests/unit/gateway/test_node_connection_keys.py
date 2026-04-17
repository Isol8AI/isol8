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
