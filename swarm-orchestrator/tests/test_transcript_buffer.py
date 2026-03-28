"""Tests for TranscriptBuffer."""

from __future__ import annotations

import time

from orchestrator.matrix.transcript import TranscriptBuffer, TranscriptEntry


def _entry(body: str, sender: str = "alice", is_signal: bool = False) -> TranscriptEntry:
    return TranscriptEntry(
        timestamp=time.time(),
        sender=sender,
        body=body,
        is_swarm_signal=is_signal,
    )


class TestTranscriptBuffer:
    def test_add_and_count(self):
        buf = TranscriptBuffer(max_messages=100)
        buf.add(_entry("hello"))
        buf.add(_entry("world"))
        assert buf.message_count == 2

    def test_swarm_signals_not_counted(self):
        buf = TranscriptBuffer()
        buf.add(_entry("human msg"))
        buf.add(_entry("signal", is_signal=True))
        assert buf.message_count == 1

    def test_participant_count(self):
        buf = TranscriptBuffer()
        buf.add(_entry("hi", sender="alice"))
        buf.add(_entry("hello", sender="bob"))
        buf.add(_entry("again", sender="alice"))
        assert buf.participant_count == 2

    def test_signal_senders_not_counted(self):
        buf = TranscriptBuffer()
        buf.add(_entry("hi", sender="alice"))
        buf.add(_entry("signal", sender="swarm-bot", is_signal=True))
        assert buf.participant_count == 1

    def test_max_messages_prune(self):
        buf = TranscriptBuffer(max_messages=5)
        for i in range(10):
            buf.add(_entry(f"msg {i}"))
        text = buf.to_prompt_text()
        assert "msg 9" in text
        assert "msg 0" not in text

    def test_to_prompt_text_format(self):
        buf = TranscriptBuffer()
        buf.add(_entry("hello world", sender="alice"))
        text = buf.to_prompt_text()
        assert "alice: hello world" in text

    def test_signal_prefix_in_prompt(self):
        buf = TranscriptBuffer()
        buf.add(_entry("swarm data", sender="bot", is_signal=True))
        text = buf.to_prompt_text()
        assert "[SWARM SIGNAL]" in text

    def test_token_estimate(self):
        buf = TranscriptBuffer()
        # 10 words * 1.3 = 13 tokens
        buf.add(_entry("one two three four five six seven eight nine ten"))
        est = buf.token_estimate()
        assert est == 13

    def test_clear(self):
        buf = TranscriptBuffer()
        buf.add(_entry("msg", sender="alice"))
        buf.clear()
        assert buf.message_count == 0
        assert buf.participant_count == 0
        assert buf.to_prompt_text() == ""

    def test_truncation_on_token_limit(self):
        buf = TranscriptBuffer(max_tokens=20)
        for i in range(50):
            buf.add(_entry(f"word{i} " * 5, sender="alice"))
        text = buf.to_prompt_text()
        # Should have truncated old entries
        assert len(text.split()) < 100
