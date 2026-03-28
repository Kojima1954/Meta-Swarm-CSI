"""LLM summarizer — two-pass approach via Ollama chat API."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx
import structlog

from orchestrator.llm.prompts import (
    INBOUND_SIGNALS_SECTION,
    RAG_CONTEXT_SECTION,
    STRUCTURING_PROMPT,
    SUMMARIZE_PROMPT,
    SYSTEM_PROMPT,
)
from orchestrator.models.summary import SwarmSummary

if TYPE_CHECKING:
    from orchestrator.config import AIConfig

log = structlog.get_logger()

_MAX_RETRIES = 2


class Summarizer:
    """Two-pass LLM summarizer: natural language, then structured JSON."""

    def __init__(self, config: "AIConfig", http_client: httpx.AsyncClient) -> None:
        self._config = config
        self._http = http_client
        self._chat_url = f"{config.ollama_url}/api/chat"

    async def summarize(
        self,
        transcript: str,
        round_number: int,
        source_node_id: str,
        participant_count: int,
        message_count: int,
        inbound_signals: list[SwarmSummary] | None = None,
        rag_context: str = "",
    ) -> SwarmSummary:
        """Run the two-pass summarization pipeline."""

        # Build the prompt sections
        inbound_section = ""
        parent_ids: list[str] = []
        if inbound_signals:
            signals_text = "\n\n".join(s.to_text() for s in inbound_signals)
            inbound_section = INBOUND_SIGNALS_SECTION.format(signals_text=signals_text)
            parent_ids = [s.summary_id() for s in inbound_signals]

        rag_section = ""
        if rag_context:
            rag_section = RAG_CONTEXT_SECTION.format(rag_text=rag_context)

        # Pass 1: generate natural-language summary
        user_prompt = SUMMARIZE_PROMPT.format(
            transcript=transcript,
            inbound_section=inbound_section,
            rag_section=rag_section,
        )

        log.info("summarizer.pass1_start", model=self._config.llm_model)
        summary_text = await self._chat(SYSTEM_PROMPT, user_prompt)
        log.info("summarizer.pass1_done", length=len(summary_text))

        # Pass 2: structure into JSON
        structuring_prompt = STRUCTURING_PROMPT.format(
            round_number=round_number,
            source_node_id=source_node_id,
            participant_count=participant_count,
            message_count=message_count,
            parent_summary_ids=json.dumps(parent_ids),
            summary_text=summary_text,
        )

        for attempt in range(_MAX_RETRIES + 1):
            log.info("summarizer.pass2_start", attempt=attempt + 1)
            json_text = await self._chat(
                "You are a JSON formatting assistant. Output ONLY valid JSON.",
                structuring_prompt,
            )

            try:
                # Strip any markdown fences the LLM might add
                cleaned = json_text.strip()
                if cleaned.startswith("```"):
                    cleaned = cleaned.split("\n", 1)[1]
                    if cleaned.endswith("```"):
                        cleaned = cleaned[: cleaned.rfind("```")]
                    cleaned = cleaned.strip()

                data = json.loads(cleaned)
                summary = SwarmSummary.model_validate(data)
                log.info("summarizer.pass2_done", summary_id=summary.summary_id())
                return summary
            except (json.JSONDecodeError, ValueError) as exc:
                log.warn(
                    "summarizer.parse_failed",
                    attempt=attempt + 1,
                    error=str(exc),
                )
                if attempt == _MAX_RETRIES:
                    raise

        raise RuntimeError("Unreachable")  # pragma: no cover

    async def _chat(self, system: str, user: str) -> str:
        """Send a chat request to Ollama and return the assistant message."""
        payload = {
            "model": self._config.llm_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {
                "temperature": self._config.temperature,
                "num_predict": self._config.max_tokens,
            },
        }

        try:
            resp = await self._http.post(
                self._chat_url,
                json=payload,
                timeout=120.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["message"]["content"]
        except httpx.HTTPError as exc:
            log.error("summarizer.ollama_error", error=str(exc))
            raise
