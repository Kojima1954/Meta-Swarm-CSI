"""Tests for the RoundController state machine."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestrator.models.summary import SwarmSummary
from orchestrator.rounds.controller import Phase, RoundController


@pytest.fixture
def mock_deps(sample_settings, sample_topology):
    """Create mocked dependencies for the RoundController."""
    transcript = MagicMock()
    transcript.to_prompt_text.return_value = "Alice: I think we should do X"
    transcript.message_count = 5
    transcript.participant_count = 2
    transcript.clear = MagicMock()

    matrix = AsyncMock()
    summarizer = AsyncMock()
    vector_store = AsyncMock()
    publisher = AsyncMock()
    subscriber = AsyncMock()

    return {
        "settings": sample_settings,
        "matrix": matrix,
        "transcript": transcript,
        "summarizer": summarizer,
        "vector_store": vector_store,
        "publisher": publisher,
        "subscriber": subscriber,
        "topology": sample_topology,
    }


@pytest.fixture
def controller(mock_deps) -> RoundController:
    return RoundController(**mock_deps)


class TestRoundController:
    def test_initial_state(self, controller):
        assert controller.phase == Phase.DISCUSS
        assert controller.round_number == 1

    def test_trigger_manual(self, controller):
        controller.trigger_manual()
        assert controller._manual_trigger.is_set()

    @pytest.mark.asyncio
    async def test_receive_inbound(self, controller):
        summary = SwarmSummary(
            round_number=1,
            source_node_id="node-beta",
            key_positions=["Test position"],
        )
        await controller.receive_inbound(summary)

        assert len(controller._inbound_queue) == 1
        controller._matrix.send_swarm_signal.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_summarize_with_empty_transcript(self, controller):
        controller._transcript.to_prompt_text.return_value = ""
        result = await controller._run_summarize()
        assert result is None
        controller._matrix.send_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_summarize_calls_all_components(self, controller):
        test_summary = SwarmSummary(
            round_number=1,
            source_node_id="node-alpha",
            key_positions=["Position A"],
        )
        controller._summarizer.summarize.return_value = test_summary
        controller._vector_store.retrieve_context.return_value = "context"

        result = await controller._run_summarize()

        assert result is not None
        assert result.source_node_id == "node-alpha"
        controller._summarizer.summarize.assert_awaited_once()
        controller._vector_store.store_summary.assert_awaited_once()
        controller._matrix.send_swarm_signal.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_propagate_calls_publisher(self, controller):
        summary = SwarmSummary(
            round_number=1,
            source_node_id="node-alpha",
            key_positions=["A"],
        )
        await controller._run_propagate(summary)
        controller._publisher.publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop(self, controller):
        await controller.stop()
        assert controller._shutdown.is_set()

    @pytest.mark.asyncio
    async def test_run_single_round_timer(self, mock_deps):
        """Test a single timer-based round: trigger → summarize → propagate."""
        mock_deps["settings"].rounds.interval_seconds = 0  # Instant trigger

        controller = RoundController(**mock_deps)

        test_summary = SwarmSummary(
            round_number=1,
            source_node_id="node-alpha",
            key_positions=["Pos"],
        )
        controller._summarizer.summarize.return_value = test_summary
        controller._vector_store.retrieve_context.return_value = ""

        # Run for one iteration then stop
        async def stop_after_delay():
            await asyncio.sleep(0.1)
            await controller.stop()

        asyncio.create_task(stop_after_delay())
        await controller.run()

        assert controller.round_number >= 2
