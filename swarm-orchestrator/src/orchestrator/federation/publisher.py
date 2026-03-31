"""Federation publisher — encrypt and send summaries via GoToSocial."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx
import structlog

from orchestrator.federation.crypto import encrypt_for_nodes
from orchestrator.models.summary import SwarmSummary
from orchestrator.models.topology import SwarmNode, Topology
from orchestrator.topology.murmuration import (
    make_neighbor_broadcast,
    make_neighbor_request,
    make_neighbor_response,
    make_topology_query,
    make_topology_response,
)

if TYPE_CHECKING:
    from orchestrator.config import FederationConfig

log = structlog.get_logger()

_SWARM_DELIMITER_START = "<!--SWARM:"
_SWARM_DELIMITER_END = ":SWARM-->"


_MAX_PENDING_RETRIES = 50


class FederationPublisher:
    """Publishes encrypted summaries to adjacent nodes via GoToSocial."""

    def __init__(
        self,
        config: "FederationConfig",
        http_client: httpx.AsyncClient,
    ) -> None:
        self._config = config
        self._http = http_client
        self._base_url = config.gotosocial_url
        self._pending: list[tuple[SwarmSummary, Topology]] = []

    async def publish(self, summary: SwarmSummary, topology: Topology) -> None:
        """Encrypt and send a summary to all adjacent nodes."""
        adjacent = topology.adjacent_nodes
        if not adjacent:
            log.info("publisher.no_adjacent_nodes")
            return

        # Serialize to JSON-LD
        jsonld = summary.to_jsonld()
        plaintext = json.dumps(jsonld).encode()

        # Encrypt for each recipient
        encrypted = encrypt_for_nodes(plaintext, adjacent)

        for node in adjacent:
            if node.id not in encrypted:
                continue
            ciphertext_b64 = encrypted[node.id]
            await self._send_dm(summary, topology, node.actor_uri, node.id, ciphertext_b64)

    async def _send_dm(  # noqa: PLR0913
        self,
        summary: SwarmSummary,
        topology: Topology,
        actor_uri: str,
        target_node_id: str,
        ciphertext_b64: str,
    ) -> None:
        """Post an encrypted summary as a direct message via GoToSocial."""
        # Extract actor handle from URI for the mention
        # URI format: https://domain/users/node-id
        parts = actor_uri.rstrip("/").split("/")
        username = parts[-1]
        domain = parts[2]
        mention = f"@{username}@{domain}"

        status_text = (
            f"\U0001f41d Swarm Summary Round {summary.round_number} "
            f"from {summary.source_node_id}\n\n"
            f"{mention}\n\n"
            f"{_SWARM_DELIMITER_START}{ciphertext_b64}{_SWARM_DELIMITER_END}"
        )

        try:
            resp = await self._http.post(
                f"{self._base_url}/api/v1/statuses",
                headers={"Authorization": f"Bearer {self._config.access_token}"},
                json={
                    "status": status_text,
                    "visibility": "direct",
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            log.info(
                "publisher.sent",
                target=target_node_id,
                round=summary.round_number,
            )
        except httpx.HTTPError as exc:
            log.error(
                "publisher.send_failed",
                target=target_node_id,
                error=str(exc),
            )
            # Queue for retry with original topology (bounded to prevent memory exhaustion)
            if len(self._pending) < _MAX_PENDING_RETRIES:
                self._pending.append((summary, topology))
            else:
                log.warn("publisher.retry_queue_full", dropped_summary=summary.summary_id())

    async def retry_pending(self) -> None:
        """Retry any queued failed deliveries."""
        if not self._pending:
            return
        pending = list(self._pending)
        self._pending.clear()
        for summary, topology in pending:
            log.info("publisher.retry", summary_id=summary.summary_id())
            await self.publish(summary, topology)

    # ── Neighbor-protocol messages ────────────────────────────────────────

    async def _send_topology_msg(
        self,
        target: SwarmNode,
        self_node: SwarmNode,
        payload: dict,
        label: str,
    ) -> None:
        """Encrypt *payload* for *target* and send as a direct message."""
        plaintext = json.dumps(payload).encode()
        encrypted = encrypt_for_nodes(plaintext, [target])
        if target.id not in encrypted:
            log.warn("publisher.topology_msg_encrypt_failed", target=target.id, label=label)
            return
        ciphertext_b64 = encrypted[target.id]
        # Reuse the existing _send_dm transport with a dummy SwarmSummary-like label
        parts = target.actor_uri.rstrip("/").split("/")
        username = parts[-1]
        domain = parts[2]
        mention = f"@{username}@{domain}"
        status_text = (
            f"\U0001f41d Swarm Topology [{label}] "
            f"from {self_node.id}\n\n"
            f"{mention}\n\n"
            f"{_SWARM_DELIMITER_START}{ciphertext_b64}{_SWARM_DELIMITER_END}"
        )
        try:
            resp = await self._http.post(
                f"{self._base_url}/api/v1/statuses",
                headers={"Authorization": f"Bearer {self._config.access_token}"},
                json={"status": status_text, "visibility": "direct"},
                timeout=30.0,
            )
            resp.raise_for_status()
            log.info("publisher.topology_msg_sent", target=target.id, label=label)
        except httpx.HTTPError as exc:
            log.error(
                "publisher.topology_msg_failed",
                target=target.id,
                label=label,
                error=str(exc),
            )

    async def send_neighbor_request(
        self, target: SwarmNode, self_node: SwarmNode
    ) -> None:
        """Send a NEIGHBOR_REQUEST DM to *target*."""
        payload = make_neighbor_request(self_node)
        await self._send_topology_msg(target, self_node, payload, "NeighborRequest")

    async def send_neighbor_response(
        self, target: SwarmNode, accepted: bool, self_node: SwarmNode
    ) -> None:
        """Reply to a NEIGHBOR_REQUEST."""
        payload = make_neighbor_response(accepted)
        await self._send_topology_msg(target, self_node, payload, "NeighborResponse")

    async def send_topology_query(
        self, target: SwarmNode, self_node: SwarmNode
    ) -> None:
        """Ask *target* for one of its neighbors (friend-of-a-friend discovery)."""
        payload = make_topology_query(self_node.id)
        await self._send_topology_msg(target, self_node, payload, "TopologyQuery")

    async def send_topology_response(
        self, target: SwarmNode, peer: SwarmNode, self_node: SwarmNode
    ) -> None:
        """Reply to a TOPOLOGY_QUERY with one of our active neighbors."""
        payload = make_topology_response(peer)
        await self._send_topology_msg(target, self_node, payload, "TopologyResponse")

    async def send_neighbor_broadcast(
        self,
        recipients: list[SwarmNode],
        self_node: SwarmNode,
        current_neighbors: list[SwarmNode],
    ) -> None:
        """Broadcast the updated neighbor list to all current neighbors."""
        if not recipients:
            return
        payload = make_neighbor_broadcast(self_node.id, current_neighbors)
        for target in recipients:
            await self._send_topology_msg(
                target, self_node, payload, "NeighborBroadcast"
            )
