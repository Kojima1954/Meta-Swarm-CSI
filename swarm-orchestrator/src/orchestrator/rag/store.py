"""Qdrant vector store — embed and retrieve swarm summaries."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import httpx
import structlog

from orchestrator.models.summary import SwarmSummary

if TYPE_CHECKING:
    from orchestrator.config import AIConfig

log = structlog.get_logger()

# nomic-embed-text produces 768-dim vectors by default
_DEFAULT_VECTOR_SIZE = 768


class VectorStore:
    """Qdrant client using the REST API via httpx."""

    def __init__(self, config: "AIConfig", http_client: httpx.AsyncClient) -> None:
        self._config = config
        self._http = http_client
        self._qdrant_url = config.qdrant_url
        self._collection = config.qdrant_collection
        self._ollama_url = config.ollama_url
        self._embedding_model = config.embedding_model
        self._vector_size: int | None = None

    async def ensure_collection(self) -> None:
        """Create the Qdrant collection if it doesn't exist."""
        # Detect vector size by embedding a test string
        if self._vector_size is None:
            test_vec = await self.embed("test")
            self._vector_size = len(test_vec)
            log.info("rag.vector_size_detected", size=self._vector_size)

        url = f"{self._qdrant_url}/collections/{self._collection}"

        # Check if collection exists
        try:
            resp = await self._http.get(url)
            if resp.status_code == 200:
                log.info("rag.collection_exists", collection=self._collection)
                return
        except httpx.HTTPError:
            pass

        # Create collection
        payload = {
            "vectors": {
                "size": self._vector_size,
                "distance": "Cosine",
            }
        }
        resp = await self._http.put(url, json=payload)
        resp.raise_for_status()
        log.info("rag.collection_created", collection=self._collection)

    async def embed(self, text: str) -> list[float]:
        """Generate embeddings via Ollama."""
        resp = await self._http.post(
            f"{self._ollama_url}/api/embeddings",
            json={"model": self._embedding_model, "prompt": text},
            timeout=60.0,
        )
        resp.raise_for_status()
        return resp.json()["embedding"]

    async def store_summary(self, summary: SwarmSummary) -> None:
        """Embed and upsert a summary into Qdrant."""
        text = summary.to_text()
        vector = await self.embed(text)

        point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, summary.summary_id()))

        payload = {
            "points": [
                {
                    "id": point_id,
                    "vector": vector,
                    "payload": {
                        "summary_id": summary.summary_id(),
                        "source_node_id": summary.source_node_id,
                        "round_number": summary.round_number,
                        "topic": summary.topic,
                        "text": text,
                        "published": summary.published.isoformat(),
                    },
                }
            ]
        }

        resp = await self._http.put(
            f"{self._qdrant_url}/collections/{self._collection}/points",
            json=payload,
            timeout=30.0,
        )
        resp.raise_for_status()
        log.info("rag.summary_stored", summary_id=summary.summary_id())

    async def retrieve_context(self, query: str, top_k: int = 5) -> str:
        """Search Qdrant for relevant prior summaries."""
        vector = await self.embed(query)

        resp = await self._http.post(
            f"{self._qdrant_url}/collections/{self._collection}/points/search",
            json={
                "vector": vector,
                "limit": top_k,
                "with_payload": True,
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        results = resp.json().get("result", [])

        if not results:
            return ""

        context_parts: list[str] = []
        for hit in results:
            payload = hit.get("payload", {})
            text = payload.get("text", "")
            sid = payload.get("summary_id", "unknown")
            score = hit.get("score", 0)
            context_parts.append(f"[{sid} (relevance: {score:.2f})]\n{text}")

        return "\n\n".join(context_parts)
