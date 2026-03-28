"""Round controller — manages the DISCUSS → SUMMARIZE → PROPAGATE lifecycle."""

from __future__ import annotations

import asyncio
from enum import Enum
from typing import TYPE_CHECKING

import structlog

from orchestrator.models.summary import SwarmSummary

if TYPE_CHECKING:
    from orchestrator.config import RoundsConfig, Settings
    from orchestrator.federation.publisher import FederationPublisher
    from orchestrator.federation.subscriber import FederationSubscriber
    from orchestrator.llm.summarizer import Summarizer
    from orchestrator.matrix.client import MatrixBridge
    from orchestrator.matrix.transcript import TranscriptBuffer
    from orchestrator.models.topology import Topology
    from orchestrator.rag.store import VectorStore

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

        self.phase = Phase.DISCUSS
        self.round_number = 1
        self._inbound_queue: list[SwarmSummary] = []
        self._manual_trigger = asyncio.Event()
        self._shutdown = asyncio.Event()

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

    async def receive_inbound(self, summary: SwarmSummary) -> None:
        """Handle an inbound summary from a peer node."""
        self._inbound_queue.append(summary)

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

    async def stop(self) -> None:
        """Signal shutdown."""
        self._shutdown.set()
        log.info("rounds.stopping")
