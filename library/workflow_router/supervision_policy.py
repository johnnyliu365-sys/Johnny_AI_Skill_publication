"""Pure receipt-bound supervision lease and model-policy reducers."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .contracts import (
    BranchFingerprint,
    OpaqueMetadataId,
    ProjectId,
    ReviewedCommitReference,
    WorktreeFingerprint,
)


_LUNA_TOTAL_MS = 30 * 60 * 1_000
_TERRA_INACTIVITY_MS = 2 * 60 * 60 * 1_000


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
        revalidate_instances="always",
    )


MonotonicMilliseconds: TypeAlias = Annotated[int, Field(ge=0)]
PositiveDurationMilliseconds: TypeAlias = Annotated[int, Field(gt=0)]
Counter: TypeAlias = Annotated[int, Field(ge=0)]
LeaseId: TypeAlias = OpaqueMetadataId
TicketReference: TypeAlias = OpaqueMetadataId
ReceiptReference: TypeAlias = OpaqueMetadataId
TaskReference: TypeAlias = OpaqueMetadataId
EvidenceReference: TypeAlias = OpaqueMetadataId


class SupervisionClass(str, Enum):
    """Finite timing policies derived from the active implementation model."""

    LUNA_XHIGH_DEFAULT = "LUNA_XHIGH_DEFAULT"
    TERRA_OR_HIGHER = "TERRA_OR_HIGHER"


class LeaseKind(str, Enum):
    """Whether elapsed time is total execution or ref inactivity."""

    TOTAL_EXECUTION = "TOTAL_EXECUTION"
    INACTIVITY = "INACTIVITY"


class LeaseLifecycle(str, Enum):
    """Finite lease lifecycle with one diagnostic interlock."""

    ACTIVE = "ACTIVE"
    DIAGNOSIS_PENDING = "DIAGNOSIS_PENDING"
    CLOSED = "CLOSED"


class LeaseEventKind(str, Enum):
    """Trusted facts consumed by the pure lease reducer."""

    EXACT_REF_ADVANCED = "EXACT_REF_ADVANCED"
    TASK_STOPPED_INCOMPLETE = "TASK_STOPPED_INCOMPLETE"
    DEADLINE_FIRED = "DEADLINE_FIRED"
    DIAGNOSIS_STOPPED_INCOMPLETE = "DIAGNOSIS_STOPPED_INCOMPLETE"
    TERMINAL_HANDOFF = "TERMINAL_HANDOFF"


class SupervisionDecisionKind(str, Enum):
    """Finite effect-free decisions emitted to the outer composition."""

    LEASE_STARTED = "LEASE_STARTED"
    EXECUTION_START_REJECTED = "EXECUTION_START_REJECTED"
    SILENT_ACTIVITY_RECORDED = "SILENT_ACTIVITY_RECORDED"
    WAKE_REVIEWER_DIAGNOSIS = "WAKE_REVIEWER_DIAGNOSIS"
    CONTINUE_IMPLEMENTATION = "CONTINUE_IMPLEMENTATION"
    TICKET_DEFECT_COMPLEXITY_EXCEEDED = "TICKET_DEFECT_COMPLEXITY_EXCEEDED"
    MODEL_CAPABILITY_INSUFFICIENT = "MODEL_CAPABILITY_INSUFFICIENT"
    LEASE_CLOSED = "LEASE_CLOSED"
    EVENT_REJECTED = "EVENT_REJECTED"


class ModelOverrideLifecycle(str, Enum):
    """One-ticket Terra override lifecycle."""

    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class TicketSplitDimension(str, Enum):
    """Approved vertical split dimensions and forbidden horizontal shortcuts."""

    OBSERVABLE_BEHAVIOR_STATE = "OBSERVABLE_BEHAVIOR_STATE"
    EXTERNAL_EFFECT = "EXTERNAL_EFFECT"
    OWNERSHIP_COMPOSITION_ROOT = "OWNERSHIP_COMPOSITION_ROOT"
    VERIFICATION_BOUNDARY = "VERIFICATION_BOUNDARY"
    FILE_BOUNDARY = "FILE_BOUNDARY"
    LINE_COUNT = "LINE_COUNT"
    HORIZONTAL_LAYER = "HORIZONTAL_LAYER"


class TicketRepairDecisionKind(str, Enum):
    """Finite Luna complexity repair outcomes."""

    SPLIT_FOR_LUNA = "SPLIT_FOR_LUNA"
    REPLACE_WITH_TERRA_HIGH = "REPLACE_WITH_TERRA_HIGH"
    REJECT_ILLEGAL_SPLIT = "REJECT_ILLEGAL_SPLIT"


class ExecutionStartedEvidence(_StrictModel):
    """Host-proved start event that alone may originate a lease."""

    project_id: ProjectId
    ticket_ref: TicketReference
    router_receipt_ref: ReceiptReference
    task_ref: TaskReference
    worktree_ref: WorktreeFingerprint
    branch_ref: BranchFingerprint
    baseline_commit: ReviewedCommitReference
    started_at_ms: MonotonicMilliseconds
    host_readback_refs: tuple[EvidenceReference, ...] = Field(min_length=1)
    exact_ticket_received: bool
    task_active: bool
    ticket_executable: bool
    sole_active_receipt: bool
    binding_fresh: bool

    @model_validator(mode="after")
    def evidence_refs_are_unique(self) -> Self:
        if len(self.host_readback_refs) != len(set(self.host_readback_refs)):
            raise ValueError("execution-start evidence references must be unique")
        return self

    @property
    def complete(self) -> bool:
        """Return whether every mandatory host readback gate is true."""

        return all(
            (
                self.exact_ticket_received,
                self.task_active,
                self.ticket_executable,
                self.sole_active_receipt,
                self.binding_fresh,
            )
        )


class SupervisionLease(_StrictModel):
    """Pure one-shot lease state; this model does not schedule a timer."""

    lease_id: LeaseId
    project_id: ProjectId
    ticket_ref: TicketReference
    router_receipt_ref: ReceiptReference
    task_ref: TaskReference
    worktree_ref: WorktreeFingerprint
    branch_ref: BranchFingerprint
    baseline_commit: ReviewedCommitReference
    supervision_class: SupervisionClass
    lease_kind: LeaseKind
    lifecycle: LeaseLifecycle
    origin_ms: MonotonicMilliseconds
    duration_ms: PositiveDurationMilliseconds
    deadline_ms: MonotonicMilliseconds
    reset_count: Counter
    continue_count: Counter

    @model_validator(mode="after")
    def lease_policy_is_exact(self) -> Self:
        if self.deadline_ms != self.origin_ms + self.duration_ms:
            raise ValueError("lease deadline must equal origin plus duration")
        if self.supervision_class is SupervisionClass.LUNA_XHIGH_DEFAULT:
            if self.lease_kind is not LeaseKind.TOTAL_EXECUTION:
                raise ValueError("Luna must use a total-execution lease")
            if self.duration_ms != _LUNA_TOTAL_MS:
                raise ValueError("Luna total-execution lease must be exactly thirty minutes")
            if self.reset_count != 0 or self.continue_count != 0:
                raise ValueError("Luna leases cannot reset or continue automatically")
            if self.lifecycle is LeaseLifecycle.DIAGNOSIS_PENDING:
                raise ValueError("Luna expiry is a ticket defect, not a continuation diagnosis")
        else:
            if self.lease_kind is not LeaseKind.INACTIVITY:
                raise ValueError("Terra-or-higher must use an inactivity lease")
            if self.duration_ms != _TERRA_INACTIVITY_MS:
                raise ValueError("Terra inactivity lease must be exactly two hours")
            if self.continue_count > 1:
                raise ValueError("Terra permits at most one automatic continuation")
        return self


class LeaseEvent(_StrictModel):
    """One monotonic fact delivered to the lease reducer."""

    kind: LeaseEventKind
    occurred_at_ms: MonotonicMilliseconds


class ModelOverrideState(_StrictModel):
    """A model override limited to one exact ticket."""

    ticket_ref: TicketReference
    lifecycle: ModelOverrideLifecycle
    from_class: SupervisionClass
    to_class: SupervisionClass

    @model_validator(mode="after")
    def override_is_luna_to_terra_only(self) -> Self:
        if self.from_class is not SupervisionClass.LUNA_XHIGH_DEFAULT:
            raise ValueError("one-ticket override must originate from Luna xhigh")
        if self.to_class is not SupervisionClass.TERRA_OR_HIGHER:
            raise ValueError("one-ticket override must target Terra high")
        return self


class SupervisionDecision(_StrictModel):
    """Pure reducer output with optional next lease and model override."""

    decision: SupervisionDecisionKind
    lease: SupervisionLease | None
    model_override: ModelOverrideState | None = None

    @model_validator(mode="after")
    def decision_shape_is_exact(self) -> Self:
        if self.decision is SupervisionDecisionKind.EXECUTION_START_REJECTED:
            if self.lease is not None:
                raise ValueError("rejected execution start cannot create a lease")
            return self
        if self.lease is None:
            raise ValueError("all non-start-rejection decisions require lease state")
        if self.decision in (
            SupervisionDecisionKind.TICKET_DEFECT_COMPLEXITY_EXCEEDED,
            SupervisionDecisionKind.MODEL_CAPABILITY_INSUFFICIENT,
            SupervisionDecisionKind.LEASE_CLOSED,
        ) and self.lease.lifecycle is not LeaseLifecycle.CLOSED:
            raise ValueError("terminal supervision decisions require a closed lease")
        if self.decision is SupervisionDecisionKind.WAKE_REVIEWER_DIAGNOSIS:
            if self.lease.lifecycle is not LeaseLifecycle.DIAGNOSIS_PENDING:
                raise ValueError("reviewer diagnosis requires a pending diagnostic lease")
        if self.decision is SupervisionDecisionKind.CONTINUE_IMPLEMENTATION:
            if self.lease.lifecycle is not LeaseLifecycle.ACTIVE:
                raise ValueError("continuation requires an active final lease")
        return self


class TicketSplitEvidence(_StrictModel):
    """Reviewer-observed split boundary already present in the approved SPEC."""

    ticket_ref: TicketReference
    dimension: TicketSplitDimension
    independently_observable_closure: bool


class TicketRepairDecision(_StrictModel):
    """Pure ticket-repair result and optional one-ticket model override."""

    decision: TicketRepairDecisionKind
    model_override: ModelOverrideState | None = None

    @model_validator(mode="after")
    def override_shape_matches_decision(self) -> Self:
        needs_override = self.decision is TicketRepairDecisionKind.REPLACE_WITH_TERRA_HIGH
        if needs_override != (self.model_override is not None):
            raise ValueError("only Terra replacement carries a model override")
        return self


def start_supervision_lease(
    lease_id: LeaseId,
    supervision_class: SupervisionClass,
    evidence: ExecutionStartedEvidence,
) -> SupervisionDecision:
    """Start timing only after complete execution-start readback."""

    if type(evidence) is not ExecutionStartedEvidence or type(supervision_class) is not SupervisionClass:
        return SupervisionDecision(
            decision=SupervisionDecisionKind.EXECUTION_START_REJECTED,
            lease=None,
        )
    try:
        trusted = ExecutionStartedEvidence.model_validate(evidence, strict=True)
    except ValidationError:
        return SupervisionDecision(
            decision=SupervisionDecisionKind.EXECUTION_START_REJECTED,
            lease=None,
        )
    if not trusted.complete:
        return SupervisionDecision(
            decision=SupervisionDecisionKind.EXECUTION_START_REJECTED,
            lease=None,
        )
    lease_kind = (
        LeaseKind.TOTAL_EXECUTION
        if supervision_class is SupervisionClass.LUNA_XHIGH_DEFAULT
        else LeaseKind.INACTIVITY
    )
    duration = (
        _LUNA_TOTAL_MS
        if supervision_class is SupervisionClass.LUNA_XHIGH_DEFAULT
        else _TERRA_INACTIVITY_MS
    )
    lease = SupervisionLease(
        lease_id=lease_id,
        project_id=trusted.project_id,
        ticket_ref=trusted.ticket_ref,
        router_receipt_ref=trusted.router_receipt_ref,
        task_ref=trusted.task_ref,
        worktree_ref=trusted.worktree_ref,
        branch_ref=trusted.branch_ref,
        baseline_commit=trusted.baseline_commit,
        supervision_class=supervision_class,
        lease_kind=lease_kind,
        lifecycle=LeaseLifecycle.ACTIVE,
        origin_ms=trusted.started_at_ms,
        duration_ms=duration,
        deadline_ms=trusted.started_at_ms + duration,
        reset_count=0,
        continue_count=0,
    )
    return SupervisionDecision(
        decision=SupervisionDecisionKind.LEASE_STARTED,
        lease=lease,
    )


def _close(
    lease: SupervisionLease,
    decision: SupervisionDecisionKind,
    model_override: ModelOverrideState | None = None,
) -> SupervisionDecision:
    return SupervisionDecision(
        decision=decision,
        lease=_replace_lease(
            lease,
            lifecycle=LeaseLifecycle.CLOSED,
            origin_ms=lease.origin_ms,
            reset_count=lease.reset_count,
            continue_count=lease.continue_count,
        ),
        model_override=model_override,
    )


def _replace_lease(
    lease: SupervisionLease,
    *,
    lifecycle: LeaseLifecycle,
    origin_ms: MonotonicMilliseconds,
    reset_count: Counter,
    continue_count: Counter,
) -> SupervisionLease:
    return SupervisionLease(
        lease_id=lease.lease_id,
        project_id=lease.project_id,
        ticket_ref=lease.ticket_ref,
        router_receipt_ref=lease.router_receipt_ref,
        task_ref=lease.task_ref,
        worktree_ref=lease.worktree_ref,
        branch_ref=lease.branch_ref,
        baseline_commit=lease.baseline_commit,
        supervision_class=lease.supervision_class,
        lease_kind=lease.lease_kind,
        lifecycle=lifecycle,
        origin_ms=origin_ms,
        duration_ms=lease.duration_ms,
        deadline_ms=origin_ms + lease.duration_ms,
        reset_count=reset_count,
        continue_count=continue_count,
    )


def _event_rejected(lease: SupervisionLease) -> SupervisionDecision:
    return SupervisionDecision(
        decision=SupervisionDecisionKind.EVENT_REJECTED,
        lease=lease,
    )


def reduce_supervision_lease(
    lease: SupervisionLease,
    event: LeaseEvent,
    model_override: ModelOverrideState | None = None,
) -> SupervisionDecision:
    """Reduce one trusted event without performing time, task, or wake effects."""

    if type(lease) is not SupervisionLease or type(event) is not LeaseEvent:
        raise TypeError("supervision reducer requires exact strong types")
    try:
        current = SupervisionLease.model_validate(lease, strict=True)
        observed = LeaseEvent.model_validate(event, strict=True)
        override = (
            None
            if model_override is None
            else ModelOverrideState.model_validate(model_override, strict=True)
        )
    except ValidationError as error:
        raise TypeError("supervision reducer received an invalid contract") from error
    if override is not None and override.ticket_ref != current.ticket_ref:
        return _event_rejected(current)
    if current.lifecycle is LeaseLifecycle.CLOSED or observed.occurred_at_ms < current.origin_ms:
        return _event_rejected(current)

    if observed.kind is LeaseEventKind.TERMINAL_HANDOFF:
        expired_override = (
            ModelOverrideState(
                ticket_ref=override.ticket_ref,
                lifecycle=ModelOverrideLifecycle.EXPIRED,
                from_class=override.from_class,
                to_class=override.to_class,
            )
            if override is not None and override.lifecycle is ModelOverrideLifecycle.ACTIVE
            else override
        )
        return _close(
            current,
            SupervisionDecisionKind.LEASE_CLOSED,
            expired_override,
        )

    if observed.kind is LeaseEventKind.EXACT_REF_ADVANCED:
        if current.lifecycle is not LeaseLifecycle.ACTIVE:
            return _event_rejected(current)
        if observed.occurred_at_ms > current.deadline_ms:
            return _event_rejected(current)
        if current.supervision_class is SupervisionClass.LUNA_XHIGH_DEFAULT:
            return SupervisionDecision(
                decision=SupervisionDecisionKind.SILENT_ACTIVITY_RECORDED,
                lease=current,
                model_override=override,
            )
        reset = _replace_lease(
            current,
            lifecycle=LeaseLifecycle.ACTIVE,
            origin_ms=observed.occurred_at_ms,
            reset_count=current.reset_count + 1,
            continue_count=current.continue_count,
        )
        return SupervisionDecision(
            decision=SupervisionDecisionKind.SILENT_ACTIVITY_RECORDED,
            lease=reset,
            model_override=override,
        )

    if observed.kind is LeaseEventKind.TASK_STOPPED_INCOMPLETE:
        if current.lifecycle is not LeaseLifecycle.ACTIVE:
            return _event_rejected(current)
        if current.supervision_class is SupervisionClass.LUNA_XHIGH_DEFAULT:
            return _close(
                current,
                SupervisionDecisionKind.TICKET_DEFECT_COMPLEXITY_EXCEEDED,
                override,
            )
        pending = _replace_lease(
            current,
            lifecycle=LeaseLifecycle.DIAGNOSIS_PENDING,
            origin_ms=current.origin_ms,
            reset_count=current.reset_count,
            continue_count=current.continue_count,
        )
        return SupervisionDecision(
            decision=SupervisionDecisionKind.WAKE_REVIEWER_DIAGNOSIS,
            lease=pending,
            model_override=override,
        )

    if observed.kind is LeaseEventKind.DEADLINE_FIRED:
        if current.lifecycle is not LeaseLifecycle.ACTIVE:
            return _event_rejected(current)
        if observed.occurred_at_ms < current.deadline_ms:
            return _event_rejected(current)
        if current.supervision_class is SupervisionClass.LUNA_XHIGH_DEFAULT:
            return _close(
                current,
                SupervisionDecisionKind.TICKET_DEFECT_COMPLEXITY_EXCEEDED,
                override,
            )
        pending = _replace_lease(
            current,
            lifecycle=LeaseLifecycle.DIAGNOSIS_PENDING,
            origin_ms=current.origin_ms,
            reset_count=current.reset_count,
            continue_count=current.continue_count,
        )
        return SupervisionDecision(
            decision=SupervisionDecisionKind.WAKE_REVIEWER_DIAGNOSIS,
            lease=pending,
            model_override=override,
        )

    if observed.kind is LeaseEventKind.DIAGNOSIS_STOPPED_INCOMPLETE:
        if (
            current.supervision_class is not SupervisionClass.TERRA_OR_HIGHER
            or current.lifecycle is not LeaseLifecycle.DIAGNOSIS_PENDING
        ):
            return _event_rejected(current)
        if current.continue_count == 0:
            continued = _replace_lease(
                current,
                lifecycle=LeaseLifecycle.ACTIVE,
                origin_ms=observed.occurred_at_ms,
                reset_count=current.reset_count,
                continue_count=1,
            )
            return SupervisionDecision(
                decision=SupervisionDecisionKind.CONTINUE_IMPLEMENTATION,
                lease=continued,
                model_override=override,
            )
        return _close(
            current,
            SupervisionDecisionKind.MODEL_CAPABILITY_INSUFFICIENT,
            override,
        )

    return _event_rejected(current)


def close_supervision_lease(
    lease: SupervisionLease,
    model_override: ModelOverrideState | None = None,
) -> SupervisionDecision:
    """Close an exact lease when its outer capability or binding is revoked."""

    if type(lease) is not SupervisionLease:
        raise TypeError("supervision closure requires exact lease state")
    try:
        current = SupervisionLease.model_validate(lease, strict=True)
        override = (
            None
            if model_override is None
            else ModelOverrideState.model_validate(model_override, strict=True)
        )
    except ValidationError as error:
        raise TypeError("supervision closure received invalid state") from error
    if current.lifecycle is LeaseLifecycle.CLOSED:
        return SupervisionDecision(
            decision=SupervisionDecisionKind.LEASE_CLOSED,
            lease=current,
            model_override=override,
        )
    return _close(current, SupervisionDecisionKind.LEASE_CLOSED, override)


def resolve_ticket_repair(evidence: TicketSplitEvidence) -> TicketRepairDecision:
    """Split along an approved vertical closure or bind one Terra-high override."""

    if type(evidence) is not TicketSplitEvidence:
        raise TypeError("ticket repair requires exact split evidence")
    try:
        trusted = TicketSplitEvidence.model_validate(evidence, strict=True)
    except ValidationError as error:
        raise TypeError("ticket repair received invalid split evidence") from error
    legal_dimensions = (
        TicketSplitDimension.OBSERVABLE_BEHAVIOR_STATE,
        TicketSplitDimension.EXTERNAL_EFFECT,
        TicketSplitDimension.OWNERSHIP_COMPOSITION_ROOT,
        TicketSplitDimension.VERIFICATION_BOUNDARY,
    )
    if trusted.dimension not in legal_dimensions:
        return TicketRepairDecision(
            decision=TicketRepairDecisionKind.REJECT_ILLEGAL_SPLIT,
        )
    if trusted.independently_observable_closure:
        return TicketRepairDecision(
            decision=TicketRepairDecisionKind.SPLIT_FOR_LUNA,
        )
    return TicketRepairDecision(
        decision=TicketRepairDecisionKind.REPLACE_WITH_TERRA_HIGH,
        model_override=ModelOverrideState(
            ticket_ref=trusted.ticket_ref,
            lifecycle=ModelOverrideLifecycle.ACTIVE,
            from_class=SupervisionClass.LUNA_XHIGH_DEFAULT,
            to_class=SupervisionClass.TERRA_OR_HIGHER,
        ),
    )


__all__ = [
    "ExecutionStartedEvidence",
    "LeaseEvent",
    "LeaseEventKind",
    "LeaseKind",
    "LeaseLifecycle",
    "ModelOverrideLifecycle",
    "ModelOverrideState",
    "SupervisionClass",
    "SupervisionDecision",
    "SupervisionDecisionKind",
    "SupervisionLease",
    "TicketRepairDecision",
    "TicketRepairDecisionKind",
    "TicketSplitDimension",
    "TicketSplitEvidence",
    "reduce_supervision_lease",
    "close_supervision_lease",
    "resolve_ticket_repair",
    "start_supervision_lease",
]
