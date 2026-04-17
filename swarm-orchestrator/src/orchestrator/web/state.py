"""Runtime state container shared between the orchestrator core and the web API.

This is a thin dependency-injection holder — the orchestrator wires one of these
at startup and hands it to the FastAPI app. All fields are optional so tests can
build a partial state for focused testing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from orchestrator.config import Settings
    from orchestrator.matrix.transcript import TranscriptBuffer
    from orchestrator.models.topology import Topology
    from orchestrator.rag.store import VectorStore
    from orchestrator.rounds.controller import RoundController
    from orchestrator.web.events import EventBus


@dataclass
class AppState:
    settings: "Settings"
    controller: "RoundController | None" = None
    transcript: "TranscriptBuffer | None" = None
    topology: "Topology | None" = None
    vector_store: "VectorStore | None" = None
    events: "EventBus | None" = None
    started_at: float = field(default_factory=time.time)

    def uptime_seconds(self) -> float:
        return max(0.0, time.time() - self.started_at)

    def safe_settings(self) -> dict[str, Any]:
        """Return a sanitized copy of settings (no secrets) for the UI."""
        s = self.settings
        return {
            "node": s.node.model_dump(),
            "matrix": {
                "homeserver_url": s.matrix.homeserver_url,
                "server_name": s.matrix.server_name,
                "room_alias": s.matrix.room_alias,
                "user_id": s.matrix.user_id,
            },
            "ai": s.ai.model_dump(),
            "federation": {
                "gotosocial_url": s.federation.gotosocial_url,
                "protocol": s.federation.protocol,
            },
            "rounds": s.rounds.model_dump(),
            "logging": s.logging.model_dump(),
            "web": {
                "enabled": s.web.enabled,
                "host": s.web.host,
                "port": s.web.port,
                "auth_required": bool(s.web.api_token),
            },
        }
