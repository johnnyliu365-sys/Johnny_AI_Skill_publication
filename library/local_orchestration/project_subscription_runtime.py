"""Receipt-bound composition of one Git subscription and one project runner."""

from __future__ import annotations

from enum import Enum
from typing import Self

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from library.local_orchestration.git_handoff_event_adapter import (
    ReceiptBoundGitEventAdapter,
)
from library.local_orchestration.project_runner_registry import (
    ProjectRunnerRegistry,
    ProjectRunnerRegistryDecision,
    ProjectRunnerRegistryResult,
)
from library.workflow_router.git_handoff_contracts import (
    GitEventAdapterDecision,
    GitEventAdapterDecisionKind,
    GitEventRegistrationLifecycle,
    GitEventRegistrationState,
    GitRefRegistrationRequest,
    GitRefSignal,
)
from library.workflow_router.live_dispatch_contracts import ReceiptLifecycle, TicketReceipt
from library.workflow_router.role_supervision_contracts import HandoffAdmissionContext
from library.workflow_router.contracts import OpaqueMetadataId


class _StrictModel(BaseModel):
    """Immutable, closed models for the receipt-bound composition boundary."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
    )


class ProjectSubscriptionRegistrationRequest(_StrictModel):
    """The three immutable authorities required to arm one subscription."""

    receipt: TicketReceipt
    git_request: GitRefRegistrationRequest
    handoff_context: HandoffAdmissionContext


class ProjectSubscriptionState(_StrictModel):
    """The exact state retained while one receipt-bound subscription is live."""

    receipt: TicketReceipt
    registration: GitEventRegistrationState
    handoff_context: HandoffAdmissionContext
    runner_ref: OpaqueMetadataId

    @model_validator(mode="after")
    def state_bindings_match(self) -> Self:
        if self.receipt.lifecycle is not ReceiptLifecycle.ACTIVE:
            raise ValueError("subscription state requires an active receipt")
        if (
            self.receipt.project_id != self.registration.project_id
            or self.receipt.project_id != self.handoff_context.project_id
            or self.receipt.ticket_reference != self.registration.ticket_ref
            or self.receipt.ticket_reference != self.handoff_context.ticket_ref
            or self.receipt.receipt_id != self.registration.router_receipt_ref
            or self.receipt.receipt_id != self.handoff_context.router_receipt_ref
            or self.receipt.worktree_fingerprint != self.registration.worktree_ref
            or self.receipt.worktree_fingerprint != self.handoff_context.worktree_ref
            or self.receipt.branch_fingerprint != self.registration.branch_ref
            or self.receipt.branch_fingerprint != self.handoff_context.branch_ref
            or self.receipt.baseline_commit != self.registration.baseline_commit
            or self.receipt.baseline_commit != self.handoff_context.baseline_commit
            or self.receipt.correlation_id != self.registration.correlation_id
            or self.receipt.correlation_id != self.handoff_context.correlation_id
            or self.receipt.ticket_revision != self.handoff_context.ticket_revision
            or self.handoff_context.target_task_ref != self.registration.implementation_task_ref
            or self.receipt.implementation_owner_id != self.handoff_context.target_role_ref
        ):
            raise ValueError("subscription state bindings must remain equal")
        return self


class ProjectSubscriptionDecision(str, Enum):
    """Finite public decisions for the subscription runtime."""

    REGISTERED = "REGISTERED"
    SILENT = "SILENT"
    COMPLETION_CANDIDATE = "COMPLETION_CANDIDATE"
    REJECTED = "REJECTED"
    CLOSE_BLOCKED = "CLOSE_BLOCKED"
    CLOSED = "CLOSED"


class ProjectSubscriptionFailure(str, Enum):
    """Finite public failure reasons without dependency diagnostics."""

    INVALID_BINDING = "INVALID_BINDING"
    INACTIVE_RECEIPT = "INACTIVE_RECEIPT"
    GIT_REGISTRATION_REJECTED = "GIT_REGISTRATION_REJECTED"
    RUNNER_REGISTRATION_REJECTED = "RUNNER_REGISTRATION_REJECTED"
    RUNNER_CLOSE_REJECTED = "RUNNER_CLOSE_REJECTED"


class ProjectSubscriptionResult(_StrictModel):
    """Closed result state for registration, observation, or closure."""

    decision: ProjectSubscriptionDecision
    state: ProjectSubscriptionState | None = None
    runner_result: ProjectRunnerRegistryResult | None = None
    git_decision: GitEventAdapterDecision | None = None
    failure: ProjectSubscriptionFailure | None = None

    @model_validator(mode="after")
    def result_shape_is_finite(self) -> Self:
        active = {
            ProjectSubscriptionDecision.REGISTERED,
            ProjectSubscriptionDecision.SILENT,
            ProjectSubscriptionDecision.COMPLETION_CANDIDATE,
        }
        if self.decision in active:
            if (
                self.state is None
                or self.state.registration.lifecycle is not GitEventRegistrationLifecycle.ACTIVE
                or self.failure is not None
            ):
                raise ValueError("active decisions require state and no failure")
        elif self.decision is ProjectSubscriptionDecision.CLOSE_BLOCKED:
            if self.state is None or self.failure is not ProjectSubscriptionFailure.RUNNER_CLOSE_REJECTED:
                raise ValueError("blocked closure requires unchanged state and close failure")
        elif self.decision is ProjectSubscriptionDecision.REJECTED:
            if self.state is not None or self.failure is None:
                raise ValueError("rejected decisions require one failure and no state")
        elif self.decision is ProjectSubscriptionDecision.CLOSED:
            if self.state is not None or self.failure is not None:
                raise ValueError("closed decisions cannot retain state or failure")
        return self


def _rejected(
    failure: ProjectSubscriptionFailure,
    *,
    runner_result: ProjectRunnerRegistryResult | None = None,
    git_decision: GitEventAdapterDecision | None = None,
) -> ProjectSubscriptionResult:
    return ProjectSubscriptionResult(
        decision=ProjectSubscriptionDecision.REJECTED,
        runner_result=runner_result,
        git_decision=git_decision,
        failure=failure,
    )


class ProjectSubscriptionRuntime:
    """Compose one exact receipt, Git registration, and runner subscription."""

    def __init__(
        self,
        runner_registry: ProjectRunnerRegistry,
        git_adapter: ReceiptBoundGitEventAdapter,
    ) -> None:
        self._runner_registry = runner_registry
        self._git_adapter = git_adapter

    def register(
        self,
        request: ProjectSubscriptionRegistrationRequest,
    ) -> ProjectSubscriptionResult:
        """Validate bindings, arm Git first, then register the project runner."""

        validated = self._validated_request(request)
        if validated is None:
            return _rejected(ProjectSubscriptionFailure.INVALID_BINDING)
        if validated.receipt.lifecycle is not ReceiptLifecycle.ACTIVE:
            return _rejected(ProjectSubscriptionFailure.INACTIVE_RECEIPT)
        if not self._request_bindings_match(validated):
            return _rejected(ProjectSubscriptionFailure.INVALID_BINDING)

        git_decision = self._validated_git_decision(
            self._git_adapter.register(validated.git_request, validated.handoff_context)
        )
        if git_decision is None:
            return _rejected(ProjectSubscriptionFailure.GIT_REGISTRATION_REJECTED)
        registration = git_decision.registration
        if (
            git_decision.decision is GitEventAdapterDecisionKind.REGISTRATION_FAILED
            or registration is None
            or registration.lifecycle is not GitEventRegistrationLifecycle.ACTIVE
        ):
            if registration is not None:
                self._git_adapter.close(registration)
            return _rejected(
                ProjectSubscriptionFailure.GIT_REGISTRATION_REJECTED,
                git_decision=git_decision,
            )

        runner_result = ProjectRunnerRegistryResult.model_validate(
            self._runner_registry.register_subscription(
                validated.receipt.project_id,
                validated.git_request.subscription_id,
            ),
            strict=True,
        )
        if runner_result.decision not in (
            ProjectRunnerRegistryDecision.SUBSCRIBED,
            ProjectRunnerRegistryDecision.REUSED,
        ) or runner_result.runner_ref is None:
            self._git_adapter.close(registration)
            return _rejected(
                ProjectSubscriptionFailure.RUNNER_REGISTRATION_REJECTED,
                runner_result=runner_result,
                git_decision=git_decision,
            )

        state = ProjectSubscriptionState(
            receipt=validated.receipt,
            registration=registration,
            handoff_context=validated.handoff_context,
            runner_ref=runner_result.runner_ref,
        )
        return ProjectSubscriptionResult(
            decision=ProjectSubscriptionDecision.REGISTERED,
            state=state,
            runner_result=runner_result,
            git_decision=git_decision,
        )

    def observe(
        self,
        state: ProjectSubscriptionState,
        signal: GitRefSignal,
    ) -> ProjectSubscriptionResult:
        """Map one adapter observation without waking or mutating a peer."""

        validated_state = self._validated_state(state)
        validated_signal = self._validated_signal(signal)
        if validated_state is None or validated_signal is None:
            return _rejected(ProjectSubscriptionFailure.INVALID_BINDING)
        decision = self._validated_git_decision(
            self._git_adapter.observe_signal(
                validated_state.registration,
                validated_signal,
                validated_state.handoff_context,
            )
        )
        if decision is None:
            return self._release_after_observation(validated_state, None)
        if decision.registration is not None:
            next_state = self._state_with_registration(validated_state, decision.registration)
        else:
            next_state = validated_state
        if next_state is None:
            return self._release_after_observation(validated_state, decision)

        if decision.decision is GitEventAdapterDecisionKind.REGISTERED:
            return self._active_result(
                ProjectSubscriptionDecision.REGISTERED,
                next_state,
                decision,
            )
        if decision.decision in (
            GitEventAdapterDecisionKind.SOURCE_ADVANCED,
            GitEventAdapterDecisionKind.SILENT,
        ):
            return self._active_result(ProjectSubscriptionDecision.SILENT, next_state, decision)
        if decision.decision is GitEventAdapterDecisionKind.TERMINAL_HANDOFF_ACCEPTED:
            return self._active_result(
                ProjectSubscriptionDecision.COMPLETION_CANDIDATE,
                next_state,
                decision,
            )
        return self._release_after_observation(next_state, decision)

    def close(self, state: ProjectSubscriptionState) -> ProjectSubscriptionResult:
        """Remove the exact runner subscription before closing its Git registration."""

        validated_state = self._validated_state(state)
        if validated_state is None:
            return _rejected(ProjectSubscriptionFailure.INVALID_BINDING)

        runner_result = ProjectRunnerRegistryResult.model_validate(
            self._runner_registry.remove_subscription(
                validated_state.receipt.project_id,
                validated_state.registration.subscription_id,
            ),
            strict=True,
        )
        if runner_result.decision is not ProjectRunnerRegistryDecision.REMOVED:
            return ProjectSubscriptionResult(
                decision=ProjectSubscriptionDecision.CLOSE_BLOCKED,
                state=validated_state,
                runner_result=runner_result,
                failure=ProjectSubscriptionFailure.RUNNER_CLOSE_REJECTED,
            )

        self._git_adapter.close(validated_state.registration)
        return ProjectSubscriptionResult(
            decision=ProjectSubscriptionDecision.CLOSED,
            runner_result=runner_result,
        )

    @staticmethod
    def _validated_request(
        request: ProjectSubscriptionRegistrationRequest,
    ) -> ProjectSubscriptionRegistrationRequest | None:
        if type(request) is not ProjectSubscriptionRegistrationRequest:
            return None
        try:
            return ProjectSubscriptionRegistrationRequest.model_validate(request, strict=True)
        except ValidationError:
            return None

    @staticmethod
    def _validated_state(state: ProjectSubscriptionState) -> ProjectSubscriptionState | None:
        if type(state) is not ProjectSubscriptionState:
            return None
        try:
            return ProjectSubscriptionState.model_validate(state, strict=True)
        except ValidationError:
            return None

    @staticmethod
    def _validated_signal(signal: GitRefSignal) -> GitRefSignal | None:
        if type(signal) is not GitRefSignal:
            return None
        try:
            return GitRefSignal.model_validate(signal, strict=True)
        except ValidationError:
            return None

    @staticmethod
    def _validated_git_decision(
        decision: GitEventAdapterDecision,
    ) -> GitEventAdapterDecision | None:
        if type(decision) is not GitEventAdapterDecision:
            return None
        try:
            return GitEventAdapterDecision.model_validate(decision, strict=True)
        except ValidationError:
            return None

    @staticmethod
    def _request_bindings_match(
        request: ProjectSubscriptionRegistrationRequest,
    ) -> bool:
        receipt = request.receipt
        git_request = request.git_request
        context = request.handoff_context
        return (
            receipt.project_id == git_request.project_id == context.project_id
            and receipt.ticket_reference == git_request.ticket_ref == context.ticket_ref
            and receipt.receipt_id == git_request.router_receipt_ref == context.router_receipt_ref
            and receipt.worktree_fingerprint == git_request.worktree_ref == context.worktree_ref
            and receipt.branch_fingerprint == git_request.branch_ref == context.branch_ref
            and receipt.baseline_commit == git_request.baseline_commit == context.baseline_commit
            and receipt.correlation_id == git_request.correlation_id == context.correlation_id
            and receipt.ticket_revision == context.ticket_revision
            and git_request.implementation_task_ref == context.target_task_ref
            and receipt.implementation_owner_id == context.target_role_ref
            and context.target_task_ref is not None
        )

    @staticmethod
    def _state_with_registration(
        state: ProjectSubscriptionState,
        registration: GitEventRegistrationState,
    ) -> ProjectSubscriptionState | None:
        try:
            return ProjectSubscriptionState(
                receipt=state.receipt,
                registration=registration,
                handoff_context=state.handoff_context,
                runner_ref=state.runner_ref,
            )
        except ValidationError:
            return None

    @staticmethod
    def _active_result(
        decision: ProjectSubscriptionDecision,
        state: ProjectSubscriptionState,
        git_decision: GitEventAdapterDecision,
    ) -> ProjectSubscriptionResult:
        return ProjectSubscriptionResult(
            decision=decision,
            state=state,
            git_decision=git_decision,
        )

    def _release_after_observation(
        self,
        state: ProjectSubscriptionState,
        git_decision: GitEventAdapterDecision | None,
    ) -> ProjectSubscriptionResult:
        runner_result = ProjectRunnerRegistryResult.model_validate(
            self._runner_registry.remove_subscription(
                state.receipt.project_id,
                state.registration.subscription_id,
            ),
            strict=True,
        )
        if runner_result.decision is ProjectRunnerRegistryDecision.REMOVED:
            return _rejected(
                ProjectSubscriptionFailure.GIT_REGISTRATION_REJECTED,
                runner_result=runner_result,
                git_decision=git_decision,
            )
        return ProjectSubscriptionResult(
            decision=ProjectSubscriptionDecision.CLOSE_BLOCKED,
            state=state,
            runner_result=runner_result,
            git_decision=git_decision,
            failure=ProjectSubscriptionFailure.RUNNER_CLOSE_REJECTED,
        )


__all__ = [
    "ProjectSubscriptionDecision",
    "ProjectSubscriptionFailure",
    "ProjectSubscriptionRegistrationRequest",
    "ProjectSubscriptionResult",
    "ProjectSubscriptionRuntime",
    "ProjectSubscriptionState",
]
