"""Topology manager — loads and validates the swarm topology."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Union

import structlog

from orchestrator.models.topology import SwarmNode, Topology
from orchestrator.topology.murmuration import MurmurationTopology

if TYPE_CHECKING:
    from orchestrator.config import TopologyConfig

log = structlog.get_logger()


class TopologyManager:
    """Loads the swarm topology from a TOML file.

    When *topology_config* is provided and ``topology_config.mode == "murmuration"``,
    the loaded :class:`Topology` is wrapped in a :class:`MurmurationTopology` that
    self-organises the neighbor set via Kademlia-XOR band selection.

    If *topology_config* is omitted (or ``mode == "static"``), behavior is identical
    to the original static implementation — full backward compatibility.
    """

    def __init__(
        self,
        topology_path: str,
        self_node_id: str,
        topology_config: "TopologyConfig | None" = None,
        self_public_key_b64: str = "",
    ) -> None:
        self._path = topology_path
        self._self_node_id = self_node_id
        self._topo_config = topology_config
        self._self_public_key_b64 = self_public_key_b64
        self._topology: Union[Topology, MurmurationTopology, None] = None

    def load(self) -> Union[Topology, MurmurationTopology]:
        """Parse topology.toml and validate; wrap in MurmurationTopology if configured."""
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

        # Murmuration mode: wrap in dynamic topology
        cfg = self._topo_config
        if cfg and cfg.mode == "murmuration" and self._self_public_key_b64:
            murmuration = MurmurationTopology(
                seed_topology=topology,
                self_public_key_b64=self._self_public_key_b64,
                state_path=cfg.state_path,
                max_neighbors=cfg.max_neighbors,
            )
            murmuration.bootstrap()
            log.info(
                "topology.murmuration_active",
                neighbors=len(murmuration.adjacent_nodes),
                max_neighbors=cfg.max_neighbors,
                rewire_every=cfg.rewire_every_n_rounds,
            )
            self._topology = murmuration
            return murmuration

        self._topology = topology
        return topology

    @property
    def topology(self) -> Union[Topology, MurmurationTopology]:
        if self._topology is None:
            raise RuntimeError("Topology not loaded. Call load() first.")
        return self._topology
