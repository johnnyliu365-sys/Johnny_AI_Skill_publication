"""Pure in-memory project subscription and runner lifecycle registry."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Protocol, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from library.workflow_router.contracts import OpaqueMetadataId, ProjectId


class _StrictModel(BaseModel):
    """Immutable strict values at the registry boundary."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
    )


class RunnerStarted(_StrictModel):
    """A lifecycle port's successful start result."""

    status: Literal["STARTED"] = "STARTED"
    runner_ref: OpaqueMetadataId


class RunnerStartCapabilityUnavailable(_StrictModel):
    """A lifecycle port's unavailable start result."""

    status: Literal["CAPABILITY_UNAVAILABLE"] = "CAPABILITY_UNAVAILABLE"
    runner_ref: None = None


RunnerStartResult: TypeAlias = Annotated[
    RunnerStarted | RunnerStartCapabilityUnavailable,
    Field(discriminator="status"),
]


class RunnerStopped(_StrictModel):
    """A lifecycle port's successful stop result."""

    status: Literal["STOPPED"] = "STOPPED"


class RunnerStopCapabilityUnavailable(_StrictModel):
    """A lifecycle port's unavailable stop result."""

    status: Literal["CAPABILITY_UNAVAILABLE"] = "CAPABILITY_UNAVAILABLE"


RunnerStopResult: TypeAlias = Annotated[
    RunnerStopped | RunnerStopCapabilityUnavailable,
    Field(discriminator="status"),
]


class RunnerLifecyclePort(Protocol):
    """The injected, effect-owning lifecycle boundary."""

    def start(self, project_ref: ProjectId) -> RunnerStartResult:
        """Start one project runner or return finite unavailability."""

    def stop(
        self,
        project_ref: ProjectId,
        runner_ref: OpaqueMetadataId,
    ) -> RunnerStopResult:
        """Stop one project runner or return finite unavailability."""


class ProjectRunnerRegistryDecision(str, Enum):
    """Finite decisions returned by the in-memory project registry."""

    SUBSCRIBED = "SUBSCRIBED"
    REUSED = "REUSED"
    REMOVED = "REMOVED"
    DETACHED = "DETACHED"
    UNINSTALLED = "UNINSTALLED"
    DUPLICATE_SUBSCRIPTION = "DUPLICATE_SUBSCRIPTION"
    FOREIGN_SUBSCRIPTION = "FOREIGN_SUBSCRIPTION"
    NOT_FOUND = "NOT_FOUND"
    RUNNER_START_UNAVAILABLE = "RUNNER_START_UNAVAILABLE"
    RUNNER_STOP_UNAVAILABLE = "RUNNER_STOP_UNAVAILABLE"


class ProjectRunnerRegistryResult(_StrictModel):
    """Closed result state with no raw lifecycle or caller diagnostics."""

    decision: ProjectRunnerRegistryDecision
    project_ref: ProjectId
    subscription_id: OpaqueMetadataId | None
    runner_ref: OpaqueMetadataId | None

    @model_validator(mode="after")
    def result_fields_match_decision(self) -> Self:
        """Keep subscription and runner nullability tied to finite outcomes."""

        if self.decision in (
            ProjectRunnerRegistryDecision.SUBSCRIBED,
            ProjectRunnerRegistryDecision.REUSED,
            ProjectRunnerRegistryDecision.DUPLICATE_SUBSCRIPTION,
        ) and (self.subscription_id is None or self.runner_ref is None):
            raise ValueError("active subscription decisions require subscription and runner")
        if self.decision is ProjectRunnerRegistryDecision.RUNNER_START_UNAVAILABLE and (
            self.subscription_id is not None or self.runner_ref is not None
        ):
            raise ValueError("start-unavailable decisions cannot retain state")
        if self.decision is ProjectRunnerRegistryDecision.FOREIGN_SUBSCRIPTION and (
            self.subscription_id is None or self.runner_ref is not None
        ):
            raise ValueError("foreign subscription decisions cannot expose a runner")
        if self.decision in (
            ProjectRunnerRegistryDecision.REMOVED,
            ProjectRunnerRegistryDecision.DETACHED,
            ProjectRunnerRegistryDecision.UNINSTALLED,
            ProjectRunnerRegistryDecision.RUNNER_STOP_UNAVAILABLE,
        ) and self.runner_ref is None:
            raise ValueError("runner lifecycle decisions require the affected runner")
        return self


class _SubscriptionRequest(_StrictModel):
    """Validated public registration/removal arguments."""

    project_ref: ProjectId
    subscription_id: OpaqueMetadataId


class _ProjectRequest(_StrictModel):
    """Validated public project-only arguments."""

    project_ref: ProjectId


class _ProjectRunnerState(_StrictModel):
    """One project state row; tuples avoid an unbounded dynamic map."""

    project_ref: ProjectId
    runner_ref: OpaqueMetadataId
    subscription_ids: tuple[OpaqueMetadataId, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def subscriptions_are_unique(self) -> Self:
        """Keep each project row free of duplicate subscription ownership."""

        if len(self.subscription_ids) != len(set(self.subscription_ids)):
            raise ValueError("subscriptions must be unique within a project")
        return self


_START_RESULT_ADAPTER: TypeAdapter[RunnerStartResult] = TypeAdapter(RunnerStartResult)
_STOP_RESULT_ADAPTER: TypeAdapter[RunnerStopResult] = TypeAdapter(RunnerStopResult)


def _find_project_state(
    states: tuple[_ProjectRunnerState, ...],
    project_ref: ProjectId,
) -> _ProjectRunnerState | None:
    """Find a project row without exposing mutable storage."""

    for state in states:
        if state.project_ref == project_ref:
            return state
    return None


def _find_subscription_owner(
    states: tuple[_ProjectRunnerState, ...],
    subscription_id: OpaqueMetadataId,
) -> _ProjectRunnerState | None:
    """Find the unique project that owns a subscription."""

    for state in states:
        if subscription_id in state.subscription_ids:
            return state
    return None


def _replace_project_state(
    states: tuple[_ProjectRunnerState, ...],
    replacement: _ProjectRunnerState,
) -> tuple[_ProjectRunnerState, ...]:
    """Replace exactly one project row."""

    return tuple(
        replacement if state.project_ref == replacement.project_ref else state
        for state in states
    )


def _remove_project_state(
    states: tuple[_ProjectRunnerState, ...],
    project_ref: ProjectId,
) -> tuple[_ProjectRunnerState, ...]:
    """Remove exactly one project row after a successful stop."""

    return tuple(state for state in states if state.project_ref != project_ref)


def _revalidate_start_result(value: RunnerStartResult) -> RunnerStartResult:
    """Round-trip an injected start result through its ordinary validator."""

    return _START_RESULT_ADAPTER.validate_python(value, strict=True)


def _revalidate_stop_result(value: RunnerStopResult) -> RunnerStopResult:
    """Round-trip an injected stop result through its ordinary validator."""

    return _STOP_RESULT_ADAPTER.validate_python(value, strict=True)


class ProjectRunnerRegistry:
    """Manage project subscriptions while delegating runner effects to one port."""

    def __init__(self, lifecycle: RunnerLifecyclePort) -> None:
        self._lifecycle = lifecycle
        self._states: tuple[_ProjectRunnerState, ...] = ()

    def register_subscription(
        self,
        project_ref: ProjectId,
        subscription_id: OpaqueMetadataId,
    ) -> ProjectRunnerRegistryResult:
        """Register a subscription, starting at most one runner per project."""

        request = _SubscriptionRequest(
            project_ref=project_ref,
            subscription_id=subscription_id,
        )
        existing = _find_project_state(self._states, request.project_ref)
        if existing is not None:
            if request.subscription_id in existing.subscription_ids:
                return ProjectRunnerRegistryResult(
                    decision=ProjectRunnerRegistryDecision.DUPLICATE_SUBSCRIPTION,
                    project_ref=request.project_ref,
                    subscription_id=request.subscription_id,
                    runner_ref=existing.runner_ref,
                )
            if _find_subscription_owner(self._states, request.subscription_id) is not None:
                return ProjectRunnerRegistryResult(
                    decision=ProjectRunnerRegistryDecision.FOREIGN_SUBSCRIPTION,
                    project_ref=request.project_ref,
                    subscription_id=request.subscription_id,
                    runner_ref=None,
                )
            updated = _ProjectRunnerState(
                project_ref=existing.project_ref,
                runner_ref=existing.runner_ref,
                subscription_ids=existing.subscription_ids + (request.subscription_id,),
            )
            self._states = _replace_project_state(self._states, updated)
            return ProjectRunnerRegistryResult(
                decision=ProjectRunnerRegistryDecision.REUSED,
                project_ref=request.project_ref,
                subscription_id=request.subscription_id,
                runner_ref=existing.runner_ref,
            )

        if _find_subscription_owner(self._states, request.subscription_id) is not None:
            return ProjectRunnerRegistryResult(
                decision=ProjectRunnerRegistryDecision.FOREIGN_SUBSCRIPTION,
                project_ref=request.project_ref,
                subscription_id=request.subscription_id,
                runner_ref=None,
            )

        start_result = _revalidate_start_result(self._lifecycle.start(request.project_ref))
        if isinstance(start_result, RunnerStartCapabilityUnavailable):
            return ProjectRunnerRegistryResult(
                decision=ProjectRunnerRegistryDecision.RUNNER_START_UNAVAILABLE,
                project_ref=request.project_ref,
                subscription_id=None,
                runner_ref=None,
            )

        state = _ProjectRunnerState(
            project_ref=request.project_ref,
            runner_ref=start_result.runner_ref,
            subscription_ids=(request.subscription_id,),
        )
        self._states = self._states + (state,)
        return ProjectRunnerRegistryResult(
            decision=ProjectRunnerRegistryDecision.SUBSCRIBED,
            project_ref=request.project_ref,
            subscription_id=request.subscription_id,
            runner_ref=start_result.runner_ref,
        )

    def remove_subscription(
        self,
        project_ref: ProjectId,
        subscription_id: OpaqueMetadataId,
    ) -> ProjectRunnerRegistryResult:
        """Remove one subscription and stop only when it is the final one."""

        request = _SubscriptionRequest(
            project_ref=project_ref,
            subscription_id=subscription_id,
        )
        existing = _find_project_state(self._states, request.project_ref)
        if existing is None or request.subscription_id not in existing.subscription_ids:
            if _find_subscription_owner(self._states, request.subscription_id) is not None:
                return ProjectRunnerRegistryResult(
                    decision=ProjectRunnerRegistryDecision.FOREIGN_SUBSCRIPTION,
                    project_ref=request.project_ref,
                    subscription_id=request.subscription_id,
                    runner_ref=None,
                )
            return ProjectRunnerRegistryResult(
                decision=ProjectRunnerRegistryDecision.NOT_FOUND,
                project_ref=request.project_ref,
                subscription_id=request.subscription_id,
                runner_ref=None,
            )

        if len(existing.subscription_ids) > 1:
            updated = _ProjectRunnerState(
                project_ref=existing.project_ref,
                runner_ref=existing.runner_ref,
                subscription_ids=tuple(
                    value
                    for value in existing.subscription_ids
                    if value != request.subscription_id
                ),
            )
            self._states = _replace_project_state(self._states, updated)
            return ProjectRunnerRegistryResult(
                decision=ProjectRunnerRegistryDecision.REMOVED,
                project_ref=request.project_ref,
                subscription_id=request.subscription_id,
                runner_ref=existing.runner_ref,
            )

        stop_result = _revalidate_stop_result(
            self._lifecycle.stop(request.project_ref, existing.runner_ref)
        )
        if isinstance(stop_result, RunnerStopCapabilityUnavailable):
            return ProjectRunnerRegistryResult(
                decision=ProjectRunnerRegistryDecision.RUNNER_STOP_UNAVAILABLE,
                project_ref=request.project_ref,
                subscription_id=request.subscription_id,
                runner_ref=existing.runner_ref,
            )

        self._states = _remove_project_state(self._states, request.project_ref)
        return ProjectRunnerRegistryResult(
            decision=ProjectRunnerRegistryDecision.REMOVED,
            project_ref=request.project_ref,
            subscription_id=request.subscription_id,
            runner_ref=existing.runner_ref,
        )

    def detach_project(
        self,
        project_ref: ProjectId,
    ) -> ProjectRunnerRegistryResult:
        """Stop and remove one active project registration."""

        request = _ProjectRequest(project_ref=project_ref)
        return self._stop_project(
            request.project_ref,
            ProjectRunnerRegistryDecision.DETACHED,
        )

    def uninstall_project(
        self,
        project_ref: ProjectId,
    ) -> ProjectRunnerRegistryResult:
        """Stop and remove one active project during uninstall."""

        request = _ProjectRequest(project_ref=project_ref)
        return self._stop_project(
            request.project_ref,
            ProjectRunnerRegistryDecision.UNINSTALLED,
        )

    def _stop_project(
        self,
        project_ref: ProjectId,
        success_decision: Literal[
            ProjectRunnerRegistryDecision.DETACHED,
            ProjectRunnerRegistryDecision.UNINSTALLED,
        ],
    ) -> ProjectRunnerRegistryResult:
        """Apply the exact stop gate shared by detach and uninstall."""

        existing = _find_project_state(self._states, project_ref)
        if existing is None:
            return ProjectRunnerRegistryResult(
                decision=ProjectRunnerRegistryDecision.NOT_FOUND,
                project_ref=project_ref,
                subscription_id=None,
                runner_ref=None,
            )

        stop_result = _revalidate_stop_result(
            self._lifecycle.stop(project_ref, existing.runner_ref)
        )
        if isinstance(stop_result, RunnerStopCapabilityUnavailable):
            return ProjectRunnerRegistryResult(
                decision=ProjectRunnerRegistryDecision.RUNNER_STOP_UNAVAILABLE,
                project_ref=project_ref,
                subscription_id=None,
                runner_ref=existing.runner_ref,
            )

        self._states = _remove_project_state(self._states, project_ref)
        return ProjectRunnerRegistryResult(
            decision=success_decision,
            project_ref=project_ref,
            subscription_id=None,
            runner_ref=existing.runner_ref,
        )


RunnerStartUnavailable: TypeAlias = RunnerStartCapabilityUnavailable
RunnerStopUnavailable: TypeAlias = RunnerStopCapabilityUnavailable
ProjectRunnerDecision: TypeAlias = ProjectRunnerRegistryDecision


__all__ = [
    "ProjectRunnerDecision",
    "ProjectRunnerRegistry",
    "ProjectRunnerRegistryDecision",
    "ProjectRunnerRegistryResult",
    "RunnerLifecyclePort",
    "RunnerStartCapabilityUnavailable",
    "RunnerStartResult",
    "RunnerStartUnavailable",
    "RunnerStarted",
    "RunnerStopCapabilityUnavailable",
    "RunnerStopResult",
    "RunnerStopUnavailable",
    "RunnerStopped",
]
