"""Topology models — nodes and their relationships in the swarm."""

from __future__ import annotations

from pydantic import BaseModel, Field, computed_field


class SwarmNode(BaseModel):
    """A single node in the swarm network."""

    id: str = Field(alias="id")
    name: str = ""
    domain: str = ""
    public_key: str = ""
    role: str = "participant"
    is_self: bool = False

    model_config = {"populate_by_name": True}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def actor_uri(self) -> str:
        """Derive the ActivityPub actor URI from domain and id."""
        if self.domain:
            return f"https://{self.domain}/users/{self.id}"
        return ""


class Topology(BaseModel):
    """The full swarm topology loaded from topology.toml."""

    nodes: list[SwarmNode] = Field(default_factory=list)

    @property
    def self_node(self) -> SwarmNode | None:
        """Return the local node (is_self=true)."""
        for node in self.nodes:
            if node.is_self:
                return node
        return None

    @property
    def adjacent_nodes(self) -> list[SwarmNode]:
        """All non-self nodes with role participant or facilitator."""
        return [
            n
            for n in self.nodes
            if not n.is_self and n.role in ("participant", "facilitator")
        ]

    def get_node(self, node_id: str) -> SwarmNode | None:
        """Look up a node by ID."""
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    def validate_self_exists(self, self_node_id: str) -> None:
        """Raise if the self node ID doesn't appear in the topology."""
        node = self.get_node(self_node_id)
        if node is None or not node.is_self:
            raise ValueError(
                f"Node '{self_node_id}' not found as is_self=true in topology"
            )
