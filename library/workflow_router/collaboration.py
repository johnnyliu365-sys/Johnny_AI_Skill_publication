"""Typed topology selection for the detachable collaboration control plane."""

from __future__ import annotations

from .contracts import (
    CapabilityRef,
    CollaborationTopology,
    CollaborationTopologyPlan,
)


class CollaborationTopologyResolver:
    """Resolve only a finite Agent-count choice and named capabilities."""

    def select(
        self,
        *,
        available_agent_count: int,
        control_plane: CapabilityRef,
        implementation_owner: CapabilityRef,
        available_capabilities: tuple[CapabilityRef, ...],
        reviewer: CapabilityRef | None = None,
    ) -> CollaborationTopologyPlan:
        """Reject unknown counts and unavailable capabilities before any grant."""

        if available_agent_count not in (1, 2):
            raise ValueError("available_agent_count must be one or two")
        if control_plane.capability_id == implementation_owner.capability_id:
            raise ValueError("control-plane and implementation capabilities must be distinct")
        if not available_capabilities:
            raise ValueError("available capabilities are required")
        selected_reviewer = reviewer or control_plane
        available_ids = {capability.capability_id for capability in available_capabilities}
        if control_plane.capability_id not in available_ids:
            raise ValueError("control-plane capability is unavailable")
        if implementation_owner.capability_id not in available_ids:
            raise ValueError("implementation capability is unavailable")
        if selected_reviewer.capability_id not in available_ids:
            raise ValueError("reviewer capability is unavailable")
        topology = (
            CollaborationTopology.ONE_IMPLEMENTATION_AGENT
            if available_agent_count == 1
            else CollaborationTopology.TWO_COLLABORATING_AGENTS
        )
        return CollaborationTopologyPlan(
            topology=topology,
            control_plane=control_plane,
            implementation_owner=implementation_owner,
            reviewer=selected_reviewer,
        )
