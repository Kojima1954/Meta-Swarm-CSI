"""Topology manager — loads and validates the swarm topology."""

from __future__ import annotations

import tomllib
from pathlib import Path

import structlog

from orchestrator.models.topology import SwarmNode, Topology

log = structlog.get_logger()


class TopologyManager:
    """Loads the swarm topology from a TOML file."""

    def __init__(self, topology_path: str, self_node_id: str) -> None:
        self._path = topology_path
        self._self_node_id = self_node_id
        self._topology: Topology | None = None

    def load(self) -> Topology:
        """Parse topology.toml and validate."""
        path = Path(self._path)
        if not path.exists():
            raise FileNotFoundError(f"Topology file not found: {self._path}")

        with open(path, "rb") as f:
            data = tomllib.load(f)

        raw_nodes = data.get("nodes", [])
        nodes = [SwarmNode(**n) for n in raw_nodes]
        topology = Topology(nodes=nodes)

        topology.validate_self_exists(self._self_node_id)

        log.info(
            "topology.loaded",
            total_nodes=len(nodes),
            adjacent=len(topology.adjacent_nodes),
            self_node=self._self_node_id,
        )
        self._topology = topology
        return topology

    @property
    def topology(self) -> Topology:
        if self._topology is None:
            raise RuntimeError("Topology not loaded. Call load() first.")
        return self._topology
