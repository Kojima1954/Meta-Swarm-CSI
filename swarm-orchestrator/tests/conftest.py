"""Shared test fixtures."""

from __future__ import annotations

import pytest

from orchestrator.config import (
    AIConfig,
    FederationConfig,
    LoggingConfig,
    MatrixConfig,
    NodeConfig,
    RoundsConfig,
    SecurityConfig,
    Settings,
)
from orchestrator.models.topology import SwarmNode, Topology


@pytest.fixture
def sample_settings() -> Settings:
    return Settings(
        node=NodeConfig(id="node-alpha", name="Node Alpha", domain="alpha.test"),
        matrix=MatrixConfig(
            homeserver_url="http://conduit:6167",
            server_name="alpha.test",
            room_alias="#deliberation:alpha.test",
            user_id="@orchestrator:alpha.test",
            password="testpass",
        ),
        ai=AIConfig(),
        federation=FederationConfig(access_token="test-token"),
        rounds=RoundsConfig(mode="timer", interval_seconds=10),
        security=SecurityConfig(
            key_path="/tmp/test.key", public_key_path="/tmp/test.pub"
        ),
        logging=LoggingConfig(level="debug"),
    )


@pytest.fixture
def sample_topology() -> Topology:
    return Topology(
        nodes=[
            SwarmNode(
                id="node-alpha",
                name="Node Alpha",
                domain="alpha.test",
                public_key="",
                role="participant",
                is_self=True,
            ),
            SwarmNode(
                id="node-beta",
                name="Node Beta",
                domain="beta.test",
                public_key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
                role="participant",
                is_self=False,
            ),
        ]
    )
