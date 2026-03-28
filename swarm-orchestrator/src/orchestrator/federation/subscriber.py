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

if TYPE_CHECKING:
    from orchestrator.config import FederationConfig

log = structlog.get_logger()

_SWARM_PATTERN = re.compile(r"<!--SWARM:(.*?):SWARM-->", re.DOTALL)


class FederationSubscriber:
    """Polls GoToSocial notifications for encrypted inbound summaries."""

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

    async def poll(self) -> list[SwarmSummary]:
        """Poll for new notifications and extract swarm summaries."""
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
            summary = self._decrypt_and_parse(ciphertext_b64)
            if summary and self._validate_sender(summary):
                summaries.append(summary)

        if summaries:
            log.info("subscriber.received", count=len(summaries))
        return summaries

    def _decrypt_and_parse(self, ciphertext_b64: str) -> SwarmSummary | None:
        """Decrypt and parse a single encrypted summary."""
        try:
            plaintext = decrypt(ciphertext_b64, self._private_key)
            data = json.loads(plaintext)
            return SwarmSummary.from_jsonld(data)
        except Exception as exc:
            log.warn("subscriber.decrypt_failed", error=str(exc))
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
        return True
