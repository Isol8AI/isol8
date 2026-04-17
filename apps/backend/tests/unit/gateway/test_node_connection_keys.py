"""Per-member device-key behavior for NodeUpstreamConnection."""

from pathlib import Path

import pytest


@pytest.fixture
def efs_root(tmp_path):
    """Fake EFS mount root with the owner dir pre-created."""
    root = tmp_path / "efs"
    root.mkdir()
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


def test_each_member_gets_a_distinct_device_key(efs_root):
    """Two members of the same org must resolve to DIFFERENT private keys
    (and therefore different nodeIds) — this is the whole point of scoping
    the key path by user_id instead of owner_id.
    """
    alice = _make_conn("user_alice", "org_1", efs_root)
    bob = _make_conn("user_bob", "org_1", efs_root)

    key_alice = alice._load_node_key()
    key_bob = bob._load_node_key()

    pub_alice = key_alice.public_key().public_bytes_raw()
    pub_bob = key_bob.public_key().public_bytes_raw()

    assert pub_alice != pub_bob, "org members must not share a device key"

    # Each key lands at its own path under the owner's tree.
    assert alice._device_key_path() != bob._device_key_path()
    assert alice._device_key_path().exists()
    assert bob._device_key_path().exists()


def test_same_member_reuses_existing_key(efs_root):
    """Reconnecting as the same member must read the same key back (stable
    nodeId across reconnects)."""
    alice1 = _make_conn("user_alice", "org_1", efs_root)
    alice2 = _make_conn("user_alice", "org_1", efs_root)

    pub1 = alice1._load_node_key().public_key().public_bytes_raw()
    pub2 = alice2._load_node_key().public_key().public_bytes_raw()

    assert pub1 == pub2, "same member must get the same key on reconnect"


def test_key_file_has_tight_permissions(efs_root):
    """Freshly generated keys must be 0600 — leaking to other local users
    is out of scope for an EFS-shared-across-backend deployment, but we
    still enforce tight perms defensively."""
    import os

    conn = _make_conn("user_alice", "org_1", efs_root)
    conn._load_node_key()

    mode = os.stat(conn._device_key_path()).st_mode & 0o777
    assert mode & 0o077 == 0, f"key perms too loose: {oct(mode)}"


def test_key_path_scoped_by_owner_and_user(efs_root):
    """Path layout: <efs>/<owner_id>/devices/<user_id>/.node-device-key.pem"""
    conn = _make_conn("user_alice", "org_1", efs_root)
    expected = efs_root / "org_1" / "devices" / "user_alice" / ".node-device-key.pem"
    assert conn._device_key_path() == expected
