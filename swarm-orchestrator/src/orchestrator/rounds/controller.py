"""Round controller — manages the DISCUSS → SUMMARIZE → PROPAGATE lifecycle."""

from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import TYPE_CHECKING

import structlog

from orchestrator.models.summary import SwarmSummary
from orchestrator.models.topology import SwarmNode

if TYPE_CHECKING:
    from orchestrator.config import RoundsConfig, Settings
    from orchestrator.federation.publisher import FederationPublisher
    from orchestrator.federation.subscriber import FederationSubscriber
    from orchestrator.llm.summarizer import Summarizer
    from orchestrator.matrix.client import MatrixBridge
    from orchestrator.matrix.transcript import TranscriptBuffer
    from orchestrator.models.topology import Topology
    from orchestrator.rag.store import VectorStore
    from orchestrator.topology.murmuration import MurmurationTopology

log = structlog.get_logger()


class Phase(str, Enum):
    DISCUSS = "DISCUSS"
    SUMMARIZE = "SUMMARIZE"
    PROPAGATE = "PROPAGATE"


class RoundController:
    """Async state machine controlling the deliberation round lifecycle."""

    def __init__(
        self,
        settings: "Settings",
        matrix: "MatrixBridge",
        transcript: "TranscriptBuffer",
        summarizer: "Summarizer",
        vector_store: "VectorStore",
        publisher: "FederationPublisher",
        subscriber: "FederationSubscriber",
        topology: "Topology",
        murmuration: "MurmurationTopology | None" = None,
    ) -> None:
        self._settings = settings
        self._config: RoundsConfig = settings.rounds
        self._matrix = matrix
        self._transcript = transcript
        self._summarizer = summarizer
        self._vector_store = vector_store
        self._publisher = publisher
        self._subscriber = subscriber
        self._topology = topology
        self._murmuration = murmuration

        self.phase = Phase.DISCUSS
        self.round_number = 1
        self._inbound_queue: list[SwarmSummary] = []
        self._manual_trigger = asyncio.Event()
        self._shutdown = asyncio.Event()

        # Security: duplicate detection and rate limiting for inbound summaries
        self._seen_summary_ids: set[str] = set()
        self._inbound_rate: dict[str, list[float]] = {}  # node_id -> timestamps
        self._max_inbound_per_node = 10  # max summaries per node per window
        self._rate_window_seconds = 300.0

        # Murmuration rewiring tracker
        self._rounds_since_rewire: int = 0

    def trigger_manual(self) -> None:
        """Called when a user types !summarize in chat."""
        self._manual_trigger.set()

    async def run(self) -> None:
        """Main loop: wait for trigger, summarize, propagate, repeat."""
        log.info(
            "rounds.started",
            mode=self._config.mode,
            interval=self._config.interval_seconds,
        )

        while not self._shutdown.is_set():
            self.phase = Phase.DISCUSS
            log.info("rounds.phase", phase=self.phase, round=self.round_number)

            # Wait for trigger
            triggered = await self._wait_for_trigger()
            if not triggered:
                break  # Shutdown requested

            # SUMMARIZE phase
            self.phase = Phase.SUMMARIZE
            log.info("rounds.phase", phase=self.phase, round=self.round_number)

            summary = await self._run_summarize()
            if summary is None:
                log.warn("rounds.summarize_failed", round=self.round_number)
                continue

            # PROPAGATE phase
            self.phase = Phase.PROPAGATE
            log.info("rounds.phase", phase=self.phase, round=self.round_number)

            await self._run_propagate(summary)

            # Advance round
            self.round_number += 1
            self._inbound_queue.clear()
            self._transcript.clear()
            self._manual_trigger.clear()
            self._seen_summary_ids.clear()

            # Murmuration: check if rewiring is due
            if self._murmuration is not None:
                self._rounds_since_rewire += 1
                rewire_every = self._settings.topology.rewire_every_n_rounds
                if self._rounds_since_rewire >= rewire_every:
                    self._rounds_since_rewire = 0
                    await self._do_murmuration_rewire()

            log.info("rounds.complete", next_round=self.round_number)

    async def _wait_for_trigger(self) -> bool:
        """Wait for the appropriate trigger based on mode config."""
        mode = self._config.mode

        if mode == "timer":
            try:
                await asyncio.wait_for(
                    self._shutdown.wait(),
                    timeout=self._config.interval_seconds,
                )
                return False  # Shutdown was requested
            except asyncio.TimeoutError:
                return True  # Timer expired, proceed

        elif mode == "message_count":
            while not self._shutdown.is_set():
                if self._transcript.message_count >= self._config.message_threshold:
                    return True
                await asyncio.sleep(5)
            return False

        elif mode == "manual":
            # Wait for either manual trigger or shutdown
            trigger_task = asyncio.create_task(self._manual_trigger.wait())
            shutdown_task = asyncio.create_task(self._shutdown.wait())
            done, pending = await asyncio.wait(
                [trigger_task, shutdown_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            return self._manual_trigger.is_set()

        else:
            log.error("rounds.unknown_mode", mode=mode)
            await asyncio.sleep(60)
            return True

    async def _run_summarize(self) -> SwarmSummary | None:
        """Execute the summarization phase."""
        transcript_text = self._transcript.to_prompt_text()
        if not transcript_text.strip():
            log.info("rounds.empty_transcript")
            await self._matrix.send_text(
                "\U0001f41d Round skipped — no messages to summarize."
            )
            return None

        # Retrieve RAG context
        rag_context = ""
        try:
            rag_context = await self._vector_store.retrieve_context(
                transcript_text[:500]
            )
        except Exception as exc:
            log.warn("rounds.rag_failed", error=str(exc))

        # Call the summarizer
        try:
            summary = await self._summarizer.summarize(
                transcript=transcript_text,
                round_number=self.round_number,
                source_node_id=self._settings.node.id,
                participant_count=self._transcript.participant_count,
                message_count=self._transcript.message_count,
                inbound_signals=self._inbound_queue or None,
                rag_context=rag_context,
            )
        except Exception as exc:
            log.error("rounds.summarize_error", error=str(exc))
            return None

        # Store in Qdrant
        try:
            await self._vector_store.store_summary(summary)
        except Exception as exc:
            log.warn("rounds.store_failed", error=str(exc))

        # Post summary to local room
        self_name = self._settings.node.name or self._settings.node.id
        await self._matrix.send_swarm_signal(summary, f"{self_name} (local)")

        return summary

    async def _run_propagate(self, summary: SwarmSummary) -> None:
        """Send the summary to all adjacent nodes."""
        try:
            await self._publisher.publish(summary, self._topology)
        except Exception as exc:
            log.error("rounds.propagate_error", error=str(exc))

    def _is_rate_limited(self, node_id: str) -> bool:
        """Check if a node has exceeded its inbound summary rate limit."""
        now = time.monotonic()
        timestamps = self._inbound_rate.get(node_id, [])
        # Prune old timestamps outside the window
        timestamps = [t for t in timestamps if now - t < self._rate_window_seconds]
        self._inbound_rate[node_id] = timestamps
        return len(timestamps) >= self._max_inbound_per_node

    async def receive_inbound(self, summary: SwarmSummary) -> None:
        """Handle an inbound summary from a peer node."""
        sid = summary.summary_id()

        # Duplicate detection
        if sid in self._seen_summary_ids:
            log.warn("rounds.inbound_duplicate", summary_id=sid)
            return
        self._seen_summary_ids.add(sid)

        # Rate limiting per source node
        node_id = summary.source_node_id
        if self._is_rate_limited(node_id):
            log.warn("rounds.inbound_rate_limited", source=node_id)
            return
        self._inbound_rate.setdefault(node_id, []).append(time.monotonic())

        self._inbound_queue.append(summary)

        # Track information gain for murmuration rewiring
        if self._murmuration is not None:
            self._murmuration.record_inbound_summary(node_id, summary.to_text())

        # Inject into the local Matrix room immediately
        source_node = self._topology.get_node(summary.source_node_id)
        source_name = source_node.name if source_node else summary.source_node_id
        await self._matrix.send_swarm_signal(summary, source_name)

        # Store in Qdrant
        try:
            await self._vector_store.store_summary(summary)
        except Exception as exc:
            log.warn("rounds.inbound_store_failed", error=str(exc))

        log.info(
            "rounds.inbound_received",
            source=summary.source_node_id,
            round=summary.round_number,
        )

    # ── Murmuration rewiring ──────────────────────────────────────────────

    async def _do_murmuration_rewire(self) -> None:
        """Execute one murmuration rewire cycle.

        1. Drop the lowest-scoring neighbor.
        2. Ask a remaining neighbor for a friend-of-a-friend introduction.
        3. Drain inbound neighbor requests and topology responses.
        4. Broadcast the updated neighbor list.
        5. Persist state.

        Safe to call when the neighbor set is empty — all steps are no-ops.
        """
        if self._murmuration is None:
            return

        self_node = self._topology.self_node
        if self_node is None:
            return

        # Step 1 & 2: drop + get query target
        dropped_id, query_node_id = self._murmuration.rewire()

        # Step 2 cont'd: send TOPOLOGY_QUERY to the chosen neighbor
        if query_node_id:
            query_node = self._topology.get_node(query_node_id)
            if query_node:
                try:
                    await self._publisher.send_topology_query(query_node, self_node)
                except Exception as exc:
                    log.warn("murmuration.query_send_failed", error=str(exc))

        # Step 3a: handle pending NEIGHBOR_REQUESTs (strangers wanting to connect)
        for sender_uri, req_payload in list(self._subscriber.neighbor_requests):
            await self._handle_neighbor_request(sender_uri, req_payload, self_node)
        self._subscriber.neighbor_requests.clear()

        # Step 3b: handle TOPOLOGY_RESPONSES and NEIGHBOR_BROADCASTs
        for msg in list(self._subscriber.topology_messages):
            await self._handle_topology_message(msg)
        self._subscriber.topology_messages.clear()

        # Step 3c: answer pending TOPOLOGY_QUERYs (neighbors asking us for a peer)
        for sender_uri, query_payload in list(self._subscriber.topology_queries):
            await self._handle_topology_query(sender_uri, query_payload, self_node)
        self._subscriber.topology_queries.clear()

        # Step 4: broadcast updated neighbor list
        neighbors_now = self._murmuration.adjacent_nodes
        if neighbors_now:
            try:
                await self._publisher.send_neighbor_broadcast(
                    neighbors_now, self_node, neighbors_now
                )
            except Exception as exc:
                log.warn("murmuration.broadcast_failed", error=str(exc))

        # Step 5: persist
        self._murmuration.save_state()

        log.info(
            "murmuration.rewire_complete",
            dropped=dropped_id,
            queried=query_node_id,
            neighbors=len(neighbors_now),
            fingerprint=self._murmuration._fingerprint,  # noqa: SLF001
        )

    async def _handle_neighbor_request(
        self, sender_uri: str, payload: dict, self_node: SwarmNode
    ) -> None:
        """Process an inbound NEIGHBOR_REQUEST from a prospective peer."""
        if self._murmuration is None:
            return

        candidate = SwarmNode(
            id=payload.get("from_node_id", ""),
            name=payload.get("from_name", ""),
            domain=payload.get("from_domain", ""),
            public_key=payload.get("from_public_key", ""),
            role="participant",
        )

        if not candidate.id or not candidate.public_key:
            log.warn("murmuration.neighbor_request_invalid", sender=sender_uri)
            return

        added = self._murmuration.add_candidate(candidate)
        try:
            await self._publisher.send_neighbor_response(candidate, added, self_node)
        except Exception as exc:
            log.warn("murmuration.response_send_failed", error=str(exc))

        if added:
            log.info("murmuration.neighbor_accepted", candidate=candidate.id)
        else:
            log.info("murmuration.neighbor_rejected", candidate=candidate.id)

    async def _handle_topology_message(self, msg: dict) -> None:
        """Process TOPOLOGY_RESPONSE or NEIGHBOR_BROADCAST messages."""
        if self._murmuration is None:
            return

        from orchestrator.topology.murmuration import (
            MSGTYPE_NEIGHBOR_BROADCAST,
            MSGTYPE_TOPOLOGY_RESPONSE,
        )

        msg_type = msg.get("type", "")

        if msg_type == MSGTYPE_TOPOLOGY_RESPONSE:
            # A neighbor introduced us to one of their peers
            candidate = SwarmNode(
                id=msg.get("neighbor_id", ""),
                name=msg.get("neighbor_name", ""),
                domain=msg.get("neighbor_domain", ""),
                public_key=msg.get("neighbor_public_key", ""),
                role="participant",
            )
            if candidate.id and candidate.public_key:
                self._murmuration.add_candidate(candidate)
                log.info("murmuration.candidate_introduced", candidate=candidate.id)

        elif msg_type == MSGTYPE_NEIGHBOR_BROADCAST:
            # A neighbor told us their current topology — add to known set
            nodes = [
                SwarmNode(
                    id=n.get("id", ""),
                    name=n.get("name", ""),
                    domain=n.get("domain", ""),
                    public_key=n.get("public_key", ""),
                    role="participant",
                )
                for n in msg.get("neighbors", [])
                if n.get("id") and n.get("public_key")
            ]
            self._murmuration.update_known_nodes(nodes)

    async def _handle_topology_query(
        self, sender_uri: str, payload: dict, self_node: SwarmNode
    ) -> None:
        """Answer a TOPOLOGY_QUERY by introducing one of our active neighbors."""
        if self._murmuration is None:
            return

        neighbors = self._murmuration.adjacent_nodes
        if not neighbors:
            return

        from_node_id = payload.get("from_node_id", "")
        # Find the requester in our known set so we can address the response
        requester = self._topology.get_node(from_node_id)
        if requester is None:
            # Construct a minimal node from the actor URI so we can reply
            if sender_uri:
                # sender_uri is https://domain/users/id
                parts = sender_uri.rstrip("/").split("/")
                if len(parts) >= 2:
                    requester = SwarmNode(
                        id=parts[-1],
                        domain=parts[2] if len(parts) > 2 else "",
                        public_key="",  # we don't know their key yet
                    )

        if requester is None or not requester.public_key:
            log.warn("murmuration.query_requester_unknown", from_id=from_node_id)
            return

        import random
        peer = random.choice(neighbors)  # noqa: S311
        try:
            await self._publisher.send_topology_response(requester, peer, self_node)
        except Exception as exc:
            log.warn("murmuration.topology_response_failed", error=str(exc))

    async def stop(self) -> None:
        """Signal shutdown."""
        self._shutdown.set()
        log.info("rounds.stopping")
