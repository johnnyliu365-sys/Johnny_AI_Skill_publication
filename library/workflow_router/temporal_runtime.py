"""Temporal durable-wait skeleton for a router decision round."""

from __future__ import annotations

from datetime import timedelta

from pydantic import model_validator
from temporalio import activity, workflow

from .contracts import (
    AuthorityState,
    ContinuationDirective,
    RouterDecision,
    RouterEvent,
    RouterEventKind,
    RouterModel,
    RouterState,
)
from .profile import ProjectWorkflowProfile
from .router import RouterEngine


class RouterRoundInput(RouterModel):
    """Serializable input for one deterministic router activity round."""

    router_state: RouterState
    router_event: RouterEvent
    profile: ProjectWorkflowProfile


class ApprovalSignal(RouterModel):
    """A validated event supplied by a human approval interface."""

    router_event: RouterEvent
    authority_state: AuthorityState

    @model_validator(mode="after")
    def authority_matches_approval_event(self) -> ApprovalSignal:
        """Reject signals that would grant or deny authority without the matching event."""

        expected = {
            RouterEventKind.APPROVAL_GRANTED: AuthorityState.APPROVED,
            RouterEventKind.APPROVAL_DENIED: AuthorityState.DENIED,
        }.get(self.router_event.kind)
        if expected is None or self.authority_state is not expected:
            raise ValueError("approval signal event and authority state must match")
        return self


@activity.defn(name="router-framework-route-round")
def route_round(input: RouterRoundInput) -> RouterDecision:
    """Execute the pure router inside an Activity, never inside durable workflow code."""

    return RouterEngine().decide(
        state=input.router_state,
        event=input.router_event,
        profile=input.profile,
    )


@workflow.defn(name="router-framework-approval-workflow")
class RouterApprovalWorkflow:
    """Wait durably for a typed human signal whenever a router round suspends."""

    def __init__(self) -> None:
        self._pending: RouterDecision | None = None
        self._approval: ApprovalSignal | None = None

    @workflow.signal
    def submit_approval(self, signal: ApprovalSignal) -> None:
        """Receive validated human approval or denial as the next router event."""

        self._approval = signal

    @workflow.query
    def pending_decision(self) -> RouterDecision | None:
        """Expose the pending decision without exposing any raw Context packet."""

        return self._pending

    @workflow.run
    async def run(self, input: RouterRoundInput) -> RouterDecision:
        """Run once, persistently wait if suspended, then evaluate the supplied approval event."""

        first = await workflow.execute_activity(
            route_round,
            input,
            start_to_close_timeout=timedelta(seconds=30),
        )
        if first.continuation is not ContinuationDirective.WAIT_FOR_HUMAN:
            return first
        self._pending = first
        await workflow.wait_condition(lambda: self._approval is not None)
        approval = self._approval
        if approval is None:
            raise RuntimeError("approval signal disappeared before router resume")
        return await workflow.execute_activity(
            route_round,
            RouterRoundInput(
                router_state=input.router_state.model_copy(
                    update={"authority_state": approval.authority_state}
                ),
                router_event=approval.router_event,
                profile=input.profile,
            ),
            start_to_close_timeout=timedelta(seconds=30),
        )
