"""Strong contracts for exact Git-ref handoff observation."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import (
    BranchFingerprint,
    OpaqueMetadataId,
    ProjectId,
    ReviewedCommitReference,
    WorktreeFingerprint,
)
from .role_supervision_contracts import (
    ArtifactReference,
    CorrelationId,
    HandoffId,
    HandoffLeaf,
    ReceiptReference,
    TaskReference,
    TicketReference,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
        revalidate_instances="always",
    )


GitRefName: TypeAlias = Annotated[
    str,
    Field(pattern=r"^refs/heads/[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$"),
]
EventSourceRef: TypeAlias = OpaqueMetadataId
SubscriptionId: TypeAlias = OpaqueMetadataId


class GitObservationMode(str, Enum):
    NATIVE_REF_EVENT = "NATIVE_REF_EVENT"
    UNAVAILABLE = "UNAVAILABLE"


class GitRefSnapshotStatus(str, Enum):
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    UNAVAILABLE = "UNAVAILABLE"


class GitPathChangeStatus(str, Enum):
    CHANGED = "CHANGED"
    UNCHANGED = "UNCHANGED"
    UNAVAILABLE = "UNAVAILABLE"


class GitBlobReadStatus(str, Enum):
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    UNAVAILABLE = "UNAVAILABLE"


class GitAncestryStatus(str, Enum):
    IS_ANCESTOR = "IS_ANCESTOR"
    NOT_ANCESTOR = "NOT_ANCESTOR"
    UNAVAILABLE = "UNAVAILABLE"


class GitNativeRegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    UNAVAILABLE = "UNAVAILABLE"
    REJECTED = "REJECTED"


class GitNativeFailureKind(str, Enum):
    NOTIFICATION_UNAVAILABLE = "NOTIFICATION_UNAVAILABLE"


class GitEventRegistrationLifecycle(str, Enum):
    ACTIVE = "ACTIVE"
    HALTED = "HALTED"
    CLOSED = "CLOSED"


class GitEventAdapterDecisionKind(str, Enum):
    REGISTERED = "REGISTERED"
    SOURCE_ADVANCED = "SOURCE_ADVANCED"
    TERMINAL_HANDOFF_ACCEPTED = "TERMINAL_HANDOFF_ACCEPTED"
    INVALID_HANDOFF_FAULT = "INVALID_HANDOFF_FAULT"
    STALE_BINDING_FAULT = "STALE_BINDING_FAULT"
    READBACK_FAILED = "READBACK_FAILED"
    REGISTRATION_FAILED = "REGISTRATION_FAILED"
    SILENT = "SILENT"


class GitEventAdapterFailure(str, Enum):
    INVALID_REQUEST = "INVALID_REQUEST"
    REF_UNAVAILABLE = "REF_UNAVAILABLE"
    NATIVE_REGISTRATION_UNAVAILABLE = "NATIVE_REGISTRATION_UNAVAILABLE"
    READBACK_UNAVAILABLE = "READBACK_UNAVAILABLE"


class SupervisionFaultKind(str, Enum):
    INVALID_HANDOFF = "INVALID_HANDOFF"
    STALE_BINDING = "STALE_BINDING"
    WAKE_CHAIN_LOST = "WAKE_CHAIN_LOST"


class GitRefSnapshotResult(_StrictModel):
    status: GitRefSnapshotStatus
    exact_git_ref: GitRefName | None = None
    commit_id: ReviewedCommitReference | None = None

    @model_validator(mode="after")
    def exact_snapshot_shape(self) -> Self:
        found = self.status is GitRefSnapshotStatus.FOUND
        if found != (self.exact_git_ref is not None and self.commit_id is not None):
            raise ValueError("found ref snapshots require exact ref and commit")
        return self


class GitPathChangeResult(_StrictModel):
    status: GitPathChangeStatus
    changed: bool | None

    @model_validator(mode="after")
    def exact_path_change_shape(self) -> Self:
        if self.status is GitPathChangeStatus.UNAVAILABLE:
            if self.changed is not None:
                raise ValueError("unavailable path result cannot assert change")
        elif self.changed != (self.status is GitPathChangeStatus.CHANGED):
            raise ValueError("path result status must match changed value")
        return self


class GitBlobReadResult(_StrictModel):
    status: GitBlobReadStatus
    payload: str | None = None

    @model_validator(mode="after")
    def exact_blob_shape(self) -> Self:
        if self.status is GitBlobReadStatus.FOUND:
            if self.payload is None:
                raise ValueError("found blob requires payload")
        elif self.payload is not None:
            raise ValueError("failed blob read cannot expose payload")
        return self


class GitAncestryResult(_StrictModel):
    status: GitAncestryStatus
    is_ancestor: bool | None

    @model_validator(mode="after")
    def exact_ancestry_shape(self) -> Self:
        if self.status is GitAncestryStatus.UNAVAILABLE:
            if self.is_ancestor is not None:
                raise ValueError("unavailable ancestry cannot assert a relation")
        elif self.is_ancestor != (self.status is GitAncestryStatus.IS_ANCESTOR):
            raise ValueError("ancestry status must match its boolean")
        return self


class GitRefRegistrationRequest(_StrictModel):
    """Receipt-bound exact ref and reserved leaf registration intent."""

    event_source_ref: EventSourceRef
    subscription_id: SubscriptionId
    project_id: ProjectId
    ticket_ref: TicketReference
    router_receipt_ref: ReceiptReference
    implementation_task_ref: TaskReference
    worktree_ref: WorktreeFingerprint
    branch_ref: BranchFingerprint
    baseline_commit: ReviewedCommitReference
    correlation_id: CorrelationId
    exact_git_ref: GitRefName
    reserved_handoff_ref: ArtifactReference

    @model_validator(mode="after")
    def reserved_ref_is_json_leaf(self) -> Self:
        if not self.reserved_handoff_ref.endswith(".json"):
            raise ValueError("reserved handoff reference must identify one JSON leaf")
        if self.reserved_handoff_ref.endswith("/index.json"):
            raise ValueError("reserved handoff reference cannot identify an index")
        return self


class GitNativeRegistrationRequest(_StrictModel):
    event_source_ref: EventSourceRef
    subscription_id: SubscriptionId
    exact_git_ref: GitRefName
    mode: GitObservationMode = GitObservationMode.NATIVE_REF_EVENT


class GitNativeRegistrationResult(_StrictModel):
    status: GitNativeRegistrationStatus
    event_source_ref: EventSourceRef | None = None
    subscription_id: SubscriptionId | None = None

    @model_validator(mode="after")
    def exact_registration_shape(self) -> Self:
        success = self.status is GitNativeRegistrationStatus.REGISTERED
        has_identity = self.event_source_ref is not None and self.subscription_id is not None
        if success != has_identity:
            raise ValueError("native registration identity must exist only on success")
        return self


class GitRefSignal(_StrictModel):
    """Native hint with no authority or untrusted payload."""

    event_source_ref: EventSourceRef
    subscription_id: SubscriptionId


class GitNativeFailureSignal(_StrictModel):
    """Sanitized terminal signal when the armed native source is lost."""

    event_source_ref: EventSourceRef
    subscription_id: SubscriptionId
    failure: GitNativeFailureKind


class GitEventRegistrationState(_StrictModel):
    """Metadata-only, persistable exact-ref registration state."""

    event_source_ref: EventSourceRef
    subscription_id: SubscriptionId
    project_id: ProjectId
    ticket_ref: TicketReference
    router_receipt_ref: ReceiptReference
    implementation_task_ref: TaskReference
    worktree_ref: WorktreeFingerprint
    branch_ref: BranchFingerprint
    baseline_commit: ReviewedCommitReference
    correlation_id: CorrelationId
    exact_git_ref: GitRefName
    reserved_handoff_ref: ArtifactReference
    mode: GitObservationMode
    lifecycle: GitEventRegistrationLifecycle
    last_observed_commit: ReviewedCommitReference
    consumed_handoff_ids: tuple[HandoffId, ...]
    fault_emitted: bool

    @model_validator(mode="after")
    def state_invariants_hold(self) -> Self:
        if len(self.consumed_handoff_ids) != len(set(self.consumed_handoff_ids)):
            raise ValueError("consumed handoff identifiers must be unique")
        if self.lifecycle is GitEventRegistrationLifecycle.ACTIVE and self.fault_emitted:
            raise ValueError("active registration cannot have emitted a terminal fault")
        if self.lifecycle is GitEventRegistrationLifecycle.HALTED and not self.fault_emitted:
            raise ValueError("halted registration must identify its emitted fault")
        return self


class SupervisionFault(_StrictModel):
    """Sanitized trusted fault without raw Git or handoff content."""

    kind: SupervisionFaultKind
    event_source_ref: EventSourceRef
    subscription_id: SubscriptionId
    ticket_ref: TicketReference
    router_receipt_ref: ReceiptReference
    observed_commit: ReviewedCommitReference


class GitEventAdapterDecision(_StrictModel):
    """One adapter decision with strict optional-result shape."""

    decision: GitEventAdapterDecisionKind
    registration: GitEventRegistrationState | None = None
    handoff: HandoffLeaf | None = None
    fault: SupervisionFault | None = None
    failure: GitEventAdapterFailure | None = None

    @model_validator(mode="after")
    def exact_decision_shape(self) -> Self:
        if self.decision is GitEventAdapterDecisionKind.REGISTRATION_FAILED:
            if self.registration is not None or self.failure is None:
                raise ValueError("failed registration requires only a failure")
            return self
        if self.registration is None or self.failure is not None:
            raise ValueError("non-registration failures require state and no failure")
        if self.decision is GitEventAdapterDecisionKind.TERMINAL_HANDOFF_ACCEPTED:
            if self.handoff is None or self.fault is not None:
                raise ValueError("accepted handoff decision requires one handoff")
        elif self.decision in (
            GitEventAdapterDecisionKind.INVALID_HANDOFF_FAULT,
            GitEventAdapterDecisionKind.STALE_BINDING_FAULT,
        ):
            if self.fault is None or self.handoff is not None:
                raise ValueError("fault decisions require one sanitized fault")
        elif self.handoff is not None or self.fault is not None:
            raise ValueError("silent/source/readback decisions cannot carry a handoff or fault")
        return self


__all__ = [
    "EventSourceRef",
    "GitAncestryResult",
    "GitAncestryStatus",
    "GitBlobReadResult",
    "GitBlobReadStatus",
    "GitEventAdapterDecision",
    "GitEventAdapterDecisionKind",
    "GitEventAdapterFailure",
    "GitEventRegistrationLifecycle",
    "GitEventRegistrationState",
    "GitNativeRegistrationRequest",
    "GitNativeRegistrationResult",
    "GitNativeRegistrationStatus",
    "GitNativeFailureKind",
    "GitNativeFailureSignal",
    "GitObservationMode",
    "GitPathChangeResult",
    "GitPathChangeStatus",
    "GitRefName",
    "GitRefRegistrationRequest",
    "GitRefSignal",
    "GitRefSnapshotResult",
    "GitRefSnapshotStatus",
    "SubscriptionId",
    "SupervisionFault",
    "SupervisionFaultKind",
]
