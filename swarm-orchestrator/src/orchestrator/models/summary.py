"""SwarmSummary — the core data object exchanged between nodes."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator

_JSONLD_CONTEXT = [
    "https://www.w3.org/ns/activitystreams",
    {"swarm": "https://nomad-swarm.org/ns#"},
]


class SwarmSummary(BaseModel):
    """A summary of one deliberation round, serializable to JSON-LD."""

    round_number: int = Field(ge=1)
    topic: str = ""
    source_node_id: str
    published: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    participant_count: int = Field(ge=0, default=0)
    message_count: int = Field(ge=0, default=0)
    key_positions: list[str] = Field(min_length=1)
    emerging_consensus: str = ""
    dissenting_views: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    parent_summary_ids: list[str] = Field(default_factory=list)

    @field_validator("key_positions")
    @classmethod
    def _key_positions_non_empty(cls, v: list[str]) -> list[str]:
        if not v or all(not s.strip() for s in v):
            raise ValueError("key_positions must contain at least one non-empty entry")
        return v

    def summary_id(self) -> str:
        return f"{self.source_node_id}:round-{self.round_number}"

    def to_text(self) -> str:
        """Plain-text representation for embedding / LLM context."""
        lines = [
            f"Round {self.round_number} — {self.source_node_id}",
            f"Topic: {self.topic}" if self.topic else "",
            f"Key positions: {'; '.join(self.key_positions)}",
            f"Consensus: {self.emerging_consensus}" if self.emerging_consensus else "",
        ]
        if self.dissenting_views:
            lines.append(f"Dissent: {'; '.join(self.dissenting_views)}")
        if self.open_questions:
            lines.append(f"Open questions: {'; '.join(self.open_questions)}")
        return "\n".join(line for line in lines if line)

    def to_jsonld(self) -> dict:
        """Serialize to a JSON-LD compatible dict."""
        return {
            "@context": _JSONLD_CONTEXT,
            "type": "swarm:SwarmSummary",
            "swarm:roundNumber": self.round_number,
            "swarm:topic": self.topic,
            "swarm:sourceNodeId": self.source_node_id,
            "published": self.published.isoformat(),
            "swarm:participantCount": self.participant_count,
            "swarm:messageCount": self.message_count,
            "swarm:keyPositions": self.key_positions,
            "swarm:emergingConsensus": self.emerging_consensus,
            "swarm:dissentingViews": self.dissenting_views,
            "swarm:openQuestions": self.open_questions,
            "swarm:parentSummaryIds": self.parent_summary_ids,
        }

    @classmethod
    def from_jsonld(cls, data: dict) -> SwarmSummary:
        """Parse a JSON-LD dict back into a SwarmSummary."""
        return cls(
            round_number=data["swarm:roundNumber"],
            topic=data.get("swarm:topic", ""),
            source_node_id=data["swarm:sourceNodeId"],
            published=datetime.fromisoformat(data["published"]),
            participant_count=data.get("swarm:participantCount", 0),
            message_count=data.get("swarm:messageCount", 0),
            key_positions=data["swarm:keyPositions"],
            emerging_consensus=data.get("swarm:emergingConsensus", ""),
            dissenting_views=data.get("swarm:dissentingViews", []),
            open_questions=data.get("swarm:openQuestions", []),
            parent_summary_ids=data.get("swarm:parentSummaryIds", []),
        )
