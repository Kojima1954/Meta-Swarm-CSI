"""Federation subscriber — poll GoToSocial for inbound swarm summaries."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

import httpx
import structlog
from nacl.public import PrivateKey

from orchestrator.federation.crypto import decrypt
from orchestrator.models.summary import SwarmSummary
from orchestrator.models.topology import Topology
from orchestrator.topology.murmuration import (
    MSGTYPE_NEIGHBOR_BROADCAST,
    MSGTYPE_NEIGHBOR_REQUEST,
    MSGTYPE_NEIGHBOR_RESPONSE,
    MSGTYPE_SUMMARY,
    MSGTYPE_TOPOLOGY_QUERY,
    MSGTYPE_TOPOLOGY_RESPONSE,
)

if TYPE_CHECKING:
    from orchestrator.config import FederationConfig

log = structlog.get_logger()

_SWARM_PATTERN = re.compile(r"<!--SWARM:(.*?):SWARM-->", re.DOTALL)

# Maximum size of a decrypted payload (1 MB) — prevents memory exhaustion
_MAX_PAYLOAD_BYTES = 1_048_576


class FederationSubscriber:
    """Polls GoToSocial notifications for encrypted inbound summaries.

    In addition to :class:`SwarmSummary` payloads, the subscriber also handles
    murmuration neighbor-protocol messages.  These are collected into three lists
    that the round controller drains during each rewire cycle:

        neighbor_requests  — list of (sender_actor_uri, payload_dict)
        topology_queries   — list of (sender_actor_uri, payload_dict)
        topology_messages  — list of payload_dict (responses / broadcasts)
    """

    def __init__(
        self,
        config: "FederationConfig",
        http_client: httpx.AsyncClient,
        private_key: PrivateKey,
        topology: Topology,
    ) -> None:
        self._config = config
        self._http = http_client
        self._private_key = private_key
        self._topology = topology
        self._last_notification_id: str | None = None

        # Murmuration neighbor-protocol queues (drained by RoundController)
        self.neighbor_requests: list[tuple[str, dict]] = []
        self.topology_queries: list[tuple[str, dict]] = []
        self.topology_messages: list[dict] = []

    async def poll(self) -> list[SwarmSummary]:
        """Poll for new notifications and extract swarm summaries.

        Neighbor-protocol messages are routed to the appropriate queues instead
        of being returned here.
        """
        summaries: list[SwarmSummary] = []

        try:
            params: dict[str, str] = {"types[]": "mention", "limit": "40"}
            if self._last_notification_id:
                params["since_id"] = self._last_notification_id

            resp = await self._http.get(
                f"{self._config.gotosocial_url}/api/v1/notifications",
                headers={"Authorization": f"Bearer {self._config.access_token}"},
                params=params,
                timeout=15.0,
            )
            resp.raise_for_status()
            notifications = resp.json()
        except httpx.HTTPError as exc:
            log.warn("subscriber.poll_failed", error=str(exc))
            return []

        if not notifications:
            return []

        # Update bookmark to latest notification
        self._last_notification_id = str(notifications[0]["id"])

        for notif in notifications:
            status = notif.get("status")
            if not status:
                continue

            content = status.get("content", "")
            match = _SWARM_PATTERN.search(content)
            if not match:
                continue

            ciphertext_b64 = match.group(1).strip()
            # Try to extract sender actor URI for topology-protocol attribution
            sender_uri = self._extract_sender_uri(notif)

            plaintext = self._decrypt_payload(ciphertext_b64)
            if plaintext is None:
                continue

            try:
                payload = json.loads(plaintext)
            except Exception as exc:
                log.warn("subscriber.json_parse_failed", error=str(exc))
                continue

            msg_type = payload.get("type", MSGTYPE_SUMMARY)

            if msg_type == MSGTYPE_SUMMARY:
                summary = self._parse_summary(payload)
                if summary and self._validate_sender(summary):
                    summaries.append(summary)

            elif msg_type == MSGTYPE_NEIGHBOR_REQUEST:
                log.info("subscriber.neighbor_request", from_uri=sender_uri)
                self.neighbor_requests.append((sender_uri, payload))

            elif msg_type == MSGTYPE_TOPOLOGY_QUERY:
                log.info("subscriber.topology_query", from_uri=sender_uri)
                self.topology_queries.append((sender_uri, payload))

            elif msg_type in (
                MSGTYPE_NEIGHBOR_RESPONSE,
                MSGTYPE_TOPOLOGY_RESPONSE,
                MSGTYPE_NEIGHBOR_BROADCAST,
            ):
                log.info("subscriber.topology_message", type=msg_type)
                self.topology_messages.append(payload)

            else:
                log.debug("subscriber.unknown_type", msg_type=msg_type)

        if summaries:
            log.info("subscriber.received", count=len(summaries))
        return summaries

    # ── Helpers ───────────────────────────────────────────────────────────

    def _extract_sender_uri(self, notif: dict) -> str:
        """Extract the actor URI of the notification sender."""
        account = notif.get("account", {})
        return account.get("url", "")

    def _decrypt_payload(self, ciphertext_b64: str) -> bytes | None:
        """Decrypt a single SWARM-envelope ciphertext; return None on failure."""
        try:
            if len(ciphertext_b64) > _MAX_PAYLOAD_BYTES * 2:
                log.warn("subscriber.payload_too_large", size=len(ciphertext_b64))
                return None
            plaintext = decrypt(ciphertext_b64, self._private_key)
            if len(plaintext) > _MAX_PAYLOAD_BYTES:
                log.warn("subscriber.decrypted_payload_too_large", size=len(plaintext))
                return None
            return plaintext
        except Exception as exc:
            log.warn("subscriber.decrypt_failed", error=str(exc))
            return None

    def _parse_summary(self, payload: dict) -> SwarmSummary | None:
        """Parse a JSON-LD SwarmSummary payload."""
        try:
            return SwarmSummary.from_jsonld(payload)
        except Exception as exc:
            log.warn("subscriber.summary_parse_failed", error=str(exc))
            return None

    def _validate_sender(self, summary: SwarmSummary) -> bool:
        """Ensure the summary came from a known adjacent node."""
        node = self._topology.get_node(summary.source_node_id)
        if node is None:
            log.warn(
                "subscriber.unknown_sender",
                source=summary.source_node_id,
            )
            return False
        if node.is_self:
            log.debug("subscriber.skip_self")
            return False
        # Verify the sender is in the adjacent node list, not just any known node
        adjacent_ids = {n.id for n in self._topology.adjacent_nodes}
        if node.id not in adjacent_ids:
            log.warn(
                "subscriber.sender_not_adjacent",
                source=summary.source_node_id,
            )
            return False
        return True
