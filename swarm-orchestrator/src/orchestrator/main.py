"""Entrypoint — wire up all components and run the orchestrator."""

from __future__ import annotations

import asyncio
import signal
import sys

import httpx
import structlog

from orchestrator.config import load_settings
from orchestrator.federation.crypto import load_keypair
from orchestrator.federation.publisher import FederationPublisher
from orchestrator.federation.subscriber import FederationSubscriber
from orchestrator.llm.summarizer import Summarizer
from orchestrator.matrix.client import MatrixBridge
from orchestrator.matrix.transcript import TranscriptBuffer
from orchestrator.rag.store import VectorStore
from orchestrator.rounds.controller import RoundController
from orchestrator.topology.manager import TopologyManager

log = structlog.get_logger()


def configure_logging(level: str) -> None:
    """Set up structlog with JSON output."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            structlog.get_level_from_name(level)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


async def poll_federation(
    subscriber: FederationSubscriber,
    controller: RoundController,
    shutdown: asyncio.Event,
    interval: float = 15.0,
) -> None:
    """Background task: poll GoToSocial for inbound summaries."""
    while not shutdown.is_set():
        try:
            summaries = await subscriber.poll()
            for summary in summaries:
                await controller.receive_inbound(summary)
        except Exception as exc:
            log.error("federation.poll_error", error=str(exc))

        try:
            await asyncio.wait_for(shutdown.wait(), timeout=interval)
            return
        except asyncio.TimeoutError:
            pass


async def run() -> None:
    """Main async entry point."""
    # Load configuration
    settings = load_settings()
    configure_logging(settings.logging.level)

    log.info(
        "orchestrator.starting",
        node_id=settings.node.id,
        version="0.1.0",
    )

    # Load topology
    topology_path = "/etc/orchestrator/topology.toml"
    topo_manager = TopologyManager(topology_path, settings.node.id)
    topology = topo_manager.load()

    # Load encryption keys
    private_key, public_key = load_keypair(
        settings.security.key_path,
        settings.security.public_key_path,
    )

    # Create shared HTTP client
    http_client = httpx.AsyncClient()

    # Initialize components
    transcript = TranscriptBuffer()

    summarizer = Summarizer(settings.ai, http_client)
    vector_store = VectorStore(settings.ai, http_client)
    publisher = FederationPublisher(settings.federation, http_client)
    subscriber = FederationSubscriber(
        settings.federation, http_client, private_key, topology
    )

    controller = RoundController(
        settings=settings,
        matrix=None,  # Set after MatrixBridge is created
        transcript=transcript,
        summarizer=summarizer,
        vector_store=vector_store,
        publisher=publisher,
        subscriber=subscriber,
        topology=topology,
    )

    matrix = MatrixBridge(
        matrix_config=settings.matrix,
        node_config=settings.node,
        transcript=transcript,
        on_manual_trigger=controller.trigger_manual,
    )
    controller._matrix = matrix  # noqa: SLF001 — DI wiring

    # Ensure Qdrant collection exists
    try:
        await vector_store.ensure_collection()
    except Exception as exc:
        log.warn("orchestrator.qdrant_init_failed", error=str(exc))

    # Set up shutdown handling
    shutdown = asyncio.Event()

    def signal_handler() -> None:
        log.info("orchestrator.shutdown_signal")
        shutdown.set()
        controller._shutdown.set()  # noqa: SLF001

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

    # Start all tasks
    tasks = [
        asyncio.create_task(matrix.start(), name="matrix"),
        asyncio.create_task(controller.run(), name="rounds"),
        asyncio.create_task(
            poll_federation(subscriber, controller, shutdown),
            name="federation",
        ),
    ]

    log.info("orchestrator.running", node_id=settings.node.id)

    try:
        # Wait for any task to complete (likely due to shutdown or error)
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

        for task in done:
            if task.exception():
                log.error(
                    "orchestrator.task_failed",
                    task=task.get_name(),
                    error=str(task.exception()),
                )
    finally:
        # Graceful shutdown
        log.info("orchestrator.shutting_down")
        shutdown.set()
        await controller.stop()
        await matrix.stop()

        for task in tasks:
            if not task.done():
                task.cancel()

        await asyncio.gather(*tasks, return_exceptions=True)
        await http_client.aclose()

        log.info("orchestrator.stopped")


def main() -> None:
    """Sync wrapper for the async entry point."""
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(f"Fatal error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
