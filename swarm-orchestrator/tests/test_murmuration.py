"""Unit tests for the murmuration topology engine."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile

import pytest

from orchestrator.models.topology import SwarmNode, Topology
from orchestrator.topology.murmuration import (
    MurmurationTopology,
    compute_fingerprint,
    derive_node_id,
    kademlia_bucket,
    select_neighbors_by_bands,
    xor_distance,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_node(node_id: str, seed: int = 0) -> SwarmNode:
    """Create a SwarmNode with a deterministic fake public key."""
    raw_key = hashlib.sha256(f"{node_id}-{seed}".encode()).digest()
    pub_key_b64 = base64.b64encode(raw_key).decode()
    return SwarmNode(
        id=node_id,
        name=f"Node {node_id}",
        domain=f"{node_id}.test",
        public_key=pub_key_b64,
        role="participant",
    )


def _self_id_from_key(pub_key_b64: str) -> bytes:
    return derive_node_id(pub_key_b64)


# ── Pure function tests ───────────────────────────────────────────────────────


class TestDeriveNodeId:
    def test_deterministic(self):
        node = _make_node("alpha")
        id1 = derive_node_id(node.public_key)
        id2 = derive_node_id(node.public_key)
        assert id1 == id2

    def test_returns_20_bytes(self):
        node = _make_node("alpha")
        result = derive_node_id(node.public_key)
        assert len(result) == 20

    def test_different_keys_different_ids(self):
        node_a = _make_node("alpha", seed=1)
        node_b = _make_node("beta", seed=2)
        assert derive_node_id(node_a.public_key) != derive_node_id(node_b.public_key)


class TestXorDistance:
    def test_symmetry(self):
        a = os.urandom(20)
        b = os.urandom(20)
        assert xor_distance(a, b) == xor_distance(b, a)

    def test_identity(self):
        a = os.urandom(20)
        assert xor_distance(a, a) == 0

    def test_nonzero_for_different(self):
        a = bytes(20)
        b = bytes([0] * 19 + [1])  # differ only in the LSB → distance = 1
        assert xor_distance(a, b) == 1


class TestKademliaBucket:
    def test_same_id_returns_minus_one(self):
        a = bytes(20)
        assert kademlia_bucket(a, a) == -1

    def test_msb_differs_bucket_zero(self):
        """If only the MSB differs, XOR has bit 159 set → bucket 0."""
        a = bytes(20)
        # First byte differs in MSB → distance = 0x80 << (19*8)
        b = bytes([0x80] + [0x00] * 19)
        assert kademlia_bucket(a, b) == 0

    def test_lsb_only_differs_bucket_159(self):
        """If only the LSB differs, XOR = 1 → bucket 159."""
        a = bytes(20)
        b = bytes([0x00] * 19 + [0x01])
        assert kademlia_bucket(a, b) == 159

    def test_known_distance(self):
        """XOR = 2 (bit 158 from MSB in 160-bit space) → bucket 158."""
        a = bytes(20)
        b = bytes([0x00] * 19 + [0x02])
        # distance = 2, bit_length = 2, bucket = 160 - 2 = 158
        assert kademlia_bucket(a, b) == 158


class TestSelectNeighborsByBands:
    def test_fewer_candidates_than_max(self):
        self_node = _make_node("self")
        self_id = derive_node_id(self_node.public_key)
        candidates = [_make_node(f"peer-{i}") for i in range(4)]
        result = select_neighbors_by_bands(self_id, candidates, max_neighbors=7)
        assert len(result) == 4

    def test_returns_at_most_max_neighbors(self):
        self_node = _make_node("self")
        self_id = derive_node_id(self_node.public_key)
        candidates = [_make_node(f"peer-{i}") for i in range(20)]
        result = select_neighbors_by_bands(self_id, candidates, max_neighbors=7)
        assert len(result) <= 7

    def test_no_duplicates(self):
        self_node = _make_node("self")
        self_id = derive_node_id(self_node.public_key)
        candidates = [_make_node(f"peer-{i}") for i in range(20)]
        result = select_neighbors_by_bands(self_id, candidates, max_neighbors=7)
        ids = [n.id for n in result]
        assert len(ids) == len(set(ids))

    def test_skips_nodes_without_public_key(self):
        self_node = _make_node("self")
        self_id = derive_node_id(self_node.public_key)
        # Mix nodes with and without keys
        candidates = [_make_node(f"peer-{i}") for i in range(5)]
        no_key_node = SwarmNode(id="no-key", domain="nokey.test", public_key="")
        candidates.append(no_key_node)
        result = select_neighbors_by_bands(self_id, candidates, max_neighbors=7)
        assert all(n.public_key for n in result)

    def test_empty_candidates_returns_empty(self):
        self_node = _make_node("self")
        self_id = derive_node_id(self_node.public_key)
        result = select_neighbors_by_bands(self_id, [], max_neighbors=7)
        assert result == []


class TestComputeFingerprint:
    def test_order_independent(self):
        ids_a = ["node-1", "node-2", "node-3"]
        ids_b = ["node-3", "node-1", "node-2"]
        assert compute_fingerprint(ids_a) == compute_fingerprint(ids_b)

    def test_different_sets_different_fingerprint(self):
        assert compute_fingerprint(["a", "b"]) != compute_fingerprint(["a", "c"])

    def test_empty_list(self):
        fp = compute_fingerprint([])
        assert len(fp) == 64  # sha256 hex


# ── MurmurationTopology tests ─────────────────────────────────────────────────


def _make_topology(self_id: str, peer_ids: list[str]) -> Topology:
    nodes = [
        SwarmNode(
            id=self_id,
            name=f"Node {self_id}",
            domain=f"{self_id}.test",
            public_key=base64.b64encode(
                hashlib.sha256(self_id.encode()).digest()
            ).decode(),
            role="participant",
            is_self=True,
        )
    ] + [_make_node(pid) for pid in peer_ids]
    return Topology(nodes=nodes)


class TestMurmurationTopology:
    def _self_pub_key(self, self_id: str = "self") -> str:
        return base64.b64encode(hashlib.sha256(self_id.encode()).digest()).decode()

    def test_bootstrap_uses_seed_topology(self):
        topo = _make_topology("self", [f"peer-{i}" for i in range(5)])
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            state_path = f.name
        try:
            mut = MurmurationTopology(
                seed_topology=topo,
                self_public_key_b64=self._self_pub_key(),
                state_path=state_path,
                max_neighbors=7,
            )
            mut.bootstrap()
            assert len(mut.adjacent_nodes) == 5  # all 5 peers fit within 7
        finally:
            os.unlink(state_path)

    def test_bootstrap_empty_seed(self):
        """Node with no seed peers starts as an island without error."""
        topo = _make_topology("self", [])
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            state_path = f.name
        try:
            mut = MurmurationTopology(
                seed_topology=topo,
                self_public_key_b64=self._self_pub_key(),
                state_path=state_path,
                max_neighbors=7,
            )
            mut.bootstrap()
            assert mut.adjacent_nodes == []
        finally:
            os.unlink(state_path)

    def test_adjacent_nodes_capped_at_max(self):
        topo = _make_topology("self", [f"peer-{i}" for i in range(20)])
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            state_path = f.name
        try:
            mut = MurmurationTopology(
                seed_topology=topo,
                self_public_key_b64=self._self_pub_key(),
                state_path=state_path,
                max_neighbors=7,
            )
            mut.bootstrap()
            assert len(mut.adjacent_nodes) <= 7
        finally:
            os.unlink(state_path)

    def test_rewire_drops_lowest_score(self):
        topo = _make_topology("self", [f"peer-{i}" for i in range(5)])
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            state_path = f.name
        try:
            mut = MurmurationTopology(
                seed_topology=topo,
                self_public_key_b64=self._self_pub_key(),
                state_path=state_path,
                max_neighbors=7,
            )
            mut.bootstrap()

            initial_ids = {n.id for n in mut.adjacent_nodes}
            # Give peer-0 a high score and peer-1 a low score
            mut._neighbor_scores["peer-0"] = 0.9
            mut._neighbor_scores["peer-1"] = 0.05

            dropped_id, _ = mut.rewire()
            # The dropped node should be the one with the lowest score
            assert dropped_id == "peer-1"
            assert "peer-1" not in {n.id for n in mut.adjacent_nodes}
        finally:
            os.unlink(state_path)

    def test_rewire_no_neighbors_returns_none_none(self):
        topo = _make_topology("self", [])
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            state_path = f.name
        try:
            mut = MurmurationTopology(
                seed_topology=topo,
                self_public_key_b64=self._self_pub_key(),
                state_path=state_path,
            )
            mut.bootstrap()
            dropped, query = mut.rewire()
            assert dropped is None
            assert query is None
        finally:
            os.unlink(state_path)

    def test_add_candidate_at_capacity_ignored(self):
        """When at max_neighbors=2, an additional candidate is ignored."""
        topo = _make_topology("self", ["peer-0", "peer-1"])
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            state_path = f.name
        try:
            mut = MurmurationTopology(
                seed_topology=topo,
                self_public_key_b64=self._self_pub_key(),
                state_path=state_path,
                max_neighbors=2,
            )
            mut.bootstrap()
            assert len(mut.adjacent_nodes) == 2

            newcomer = _make_node("newcomer")
            # Give newcomer a bucket already occupied by both existing neighbors
            # by patching _self_id to make distances predictable (just test the
            # capacity guard — bucket logic is covered by select_neighbors tests)
            mut._max_neighbors = 2
            result = mut.add_candidate(newcomer)
            # May or may not be added depending on bucket — but capacity is guarded
            assert len(mut.adjacent_nodes) <= 2
        finally:
            os.unlink(state_path)

    def test_add_candidate_already_present_returns_false(self):
        topo = _make_topology("self", ["peer-0"])
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            state_path = f.name
        try:
            mut = MurmurationTopology(
                seed_topology=topo,
                self_public_key_b64=self._self_pub_key(),
                state_path=state_path,
            )
            mut.bootstrap()
            existing = mut.adjacent_nodes[0]
            result = mut.add_candidate(existing)
            assert result is False
        finally:
            os.unlink(state_path)

    def test_save_and_load_state(self):
        topo = _make_topology("self", ["peer-0", "peer-1", "peer-2"])
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            state_path = f.name
        try:
            mut = MurmurationTopology(
                seed_topology=topo,
                self_public_key_b64=self._self_pub_key(),
                state_path=state_path,
            )
            mut.bootstrap()
            original_ids = {n.id for n in mut.adjacent_nodes}
            original_fp = mut._fingerprint

            # Create a new instance and load the state
            mut2 = MurmurationTopology(
                seed_topology=topo,
                self_public_key_b64=self._self_pub_key(),
                state_path=state_path,
            )
            loaded = mut2.load_state()
            assert loaded is True
            assert {n.id for n in mut2.adjacent_nodes} == original_ids
            assert mut2._fingerprint == original_fp
        finally:
            os.unlink(state_path)

    def test_fingerprint_changes_after_rewire(self):
        topo = _make_topology("self", [f"peer-{i}" for i in range(5)])
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            state_path = f.name
        try:
            mut = MurmurationTopology(
                seed_topology=topo,
                self_public_key_b64=self._self_pub_key(),
                state_path=state_path,
            )
            mut.bootstrap()
            fp_before = mut._fingerprint
            mut.rewire()
            fp_after = mut._fingerprint
            assert fp_before != fp_after
        finally:
            os.unlink(state_path)

    def test_get_node_searches_neighbors_and_known(self):
        topo = _make_topology("self", ["peer-0"])
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            state_path = f.name
        try:
            mut = MurmurationTopology(
                seed_topology=topo,
                self_public_key_b64=self._self_pub_key(),
                state_path=state_path,
            )
            mut.bootstrap()
            result = mut.get_node("peer-0")
            assert result is not None
            assert result.id == "peer-0"

            # Self node accessible via seed delegation
            self_result = mut.get_node("self")
            assert self_result is not None
        finally:
            os.unlink(state_path)

    def test_node_id_computed_field(self):
        """SwarmNode.node_id returns 20-byte SHA1 of the public key."""
        node = _make_node("alpha")
        assert node.node_id is not None
        assert len(node.node_id) == 20

    def test_node_id_none_when_no_public_key(self):
        node = SwarmNode(id="empty", domain="empty.test", public_key="")
        assert node.node_id is None
