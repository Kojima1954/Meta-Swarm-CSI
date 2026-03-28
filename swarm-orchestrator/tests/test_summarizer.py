"""Tests for the LLM summarizer with mocked Ollama responses."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from orchestrator.config import AIConfig
from orchestrator.llm.summarizer import Summarizer
from orchestrator.models.summary import SwarmSummary


def _mock_chat_response(content: str) -> httpx.Response:
    """Create a mock httpx response for Ollama chat."""
    return httpx.Response(
        status_code=200,
        json={"message": {"role": "assistant", "content": content}},
        request=httpx.Request("POST", "http://ollama:11434/api/chat"),
    )


@pytest.fixture
def ai_config() -> AIConfig:
    return AIConfig(
        llm_model="test-model",
        ollama_url="http://ollama:11434",
        temperature=0.3,
        max_tokens=1024,
    )


@pytest.fixture
def valid_summary_json() -> str:
    return json.dumps(
        {
            "round_number": 1,
            "topic": "Test topic",
            "source_node_id": "node-alpha",
            "participant_count": 5,
            "message_count": 20,
            "key_positions": ["Position A", "Position B"],
            "emerging_consensus": "Agreement on X",
            "dissenting_views": ["Disagree on Y"],
            "open_questions": ["What about Z?"],
            "parent_summary_ids": [],
        }
    )


class TestSummarizer:
    @pytest.mark.asyncio
    async def test_successful_summarization(self, ai_config, valid_summary_json):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        # Pass 1: natural language summary
        # Pass 2: structured JSON
        mock_client.post.side_effect = [
            _mock_chat_response("This is a summary of the discussion."),
            _mock_chat_response(valid_summary_json),
        ]

        summarizer = Summarizer(ai_config, mock_client)
        result = await summarizer.summarize(
            transcript="Alice: I think X\nBob: I think Y",
            round_number=1,
            source_node_id="node-alpha",
            participant_count=5,
            message_count=20,
        )

        assert isinstance(result, SwarmSummary)
        assert result.round_number == 1
        assert result.topic == "Test topic"
        assert len(result.key_positions) == 2
        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_retry_on_invalid_json(self, ai_config, valid_summary_json):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.side_effect = [
            _mock_chat_response("Summary text."),
            # First JSON attempt: invalid
            _mock_chat_response("not valid json {{{"),
            # Retry: valid
            _mock_chat_response(valid_summary_json),
        ]

        summarizer = Summarizer(ai_config, mock_client)
        result = await summarizer.summarize(
            transcript="Alice: hello",
            round_number=1,
            source_node_id="node-alpha",
            participant_count=1,
            message_count=1,
        )

        assert isinstance(result, SwarmSummary)
        assert mock_client.post.call_count == 3  # 1 summary + 2 structuring

    @pytest.mark.asyncio
    async def test_markdown_fences_stripped(self, ai_config):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        fenced_json = '```json\n{"round_number":1,"topic":"T","source_node_id":"n","participant_count":1,"message_count":1,"key_positions":["A"],"emerging_consensus":"","dissenting_views":[],"open_questions":[],"parent_summary_ids":[]}\n```'
        mock_client.post.side_effect = [
            _mock_chat_response("Summary."),
            _mock_chat_response(fenced_json),
        ]

        summarizer = Summarizer(ai_config, mock_client)
        result = await summarizer.summarize(
            transcript="msg",
            round_number=1,
            source_node_id="n",
            participant_count=1,
            message_count=1,
        )

        assert isinstance(result, SwarmSummary)

    @pytest.mark.asyncio
    async def test_includes_inbound_signals_in_prompt(self, ai_config, valid_summary_json):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.side_effect = [
            _mock_chat_response("Summary with signals."),
            _mock_chat_response(valid_summary_json),
        ]

        inbound = SwarmSummary(
            round_number=1,
            source_node_id="node-beta",
            key_positions=["Beta position"],
            emerging_consensus="Beta consensus",
        )

        summarizer = Summarizer(ai_config, mock_client)
        await summarizer.summarize(
            transcript="Alice: hello",
            round_number=2,
            source_node_id="node-alpha",
            participant_count=1,
            message_count=1,
            inbound_signals=[inbound],
        )

        # Check that the first call includes signal context
        call_args = mock_client.post.call_args_list[0]
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        user_content = payload["messages"][1]["content"]
        assert "SWARM SIGNALS" in user_content
