"""Tests for SwarmSummary model."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from orchestrator.models.summary import SwarmSummary


def _make_summary(**overrides) -> SwarmSummary:
    defaults = {
        "round_number": 1,
        "topic": "Water purification",
        "source_node_id": "node-alpha",
        "published": datetime(2026, 3, 26, 14, 30, tzinfo=timezone.utc),
        "participant_count": 7,
        "message_count": 43,
        "key_positions": ["Boiling is reliable", "Solar disinfection viable"],
        "emerging_consensus": "Multi-method approach preferred",
        "dissenting_views": ["Chlorine tablets dismissed too quickly"],
        "open_questions": ["Shelf life of ceramic filters?"],
        "parent_summary_ids": [],
    }
    defaults.update(overrides)
    return SwarmSummary(**defaults)


class TestSwarmSummary:
    def test_basic_creation(self):
        s = _make_summary()
        assert s.round_number == 1
        assert s.source_node_id == "node-alpha"
        assert len(s.key_positions) == 2

    def test_summary_id(self):
        s = _make_summary(round_number=3, source_node_id="node-beta")
        assert s.summary_id() == "node-beta:round-3"

    def test_round_number_must_be_positive(self):
        with pytest.raises(ValidationError):
            _make_summary(round_number=0)

    def test_key_positions_required(self):
        with pytest.raises(ValidationError):
            _make_summary(key_positions=[])

    def test_key_positions_must_have_content(self):
        with pytest.raises(ValidationError):
            _make_summary(key_positions=["", "  "])

    def test_to_text(self):
        s = _make_summary()
        text = s.to_text()
        assert "node-alpha" in text
        assert "Boiling" in text
        assert "Multi-method" in text

    def test_jsonld_roundtrip(self):
        original = _make_summary(round_number=5)
        jsonld = original.to_jsonld()

        assert jsonld["type"] == "swarm:SwarmSummary"
        assert jsonld["swarm:roundNumber"] == 5
        assert jsonld["@context"][0] == "https://www.w3.org/ns/activitystreams"

        restored = SwarmSummary.from_jsonld(jsonld)
        assert restored.round_number == original.round_number
        assert restored.source_node_id == original.source_node_id
        assert restored.key_positions == original.key_positions
        assert restored.emerging_consensus == original.emerging_consensus
        assert restored.dissenting_views == original.dissenting_views
        assert restored.open_questions == original.open_questions

    def test_jsonld_preserves_parent_ids(self):
        s = _make_summary(parent_summary_ids=["node-beta:round-2", "node-gamma:round-2"])
        jsonld = s.to_jsonld()
        restored = SwarmSummary.from_jsonld(jsonld)
        assert restored.parent_summary_ids == ["node-beta:round-2", "node-gamma:round-2"]

    def test_defaults(self):
        s = SwarmSummary(
            round_number=1,
            source_node_id="x",
            key_positions=["pos"],
        )
        assert s.dissenting_views == []
        assert s.open_questions == []
        assert s.parent_summary_ids == []
        assert s.participant_count == 0
