"""Rolling transcript buffer for the deliberation room."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class TranscriptEntry:
    """A single message in the transcript."""

    timestamp: float
    sender: str
    body: str
    is_swarm_signal: bool = False


class TranscriptBuffer:
    """Rolling buffer of recent messages for LLM summarization."""

    # Maximum size of a single message body (64 KB)
    MAX_ENTRY_LENGTH = 65_536

    def __init__(
        self,
        max_messages: int = 200,
        max_age_seconds: int = 1800,
        max_tokens: int = 4000,
    ) -> None:
        self.max_messages = max_messages
        self.max_age_seconds = max_age_seconds
        self.max_tokens = max_tokens
        self._entries: list[TranscriptEntry] = []
        self._unique_senders: set[str] = set()

    def add(self, entry: TranscriptEntry) -> None:
        """Add a message and prune old entries."""
        # Truncate oversized message bodies to prevent memory abuse
        if len(entry.body) > self.MAX_ENTRY_LENGTH:
            entry.body = entry.body[: self.MAX_ENTRY_LENGTH] + " [truncated]"
        self._entries.append(entry)
        if not entry.is_swarm_signal:
            self._unique_senders.add(entry.sender)
        self._prune()

    def _prune(self) -> None:
        """Remove entries beyond max count or max age."""
        now = time.time()
        cutoff = now - self.max_age_seconds
        self._entries = [e for e in self._entries if e.timestamp >= cutoff]
        if len(self._entries) > self.max_messages:
            self._entries = self._entries[-self.max_messages :]
        # Rebuild unique senders from remaining entries
        self._unique_senders = {
            e.sender for e in self._entries if not e.is_swarm_signal
        }

    @property
    def message_count(self) -> int:
        """Number of human (non-signal) messages."""
        return sum(1 for e in self._entries if not e.is_swarm_signal)

    @property
    def participant_count(self) -> int:
        """Number of unique human senders."""
        return len(self._unique_senders)

    def token_estimate(self) -> int:
        """Rough token count using word_count * 1.3 heuristic."""
        total_words = sum(len(e.body.split()) for e in self._entries)
        return int(total_words * 1.3)

    def to_prompt_text(self) -> str:
        """Format transcript for LLM consumption.

        Truncates from the oldest messages if token estimate exceeds max.
        """
        entries = list(self._entries)

        # Truncate oldest entries if too long
        while entries and self._estimate_tokens(entries) > self.max_tokens:
            entries.pop(0)

        lines: list[str] = []
        for entry in entries:
            prefix = "[SWARM SIGNAL] " if entry.is_swarm_signal else ""
            ts = time.strftime("%H:%M", time.localtime(entry.timestamp))
            lines.append(f"[{ts}] {prefix}{entry.sender}: {entry.body}")
        return "\n".join(lines)

    @staticmethod
    def _estimate_tokens(entries: list[TranscriptEntry]) -> int:
        total_words = sum(len(e.body.split()) for e in entries)
        return int(total_words * 1.3)

    def clear(self) -> None:
        """Reset the buffer after a round completes."""
        self._entries.clear()
        self._unique_senders.clear()
