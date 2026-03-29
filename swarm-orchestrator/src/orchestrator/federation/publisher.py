"""Federation publisher — encrypt and send summaries via GoToSocial."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx
import structlog

from orchestrator.federation.crypto import encrypt_for_nodes
from orchestrator.models.summary import SwarmSummary
from orchestrator.models.topology import Topology

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
