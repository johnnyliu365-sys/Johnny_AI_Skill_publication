"""Strong boundary contracts for the receipt-bound supervision composition."""

from __future__ import annotations

from enum import Enum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import BranchFingerprint, OpaqueMetadataId, ProjectId, WorktreeFingerprint
from .git_handoff_contracts import (
    GitEventAdapterDecision,
    GitEventRegistrationLifecycle,
    GitEventRegistrationState,
    GitRefRegistrationRequest,
    SubscriptionId,
)
from .live_dispatch_contracts import TicketReceipt
from .role_supervision_contracts import HandoffAdmissionContext
from .role_wake_contracts import (
    MonotonicDeadlineCapabilityProof,
    RoleWakeCapabilityProof,
    RoleWakeChainProof,
    RoleWakeResult,
)
from .supervision_policy import (
    ExecutionStartedEvidence,
    LeaseLifecycle,
    ModelOverrideState,
    SupervisionClass,
    SupervisionDecision,
    SupervisionLease,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
        revalidate_instances="always",
    )


class SupervisionRuntimeLifecycle(str, Enum):
    PREPARED = "PREPARED"
    ACTIVE = "ACTIVE"
    REVIEW_PENDING = "REVIEW_PENDING"
    CLOSED = "CLOSED"
    HALTED = "HALTED"


class SupervisionPreparationStatus(str, Enum):
    PREPARED = "PREPARED"
    REJECTED = "REJECTED"
    CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"


class SupervisionStartStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"


class SupervisionRuntimeFailure(str, Enum):
    REGISTRATION_REJECTED = "REGISTRATION_REJECTED"
    ROLE_WAKE_CHAIN_UNAVAILABLE = "ROLE_WAKE_CHAIN_UNAVAILABLE"
    EXECUTION_START_REJECTED = "EXECUTION_START_REJECTED"
    DEADLINE_UNAVAILABLE = "DEADLINE_UNAVAILABLE"
    NATIVE_NOTIFICATION_UNAVAILABLE = "NATIVE_NOTIFICATION_UNAVAILABLE"
    GIT_READBACK_UNAVAILABLE = "GIT_READBACK_UNAVAILABLE"
    ROLE_WAKE_UNAVAILABLE = "ROLE_WAKE_UNAVAILABLE"
    STALE_RUNTIME_EVENT = "STALE_RUNTIME_EVENT"
    MODEL_CAPABILITY_INSUFFICIENT = "MODEL_CAPABILITY_INSUFFICIENT"


class ReviewerDiagnosisRoute(str, Enum):
    CONTINUE_IMPLEMENTATION_REQUIRED = "CONTINUE_IMPLEMENTATION_REQUIRED"
    TICKET_REPAIR_REQUIRED = "TICKET_REPAIR_REQUIRED"
    MODEL_CAPABILITY_INSUFFICIENT = "MODEL_CAPABILITY_INSUFFICIENT"
    NO_ACTION = "NO_ACTION"
    REJECTED = "REJECTED"


class ContinuationStatus(str, Enum):
    RESUMED = "RESUMED"
    REJECTED = "REJECTED"
    CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"


class SupervisionPreparationRequest(_StrictModel):
    receipt: TicketReceipt
    registration_request: GitRefRegistrationRequest
    handoff_context: HandoffAdmissionContext
    reviewer_ref: OpaqueMetadataId
    implementation_task_ref: OpaqueMetadataId
    wake_capability: RoleWakeCapabilityProof
    deadline_capability: MonotonicDeadlineCapabilityProof


class SupervisionStartRequest(_StrictModel):
    subscription_id: SubscriptionId
    lease_id: OpaqueMetadataId
    supervision_class: SupervisionClass
    execution_started: ExecutionStartedEvidence


class ReviewerDiagnosisRequest(_StrictModel):
    subscription_id: SubscriptionId
    project_id: ProjectId
    ticket_ref: OpaqueMetadataId
    router_receipt_ref: OpaqueMetadataId
    task_ref: OpaqueMetadataId
    worktree_ref: WorktreeFingerprint
    branch_ref: BranchFingerprint
    observed_at_ms: int = Field(ge=0)
    task_stopped_incomplete: bool
    approved_closure_unchanged: bool
    host_readback_refs: tuple[OpaqueMetadataId, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def readback_is_unique(self) -> Self:
        if len(self.host_readback_refs) != len(set(self.host_readback_refs)):
            raise ValueError("diagnosis readback references must be unique")
        return self


class ContinuationAcceptedEvidence(_StrictModel):
    subscription_id: SubscriptionId
    project_id: ProjectId
    ticket_ref: OpaqueMetadataId
    router_receipt_ref: OpaqueMetadataId
    task_ref: OpaqueMetadataId
    worktree_ref: WorktreeFingerprint
    branch_ref: BranchFingerprint
    accepted_at_ms: int = Field(ge=0)
    host_readback_refs: tuple[OpaqueMetadataId, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def readback_is_unique(self) -> Self:
        if len(self.host_readback_refs) != len(set(self.host_readback_refs)):
            raise ValueError("continuation readback references must be unique")
        return self


class SupervisionRuntimeState(_StrictModel):
    registration: GitEventRegistrationState
    handoff_context: HandoffAdmissionContext
    chain: RoleWakeChainProof
    lease: SupervisionLease | None
    model_override: ModelOverrideState | None = None
    lifecycle: SupervisionRuntimeLifecycle
    last_git_decision: GitEventAdapterDecision
    last_supervision_decision: SupervisionDecision | None = None
    last_wake_result: RoleWakeResult | None = None
    failure: SupervisionRuntimeFailure | None = None

    @model_validator(mode="after")
    def lifecycle_shape_is_exact(self) -> Self:
        chain_registration = self.chain.registration
        if not all(
            (
                self.registration.event_source_ref == chain_registration.event_source_ref,
                self.registration.subscription_id == chain_registration.subscription_id,
                self.registration.project_id == chain_registration.project_id,
                self.registration.ticket_ref == chain_registration.ticket_ref,
                self.registration.router_receipt_ref
                == chain_registration.router_receipt_ref,
                self.registration.implementation_task_ref
                == chain_registration.implementation_task_ref,
                self.registration.worktree_ref == chain_registration.worktree_ref,
                self.registration.branch_ref == chain_registration.branch_ref,
                self.registration.baseline_commit == chain_registration.baseline_commit,
                self.registration.correlation_id == chain_registration.correlation_id,
            )
        ):
            raise ValueError("runtime state and wake chain must bind one execution")
        if self.lease is not None and not all(
            (
                self.lease.project_id == self.registration.project_id,
                self.lease.ticket_ref == self.registration.ticket_ref,
                self.lease.router_receipt_ref == self.registration.router_receipt_ref,
                self.lease.task_ref == self.registration.implementation_task_ref,
                self.lease.worktree_ref == self.registration.worktree_ref,
                self.lease.branch_ref == self.registration.branch_ref,
                self.lease.baseline_commit == self.registration.baseline_commit,
            )
        ):
            raise ValueError("runtime lease must bind the exact registration")
        if self.lifecycle is SupervisionRuntimeLifecycle.PREPARED:
            if self.lease is not None or self.failure is not None:
                raise ValueError("prepared supervision has no lease or failure")
        elif self.lifecycle is SupervisionRuntimeLifecycle.ACTIVE:
            if (
                self.lease is None
                or self.lease.lifecycle is not LeaseLifecycle.ACTIVE
                or self.failure is not None
            ):
                raise ValueError("active supervision requires one active lease")
        elif self.lifecycle is SupervisionRuntimeLifecycle.REVIEW_PENDING:
            if self.lease is None or self.last_wake_result is None or self.failure is not None:
                raise ValueError("review-pending supervision requires lease and wake result")
        elif self.lifecycle is SupervisionRuntimeLifecycle.CLOSED:
            if (
                self.lease is None
                or self.lease.lifecycle is not LeaseLifecycle.CLOSED
                or self.registration.lifecycle is not GitEventRegistrationLifecycle.CLOSED
                or self.failure is not None
            ):
                raise ValueError("closed supervision requires closed lease and registration")
        elif self.failure is None:
            raise ValueError("halted supervision requires a finite failure")
        return self


class SupervisionPreparationResult(_StrictModel):
    status: SupervisionPreparationStatus
    state: SupervisionRuntimeState | None = None
    failure: SupervisionRuntimeFailure | None = None

    @model_validator(mode="after")
    def exact_result_shape(self) -> Self:
        success = self.status is SupervisionPreparationStatus.PREPARED
        if success != (self.state is not None and self.failure is None):
            raise ValueError("preparation success requires only state")
        if not success and (self.state is not None or self.failure is None):
            raise ValueError("preparation failure requires only failure")
        return self


class SupervisionStartResult(_StrictModel):
    status: SupervisionStartStatus
    state: SupervisionRuntimeState | None = None
    failure: SupervisionRuntimeFailure | None = None

    @model_validator(mode="after")
    def exact_result_shape(self) -> Self:
        success = self.status is SupervisionStartStatus.ACTIVE
        if success != (self.state is not None and self.failure is None):
            raise ValueError("start success requires only state")
        if not success and (self.state is not None or self.failure is None):
            raise ValueError("start failure requires only failure")
        return self


class ReviewerDiagnosisResult(_StrictModel):
    route: ReviewerDiagnosisRoute
    state: SupervisionRuntimeState | None = None

    @model_validator(mode="after")
    def accepted_routes_retain_state(self) -> Self:
        if self.route is ReviewerDiagnosisRoute.REJECTED:
            if self.state is not None:
                raise ValueError("rejected diagnosis cannot return runtime state")
        elif self.state is None:
            raise ValueError("accepted diagnosis requires runtime state")
        return self


class ContinuationResult(_StrictModel):
    status: ContinuationStatus
    state: SupervisionRuntimeState | None = None
    failure: SupervisionRuntimeFailure | None = None

    @model_validator(mode="after")
    def exact_result_shape(self) -> Self:
        success = self.status is ContinuationStatus.RESUMED
        if success != (self.state is not None and self.failure is None):
            raise ValueError("continuation success requires only runtime state")
        if not success and (self.state is not None or self.failure is None):
            raise ValueError("continuation failure requires only a failure")
        return self


__all__ = [
    "ContinuationAcceptedEvidence",
    "ContinuationResult",
    "ContinuationStatus",
    "ReviewerDiagnosisRequest",
    "ReviewerDiagnosisResult",
    "ReviewerDiagnosisRoute",
    "SupervisionPreparationRequest",
    "SupervisionPreparationResult",
    "SupervisionPreparationStatus",
    "SupervisionRuntimeFailure",
    "SupervisionRuntimeLifecycle",
    "SupervisionRuntimeState",
    "SupervisionStartRequest",
    "SupervisionStartResult",
    "SupervisionStartStatus",
]
