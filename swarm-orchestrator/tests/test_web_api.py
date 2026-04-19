"""Tests for the FastAPI web API layer."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from orchestrator.matrix.transcript import TranscriptBuffer, TranscriptEntry
from orchestrator.models.summary import SwarmSummary
from orchestrator.rounds.controller import Phase
from orchestrator.web import AppState, EventBus, build_app


@pytest.fixture
def app_state(sample_settings, sample_topology):
    transcript = TranscriptBuffer()
    now = time.time()
    transcript.add(TranscriptEntry(timestamp=now - 5, sender="alice", body="hi"))
    transcript.add(
        TranscriptEntry(
            timestamp=now, sender="bot", body="[SWARM]", is_swarm_signal=True
        )
    )

    controller = MagicMock()
    controller.phase = Phase.DISCUSS
    controller.round_number = 3
    controller.trigger_manual = MagicMock()

    return AppState(
        settings=sample_settings,
        controller=controller,
        transcript=transcript,
        topology=sample_topology,
        events=EventBus(),
    )


@pytest.fixture
def client(app_state):
    app = build_app(app_state)
    return TestClient(app)


class TestHealthAndStatus:
    def test_health(self, client):
        r = client.get("/api/v1/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

    def test_status_reports_phase_and_round(self, client):
        r = client.get("/api/v1/status")
        assert r.status_code == 200
        data = r.json()
        assert data["phase"] == "DISCUSS"
        assert data["round_number"] == 3
        assert data["node"]["id"] == "node-alpha"
        assert data["transcript"]["message_count"] == 1  # one non-signal
        assert data["transcript"]["participant_count"] == 1

    def test_status_when_no_controller(self, sample_settings):
        state = AppState(settings=sample_settings, events=EventBus())
        client = TestClient(build_app(state))
        r = client.get("/api/v1/status")
        assert r.status_code == 200
        assert r.json()["phase"] == "UNKNOWN"


class TestTopology:
    def test_topology_lists_nodes(self, client):
        r = client.get("/api/v1/topology")
        assert r.status_code == 200
        data = r.json()
        assert data["self_id"] == "node-alpha"
        assert len(data["nodes"]) == 2
        ids = {n["id"] for n in data["nodes"]}
        assert ids == {"node-alpha", "node-beta"}
        # Private key material is never exposed
        for n in data["nodes"]:
            assert "public_key" not in n
            assert "has_public_key" in n


class TestTranscript:
    def test_transcript_returns_entries(self, client):
        r = client.get("/api/v1/transcript")
        assert r.status_code == 200
        data = r.json()
        assert len(data["entries"]) == 2
        assert data["entries"][0]["sender"] == "alice"
        assert data["entries"][1]["is_swarm_signal"] is True

    def test_transcript_respects_limit(self, client):
        r = client.get("/api/v1/transcript?limit=1")
        assert r.status_code == 200
        assert len(r.json()["entries"]) == 1


class TestConfig:
    def test_config_redacts_secrets(self, client):
        r = client.get("/api/v1/config")
        assert r.status_code == 200
        data = r.json()
        # Matrix password is never exposed
        assert "password" not in data["matrix"]
        # Federation token is never exposed
        assert "access_token" not in data["federation"]
        # Node info is visible
        assert data["node"]["id"] == "node-alpha"


class TestRoundTrigger:
    def test_trigger_requires_token_when_none_configured(self, client):
        # Default sample_settings has no api_token, so endpoint returns 503
        r = client.post("/api/v1/rounds/trigger")
        assert r.status_code == 503

    def test_trigger_rejects_missing_auth(self, app_state):
        app_state.settings.web.api_token = "secret"
        client = TestClient(build_app(app_state))
        r = client.post("/api/v1/rounds/trigger")
        assert r.status_code == 401

    def test_trigger_rejects_wrong_token(self, app_state):
        app_state.settings.web.api_token = "secret"
        client = TestClient(build_app(app_state))
        r = client.post(
            "/api/v1/rounds/trigger",
            headers={"Authorization": "Bearer nope"},
        )
        assert r.status_code == 401

    def test_trigger_accepts_correct_token(self, app_state):
        app_state.settings.web.api_token = "secret"
        client = TestClient(build_app(app_state))
        r = client.post(
            "/api/v1/rounds/trigger",
            headers={"Authorization": "Bearer secret"},
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True
        app_state.controller.trigger_manual.assert_called_once()


class TestSummariesFromEvents:
    @pytest.mark.asyncio
    async def test_summaries_list_pulls_from_event_history(self, app_state):
        summary = SwarmSummary(
            round_number=1,
            source_node_id="node-alpha",
            key_positions=["Position A"],
        )
        await app_state.events.publish(
            "summary.created",
            origin="local",
            source_name="Node Alpha",
            summary=summary.model_dump(mode="json"),
        )
        client = TestClient(build_app(app_state))
        r = client.get("/api/v1/summaries")
        assert r.status_code == 200
        data = r.json()
        assert len(data["summaries"]) == 1
        assert data["summaries"][0]["source_node_id"] == "node-alpha"


class TestStaticAssets:
    def test_root_serves_index_html(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "Swarm Orchestrator" in r.text
        assert r.headers["content-type"].startswith("text/html")

    def test_spa_fallback_serves_index_for_unknown_paths(self, client):
        r = client.get("/summaries")
        assert r.status_code == 200
        assert "Swarm Orchestrator" in r.text

    def test_api_404_not_spa_fallback(self, client):
        r = client.get("/api/v1/nonexistent")
        assert r.status_code == 404
