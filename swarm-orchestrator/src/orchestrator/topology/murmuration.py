"""Murmuration topology — self-organizing, Kademlia-XOR neighbor selection.

Each node derives a 160-bit identity from its X25519 public key (SHA1) and
selects up to 7 neighbors across 7 XOR-distance bands, mirroring the
topological interaction model observed in starling murmurations (STARFLAG
research: each bird tracks 6–7 nearest neighbors regardless of flock density).

The topology is dynamic: every R rounds the lowest-value neighbor is dropped
and replaced via friend-of-a-friend discovery (gossip rewiring).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import random
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from orchestrator.models.topology import SwarmNode, Topology

if TYPE_CHECKING:
    pass

log = structlog.get_logger()

# ── Message type constants ────────────────────────────────────────────────────

MSGTYPE_SUMMARY = "swarm:SwarmSummary"
MSGTYPE_NEIGHBOR_REQUEST = "swarm:NeighborRequest"
MSGTYPE_NEIGHBOR_RESPONSE = "swarm:NeighborResponse"
MSGTYPE_TOPOLOGY_QUERY = "swarm:TopologyQuery"
MSGTYPE_TOPOLOGY_RESPONSE = "swarm:TopologyResponse"
MSGTYPE_NEIGHBOR_BROADCAST = "swarm:NeighborBroadcast"

# ── Pure functions (stateless, easy to unit-test) ─────────────────────────────


def derive_node_id(public_key_b64: str) -> bytes:
    """Return SHA1(base64_decode(public_key)) — a 20-byte (160-bit) node ID."""
    pub_bytes = base64.b64decode(public_key_b64)
    return hashlib.sha1(pub_bytes).digest()  # noqa: S324


def xor_distance(a: bytes, b: bytes) -> int:
    """XOR distance between two equal-length byte strings, returned as an integer."""
    if len(a) != len(b):
        # Pad the shorter one with leading zeros
        max_len = max(len(a), len(b))
        a = a.rjust(max_len, b"\x00")
        b = b.rjust(max_len, b"\x00")
    return int.from_bytes(a, "big") ^ int.from_bytes(b, "big")


def kademlia_bucket(self_id: bytes, candidate_id: bytes) -> int:
    """Return the Kademlia bucket index for *candidate* relative to *self*.

    Bucket k = the highest set bit of XOR(self, candidate) is at position k
    counting from the MSB (0-indexed from the left in a 160-bit space).

    Convention:
        k = 0   → farthest  (MSB of XOR is set, distance ≥ 2^159)
        k = 159 → closest   (only the LSB of XOR differs, distance = 1)

    Returns -1 if self_id == candidate_id (distance 0, same node).
    """
    dist = xor_distance(self_id, candidate_id)
    if dist == 0:
        return -1
    # bit_length() gives the position of the highest set bit (1-indexed from LSB).
    # Convert to 0-indexed from MSB in a 160-bit space:
    #   if bit_length() == 160  → highest bit is at MSB → bucket 0
    #   if bit_length() == 1    → only LSB set          → bucket 159
    return 160 - dist.bit_length()


def select_neighbors_by_bands(
    self_id: bytes,
    candidates: list[SwarmNode],
    max_neighbors: int = 7,
) -> list[SwarmNode]:
    """Select up to *max_neighbors* nodes across XOR-distance bands.

    Band assignment (for max_neighbors = 7):
        Band 0:   Closest node overall (minimum XOR distance)
        Bands 1–5: Closest node in each of 5 distinct Kademlia buckets
        Band 6:   Random node from any remaining candidates (long-range link)

    For small swarms (fewer candidates than max_neighbors), all available
    candidates with a valid node_id are returned.

    Nodes with no public_key (node_id is None) are skipped.
    """
    # Filter candidates that have a usable node_id
    eligible = [n for n in candidates if n.node_id is not None]
    if not eligible:
        return []

    if len(eligible) <= max_neighbors:
        return list(eligible)

    selected: list[SwarmNode] = []
    selected_ids: set[str] = set()

    def _add(node: SwarmNode) -> None:
        if node.id not in selected_ids:
            selected.append(node)
            selected_ids.add(node.id)

    # Band 0: closest overall
    closest = min(eligible, key=lambda n: xor_distance(self_id, n.node_id))  # type: ignore[arg-type]
    _add(closest)

    # Bands 1–(max_neighbors-2): one node per Kademlia bucket
    num_bucket_bands = max_neighbors - 2  # e.g. 5 for max_neighbors=7
    remaining_by_bucket: dict[int, list[SwarmNode]] = {}
    for node in eligible:
        if node.id in selected_ids:
            continue
        bucket = kademlia_bucket(self_id, node.node_id)  # type: ignore[arg-type]
        remaining_by_bucket.setdefault(bucket, []).append(node)

    # Sort buckets from closest to farthest (highest bucket index = closest)
    sorted_buckets = sorted(remaining_by_bucket.keys(), reverse=True)
    for bucket in sorted_buckets:
        if len(selected) >= max_neighbors - 1:  # leave room for long-range
            break
        # Pick the closest node within this bucket
        bucket_nodes = remaining_by_bucket[bucket]
        best = min(bucket_nodes, key=lambda n: xor_distance(self_id, n.node_id))  # type: ignore[arg-type]
        _add(best)
        if len(selected) >= num_bucket_bands + 1:
            break

    # Band 6 (last slot): random long-range link from all remaining
    remaining = [n for n in eligible if n.id not in selected_ids]
    if remaining and len(selected) < max_neighbors:
        long_range = random.choice(remaining)  # noqa: S311
        _add(long_range)

    return selected


def compute_fingerprint(neighbor_ids: list[str]) -> str:
    """SHA256 of sorted, UTF-8 encoded neighbor IDs concatenated — hex string."""
    sorted_ids = sorted(neighbor_ids)
    data = b"".join(s.encode() for s in sorted_ids)
    return hashlib.sha256(data).hexdigest()


# ── Neighbor-protocol message constructors ────────────────────────────────────


def make_neighbor_request(from_node: SwarmNode) -> dict:
    """Build a NEIGHBOR_REQUEST payload."""
    return {
        "type": MSGTYPE_NEIGHBOR_REQUEST,
        "from_node_id": from_node.id,
        "from_name": from_node.name,
        "from_domain": from_node.domain,
        "from_public_key": from_node.public_key,
        "from_actor_uri": from_node.actor_uri,
    }


def make_neighbor_response(accepted: bool, reason: str = "") -> dict:
    """Build a NEIGHBOR_RESPONSE payload."""
    return {
        "type": MSGTYPE_NEIGHBOR_RESPONSE,
        "accepted": accepted,
        "reason": reason,
    }


def make_topology_query(from_node_id: str) -> dict:
    """Build a TOPOLOGY_QUERY payload (ask a neighbor to introduce a peer)."""
    return {
        "type": MSGTYPE_TOPOLOGY_QUERY,
        "from_node_id": from_node_id,
    }


def make_topology_response(neighbor: SwarmNode) -> dict:
    """Build a TOPOLOGY_RESPONSE payload."""
    return {
        "type": MSGTYPE_TOPOLOGY_RESPONSE,
        "neighbor_id": neighbor.id,
        "neighbor_name": neighbor.name,
        "neighbor_domain": neighbor.domain,
        "neighbor_public_key": neighbor.public_key,
        "neighbor_actor_uri": neighbor.actor_uri,
    }


def make_neighbor_broadcast(from_node_id: str, neighbors: list[SwarmNode]) -> dict:
    """Build a NEIGHBOR_BROADCAST payload announcing the current neighbor list."""
    return {
        "type": MSGTYPE_NEIGHBOR_BROADCAST,
        "from_node_id": from_node_id,
        "neighbors": [
            {
                "id": n.id,
                "name": n.name,
                "domain": n.domain,
                "public_key": n.public_key,
                "actor_uri": n.actor_uri,
            }
            for n in neighbors
        ],
    }


# ── MurmurationTopology ───────────────────────────────────────────────────────


class MurmurationTopology:
    """Drop-in replacement for :class:`Topology` with dynamic 7-neighbor management.

    The ``adjacent_nodes`` property returns the current live neighbor set (≤ 7
    nodes), making this backward-compatible with all existing callers that use
    ``topology.adjacent_nodes``, ``topology.self_node``, and ``topology.get_node()``.

    Neighbor selection follows the Kademlia-XOR band model:
    - Each node has a unique 160-bit position derived from its public key.
    - Neighbors are selected from 7 distance bands to ensure diverse coverage.
    - Every R rounds, the lowest-scoring neighbor is dropped and replaced via
      friend-of-a-friend discovery (the gossip "murmuration" phase).

    Zero-neighbor resilience:
    - If no seed nodes exist, the node starts as an island and waits.
    - All methods degrade gracefully to no-ops when the neighbor set is empty.
    """

    def __init__(
        self,
        seed_topology: Topology,
        self_public_key_b64: str,
        state_path: str,
        max_neighbors: int = 7,
    ) -> None:
        self._seed = seed_topology
        self._self_public_key_b64 = self_public_key_b64
        self._state_path = Path(state_path)
        self._max_neighbors = max_neighbors

        # Derive this node's 160-bit XOR keyspace position
        self._self_id: bytes = derive_node_id(self_public_key_b64)

        # Active neighbor set (≤ max_neighbors)
        self._neighbors: list[SwarmNode] = []
        # All nodes we've ever heard of (known but not necessarily active neighbors)
        self._known_nodes: dict[str, SwarmNode] = {}

        # Per-neighbor information-gain scores (0.0–1.0)
        # Tracks: how many unique key_positions a neighbor contributed
        self._neighbor_scores: dict[str, float] = {}
        self._neighbor_total_summaries: dict[str, int] = {}
        self._neighbor_unique_positions: dict[str, set[str]] = {}
        # Positions contributed by ANY neighbor this window (for novelty calc)
        self._all_seen_positions: set[str] = set()

        self._fingerprint: str = ""
        self._last_rewire_round: int = 0

    # ── Topology interface (backward-compatible with Topology) ─────────────

    @property
    def self_node(self) -> SwarmNode | None:
        """Return the local node (is_self=True)."""
        return self._seed.self_node

    @property
    def adjacent_nodes(self) -> list[SwarmNode]:
        """Current active neighbors (≤ max_neighbors)."""
        return list(self._neighbors)

    def get_node(self, node_id: str) -> SwarmNode | None:
        """Look up a node by string ID in neighbors + known set + seed topology."""
        for n in self._neighbors:
            if n.id == node_id:
                return n
        if node_id in self._known_nodes:
            return self._known_nodes[node_id]
        return self._seed.get_node(node_id)

    def validate_self_exists(self, self_node_id: str) -> None:
        """Delegate validation to the underlying seed topology."""
        self._seed.validate_self_exists(self_node_id)

    # ── Bootstrap ─────────────────────────────────────────────────────────

    def bootstrap(self) -> None:
        """Initialise the neighbor set.

        1. Try to load persisted state (from a previous run).
        2. If none exists, select neighbors from the seed topology via XOR bands.
        3. If the seed topology is also empty, start as an island (zero neighbors).
        """
        # Populate known_nodes from seed
        for node in self._seed.nodes:
            if not node.is_self:
                self._known_nodes[node.id] = node

        # Attempt to restore from persisted state
        if self.load_state():
            log.info(
                "murmuration.bootstrap_restored",
                neighbors=len(self._neighbors),
                fingerprint=self._fingerprint,
            )
            return

        # Fresh start: select from seed nodes
        seed_candidates = [
            n for n in self._seed.nodes
            if not n.is_self and n.role in ("participant", "facilitator")
        ]

        if not seed_candidates:
            log.info("murmuration.no_seed_nodes")
            self._fingerprint = compute_fingerprint([])
            return

        self._neighbors = select_neighbors_by_bands(
            self._self_id, seed_candidates, self._max_neighbors
        )
        self._fingerprint = compute_fingerprint([n.id for n in self._neighbors])
        self.save_state()

        log.info(
            "murmuration.bootstrap_complete",
            neighbors=len(self._neighbors),
            fingerprint=self._fingerprint,
        )

    # ── Information-gain scoring ──────────────────────────────────────────

    def record_inbound_summary(self, node_id: str, summary_text: str) -> None:
        """Track how novel a neighbor's contribution is.

        Novelty = unique key_positions the neighbor introduced that no other
        neighbor contributed in the same round window.  The score is:
            score = cumulative_novel_positions / total_summaries_received
        """
        self._neighbor_total_summaries[node_id] = (
            self._neighbor_total_summaries.get(node_id, 0) + 1
        )

        # Extract a rough set of "positions" from the summary text — split on
        # sentence boundaries as a proxy for distinct claims.
        positions = {
            s.strip()
            for s in summary_text.replace(";", ".").split(".")
            if len(s.strip()) > 10
        }

        if node_id not in self._neighbor_unique_positions:
            self._neighbor_unique_positions[node_id] = set()

        novel = positions - self._all_seen_positions
        self._neighbor_unique_positions[node_id].update(novel)
        self._all_seen_positions.update(positions)

        total = self._neighbor_total_summaries[node_id]
        unique = len(self._neighbor_unique_positions[node_id])
        self._neighbor_scores[node_id] = unique / max(total, 1)

    def _score_of(self, node_id: str) -> float:
        """Return the current info-gain score for a neighbor (default 0.5)."""
        return self._neighbor_scores.get(node_id, 0.5)

    # ── Rewiring ─────────────────────────────────────────────────────────

    def rewire(
        self,
        known_candidates: list[SwarmNode] | None = None,
    ) -> tuple[str | None, str | None]:
        """Perform one murmuration rewire cycle.

        1. DROP the neighbor with the lowest info-gain score.
        2. Return (dropped_node_id, query_node_id) so the caller can send
           an async TOPOLOGY_QUERY to *query_node_id* via ActivityPub.

        The actual CONNECT step happens in :meth:`add_candidate` after the
        async TOPOLOGY_RESPONSE arrives.

        Returns (None, None) when there are no neighbors (solo mode).
        """
        if not self._neighbors:
            log.info("murmuration.rewire_skipped_no_neighbors")
            return None, None

        # Update known_nodes with any new candidates provided
        if known_candidates:
            self.update_known_nodes(known_candidates)

        # Find the lowest-scoring neighbor
        worst = min(self._neighbors, key=lambda n: self._score_of(n.id))
        self._neighbors = [n for n in self._neighbors if n.id != worst.id]

        # Clean up score tracking for dropped node
        self._neighbor_scores.pop(worst.id, None)
        self._neighbor_total_summaries.pop(worst.id, None)
        self._neighbor_unique_positions.pop(worst.id, None)

        log.info(
            "murmuration.rewire_dropped",
            dropped=worst.id,
            score=self._score_of(worst.id),
        )

        # Pick a random remaining neighbor to ask for a friend-of-friend
        query_node_id: str | None = None
        if self._neighbors:
            query_node = random.choice(self._neighbors)  # noqa: S311
            query_node_id = query_node.id

        self._fingerprint = compute_fingerprint([n.id for n in self._neighbors])
        return worst.id, query_node_id

    def add_candidate(self, candidate: SwarmNode) -> bool:
        """Evaluate and potentially add a discovered candidate to the neighbor set.

        Rules:
        - Skip if the candidate has no public_key.
        - Skip if already an active neighbor.
        - If below capacity (< max_neighbors), add unconditionally.
        - If at capacity, check if the candidate belongs to a band that currently
          has no representative — if so, replace the lowest-scoring neighbor.
        Returns True if the candidate was added.
        """
        if not candidate.public_key:
            return False
        if any(n.id == candidate.id for n in self._neighbors):
            return False

        if len(self._neighbors) < self._max_neighbors:
            self._neighbors.append(candidate)
            self._known_nodes[candidate.id] = candidate
            self._fingerprint = compute_fingerprint([n.id for n in self._neighbors])
            log.info("murmuration.candidate_added", candidate=candidate.id)
            return True

        # At capacity — check if the candidate opens a new band
        if candidate.node_id is None:
            return False

        existing_buckets = {
            kademlia_bucket(self._self_id, n.node_id)
            for n in self._neighbors
            if n.node_id is not None
        }
        candidate_bucket = kademlia_bucket(self._self_id, candidate.node_id)

        if candidate_bucket not in existing_buckets:
            # New band — replace the lowest-scoring current neighbor
            worst = min(self._neighbors, key=lambda n: self._score_of(n.id))
            self._neighbors = [n for n in self._neighbors if n.id != worst.id]
            self._neighbors.append(candidate)
            self._known_nodes[candidate.id] = candidate
            self._fingerprint = compute_fingerprint([n.id for n in self._neighbors])
            log.info(
                "murmuration.candidate_replaced",
                candidate=candidate.id,
                replaced=worst.id,
                bucket=candidate_bucket,
            )
            return True

        return False

    def update_known_nodes(self, nodes: list[SwarmNode]) -> None:
        """Merge newly-learned nodes into the known-but-not-adjacent set."""
        for node in nodes:
            if not node.is_self:
                self._known_nodes[node.id] = node

    # ── Persistence ───────────────────────────────────────────────────────

    def save_state(self) -> None:
        """Persist the current neighbor set and scores to a JSON file."""
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            state = {
                "neighbors": [
                    {
                        "id": n.id,
                        "name": n.name,
                        "domain": n.domain,
                        "public_key": n.public_key,
                        "role": n.role,
                    }
                    for n in self._neighbors
                ],
                "known_nodes": [
                    {
                        "id": n.id,
                        "name": n.name,
                        "domain": n.domain,
                        "public_key": n.public_key,
                        "role": n.role,
                    }
                    for n in self._known_nodes.values()
                ],
                "neighbor_scores": dict(self._neighbor_scores),
                "fingerprint": self._fingerprint,
                "last_rewire_round": self._last_rewire_round,
            }
            self._state_path.write_text(json.dumps(state, indent=2))
            log.debug("murmuration.state_saved", path=str(self._state_path))
        except OSError as exc:
            log.warn("murmuration.state_save_failed", error=str(exc))

    def load_state(self) -> bool:
        """Load persisted state. Returns False if file missing or corrupt."""
        if not self._state_path.exists():
            return False
        try:
            data = json.loads(self._state_path.read_text())
            self._neighbors = [
                SwarmNode(**n) for n in data.get("neighbors", [])
            ]
            for n_data in data.get("known_nodes", []):
                node = SwarmNode(**n_data)
                self._known_nodes[node.id] = node
            self._neighbor_scores = data.get("neighbor_scores", {})
            self._fingerprint = data.get("fingerprint", "")
            self._last_rewire_round = data.get("last_rewire_round", 0)
            return True
        except Exception as exc:
            log.warn("murmuration.state_load_failed", error=str(exc))
            return False
