"""Pure write-owning execution identity and model replacement policy."""

from __future__ import annotations

from enum import Enum
from typing import Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .contracts import (
    BranchFingerprint,
    OpaqueMetadataId,
    ReviewedCommitReference,
    RevisionDigest,
    WorktreeFingerprint,
)
from .live_dispatch_contracts import ReceiptLifecycle, TicketReceipt


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
        revalidate_instances="always",
    )


BindingReference: TypeAlias = OpaqueMetadataId
TaskReference: TypeAlias = OpaqueMetadataId
WriterReference: TypeAlias = OpaqueMetadataId
HostReference: TypeAlias = OpaqueMetadataId
MachineReference: TypeAlias = OpaqueMetadataId
CorrelationId: TypeAlias = OpaqueMetadataId
LeaseReference: TypeAlias = OpaqueMetadataId
SubscriptionId: TypeAlias = OpaqueMetadataId
CheckpointReference: TypeAlias = OpaqueMetadataId
EvidenceReference: TypeAlias = OpaqueMetadataId
ReplacementId: TypeAlias = OpaqueMetadataId
CommitId: TypeAlias = ReviewedCommitReference


class ExecutionBindingLifecycle(str, Enum):
    ACTIVE = "ACTIVE"
    REPLACEMENT_PENDING = "REPLACEMENT_PENDING"
    REPLACED = "REPLACED"
    CLOSED = "CLOSED"


class ExecutionModel(str, Enum):
    LUNA_XHIGH = "LUNA_XHIGH"
    TERRA_HIGH = "TERRA_HIGH"
    TERRA_XHIGH = "TERRA_XHIGH"
    SOL_XHIGH = "SOL_XHIGH"


class ExecutionReplacementDecisionKind(str, Enum):
    SAME_EXECUTION_NOOP = "SAME_EXECUTION_NOOP"
    REPLACEMENT_READY = "REPLACEMENT_READY"
    REPLACED = "REPLACED"
    MODEL_REBOUND_IN_PLACE = "MODEL_REBOUND_IN_PLACE"
    REJECTED = "REJECTED"


class ExecutionReplacementFailure(str, Enum):
    INVALID_CONTRACT = "INVALID_CONTRACT"
    CHECKPOINT_REQUIRED = "CHECKPOINT_REQUIRED"
    LAST_COMMIT_ONLY = "LAST_COMMIT_ONLY"
    CLEAN_CHECKOUT_REQUIRED = "CLEAN_CHECKOUT_REQUIRED"
    RECEIPT_REPLACEMENT_REQUIRED = "RECEIPT_REPLACEMENT_REQUIRED"
    REVOCATION_UNPROVEN = "REVOCATION_UNPROVEN"
    ACTIVATION_UNPROVEN = "ACTIVATION_UNPROVEN"
    MODEL_REBIND_UNPROVEN = "MODEL_REBIND_UNPROVEN"


class ExecutionEventStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    STALE_BINDING = "STALE_BINDING"


class ExecutionBinding(_StrictModel):
    """One write-owning task identity bound to the ticket's active receipt."""

    binding_ref: BindingReference
    binding_revision: RevisionDigest
    lifecycle: ExecutionBindingLifecycle
    receipt: TicketReceipt
    implementation_owner_ref: OpaqueMetadataId
    task_ref: TaskReference
    effective_writer_ref: WriterReference
    host_ref: HostReference
    machine_ref: MachineReference
    worktree_ref: WorktreeFingerprint
    branch_ref: BranchFingerprint
    baseline_commit: CommitId
    correlation_id: CorrelationId
    model: ExecutionModel
    write_lease_ref: LeaseReference
    subscription_id: SubscriptionId
    last_committed_commit: CommitId

    @model_validator(mode="after")
    def binding_matches_receipt(self) -> Self:
        if (
            self.lifecycle is ExecutionBindingLifecycle.ACTIVE
            and self.receipt.lifecycle is not ReceiptLifecycle.ACTIVE
        ):
            raise ValueError("active execution binding requires an active receipt")
        if self.receipt.lifecycle is ReceiptLifecycle.QUARANTINED:
            raise ValueError("execution bindings cannot use quarantined receipts")
        if (
            self.implementation_owner_ref != self.receipt.implementation_owner_id
            or self.worktree_ref != self.receipt.worktree_fingerprint
            or self.branch_ref != self.receipt.branch_fingerprint
            or self.baseline_commit != self.receipt.baseline_commit
        ):
            raise ValueError("execution binding must match receipt-bound ownership fields")
        for commit in (self.baseline_commit, self.last_committed_commit):
            if len(commit) not in (40, 64) or any(character not in "0123456789abcdef" for character in commit):
                raise ValueError("execution commits must be lowercase Git object IDs")
        return self


class ExecutionIdentityObservation(_StrictModel):
    """Readback of the effective writer; shell identity is deliberately non-authoritative."""

    task_ref: TaskReference
    effective_writer_ref: WriterReference
    host_ref: HostReference
    machine_ref: MachineReference
    shell_session_ref: OpaqueMetadataId


class ExecutionReplacementCandidate(_StrictModel):
    """Proposed successor binding before old-writer revocation."""

    binding_ref: BindingReference
    binding_revision: RevisionDigest
    receipt: TicketReceipt
    implementation_owner_ref: OpaqueMetadataId
    task_ref: TaskReference
    effective_writer_ref: WriterReference
    host_ref: HostReference
    machine_ref: MachineReference
    worktree_ref: WorktreeFingerprint
    branch_ref: BranchFingerprint
    baseline_commit: CommitId
    correlation_id: CorrelationId
    model: ExecutionModel
    write_lease_ref: LeaseReference
    subscription_id: SubscriptionId
    worktree_is_fresh_clean_checkout: bool

    @model_validator(mode="after")
    def candidate_matches_receipt(self) -> Self:
        if self.receipt.lifecycle is not ReceiptLifecycle.ACTIVE:
            raise ValueError("replacement candidate requires an active receipt")
        if (
            self.implementation_owner_ref != self.receipt.implementation_owner_id
            or self.worktree_ref != self.receipt.worktree_fingerprint
            or self.branch_ref != self.receipt.branch_fingerprint
            or self.baseline_commit != self.receipt.baseline_commit
        ):
            raise ValueError("replacement candidate must match its receipt")
        if len(self.baseline_commit) not in (40, 64) or any(
            character not in "0123456789abcdef" for character in self.baseline_commit
        ):
            raise ValueError("replacement baseline must be a lowercase Git object ID")
        return self


class ReplacementReceiptAuthority(_StrictModel):
    """Router-only authority when a receipt-bound ownership field changes."""

    router_authorized: bool
    old_receipt_revoked: bool
    replacement_receipt: TicketReceipt


class ExecutionReplacementRequest(_StrictModel):
    """Either a same-task observation or one complete successor proposal."""

    replacement_id: ReplacementId
    current: ExecutionBinding
    identity_observation: ExecutionIdentityObservation | None = None
    candidate: ExecutionReplacementCandidate | None
    old_task_available: bool
    checkpoint_ref: CheckpointReference | None
    checkpoint_commit: CommitId | None
    receipt_authority: ReplacementReceiptAuthority | None

    @model_validator(mode="after")
    def request_has_one_action_shape(self) -> Self:
        if self.current.lifecycle is not ExecutionBindingLifecycle.ACTIVE:
            raise ValueError("only an active execution may be observed or replaced")
        if self.candidate is None:
            if self.identity_observation is None:
                raise ValueError("no-candidate request requires an identity observation")
            if (
                self.checkpoint_ref is not None
                or self.checkpoint_commit is not None
                or self.receipt_authority is not None
            ):
                raise ValueError("same-session observation cannot carry replacement authority")
        elif self.identity_observation is not None:
            raise ValueError("replacement candidate and identity observation are exclusive")
        if (self.checkpoint_ref is None) != (self.checkpoint_commit is None):
            raise ValueError("checkpoint reference and commit must appear together")
        if self.checkpoint_commit is not None and (
            len(self.checkpoint_commit) not in (40, 64)
            or any(character not in "0123456789abcdef" for character in self.checkpoint_commit)
        ):
            raise ValueError("checkpoint commit must be a lowercase Git object ID")
        return self


class ExecutionReplacementPlan(_StrictModel):
    decision: ExecutionReplacementDecisionKind
    replacement_id: ReplacementId
    current: ExecutionBinding
    candidate: ExecutionReplacementCandidate | None = None
    checkpoint_ref: CheckpointReference | None = None
    checkpoint_commit: CommitId | None = None
    old_receipt_revoked: bool = False
    failure: ExecutionReplacementFailure | None = None

    @model_validator(mode="after")
    def exact_plan_shape(self) -> Self:
        if self.decision is ExecutionReplacementDecisionKind.REPLACEMENT_READY:
            if (
                self.current.lifecycle is not ExecutionBindingLifecycle.REPLACEMENT_PENDING
                or self.candidate is None
                or self.failure is not None
            ):
                raise ValueError("ready replacement requires pending old and one candidate")
        elif self.decision is ExecutionReplacementDecisionKind.SAME_EXECUTION_NOOP:
            if (
                self.current.lifecycle is not ExecutionBindingLifecycle.ACTIVE
                or self.candidate is not None
                or self.failure is not None
            ):
                raise ValueError("same execution no-op retains only active current binding")
        elif self.decision is ExecutionReplacementDecisionKind.REJECTED:
            if self.candidate is not None or self.failure is None:
                raise ValueError("rejected replacement exposes no candidate and one failure")
        else:
            raise ValueError("plan supports only no-op, ready, or rejected decisions")
        return self


class ExecutionRevocationReadback(_StrictModel):
    binding_ref: BindingReference
    write_disabled: bool
    subscription_closed: bool
    evidence_refs: tuple[EvidenceReference, ...] = Field(min_length=1)


class ExecutionActivationReadback(_StrictModel):
    binding_ref: BindingReference
    task_ref: TaskReference
    effective_writer_ref: WriterReference
    host_ref: HostReference
    machine_ref: MachineReference
    write_enabled: bool
    evidence_refs: tuple[EvidenceReference, ...] = Field(min_length=1)


class ExecutionReplacementResult(_StrictModel):
    decision: ExecutionReplacementDecisionKind
    replacement_id: ReplacementId
    current: ExecutionBinding
    active: ExecutionBinding | None = None
    failure: ExecutionReplacementFailure | None = None

    @model_validator(mode="after")
    def exact_result_shape(self) -> Self:
        success = self.decision in (
            ExecutionReplacementDecisionKind.REPLACED,
            ExecutionReplacementDecisionKind.MODEL_REBOUND_IN_PLACE,
        )
        if success:
            if self.active is None or self.failure is not None:
                raise ValueError("successful replacement requires one active binding")
        elif self.decision is ExecutionReplacementDecisionKind.REJECTED:
            if self.active is not None or self.failure is None:
                raise ValueError("rejected replacement requires one failure")
        else:
            raise ValueError("replacement result has invalid terminal decision")
        return self


class ExecutionEventIdentity(_StrictModel):
    binding_ref: BindingReference
    task_ref: TaskReference
    receipt_ref: OpaqueMetadataId
    correlation_id: CorrelationId


class ModelRebindEvidence(_StrictModel):
    binding_revision: RevisionDigest
    task_ref: TaskReference
    host_ref: HostReference
    target_model: ExecutionModel
    in_place_rebind_proven: bool
    evidence_refs: tuple[EvidenceReference, ...] = Field(min_length=1)


def _replace_binding_lifecycle(
    binding: ExecutionBinding,
    lifecycle: ExecutionBindingLifecycle,
    receipt: TicketReceipt | None = None,
) -> ExecutionBinding:
    return ExecutionBinding(
        binding_ref=binding.binding_ref,
        binding_revision=binding.binding_revision,
        lifecycle=lifecycle,
        receipt=receipt or binding.receipt,
        implementation_owner_ref=binding.implementation_owner_ref,
        task_ref=binding.task_ref,
        effective_writer_ref=binding.effective_writer_ref,
        host_ref=binding.host_ref,
        machine_ref=binding.machine_ref,
        worktree_ref=binding.worktree_ref,
        branch_ref=binding.branch_ref,
        baseline_commit=binding.baseline_commit,
        correlation_id=binding.correlation_id,
        model=binding.model,
        write_lease_ref=binding.write_lease_ref,
        subscription_id=binding.subscription_id,
        last_committed_commit=binding.last_committed_commit,
    )


def _replace_receipt_lifecycle(
    receipt: TicketReceipt,
    lifecycle: ReceiptLifecycle,
) -> TicketReceipt:
    return TicketReceipt(
        project_id=receipt.project_id,
        receipt_id=receipt.receipt_id,
        ticket_reference=receipt.ticket_reference,
        ticket_revision=receipt.ticket_revision,
        ticket_digest=receipt.ticket_digest,
        ticket_document_commit=receipt.ticket_document_commit,
        handoff_reference=receipt.handoff_reference,
        handoff_revision=receipt.handoff_revision,
        handoff_digest=receipt.handoff_digest,
        handoff_document_commit=receipt.handoff_document_commit,
        baseline_commit=receipt.baseline_commit,
        implementation_owner_id=receipt.implementation_owner_id,
        expected_return=receipt.expected_return,
        descriptor_binding=receipt.descriptor_binding,
        correlation_id=receipt.correlation_id,
        dispatch_question_id=receipt.dispatch_question_id,
        worktree_fingerprint=receipt.worktree_fingerprint,
        branch_fingerprint=receipt.branch_fingerprint,
        lifecycle=lifecycle,
    )


def _receipt_bound_fields_changed(
    current: ExecutionBinding,
    candidate: ExecutionReplacementCandidate,
) -> bool:
    return any(
        (
            current.implementation_owner_ref != candidate.implementation_owner_ref,
            current.worktree_ref != candidate.worktree_ref,
            current.branch_ref != candidate.branch_ref,
            current.baseline_commit != candidate.baseline_commit,
            current.receipt.receipt_id != candidate.receipt.receipt_id,
        )
    )


def _reject(
    request: ExecutionReplacementRequest,
    failure: ExecutionReplacementFailure,
) -> ExecutionReplacementPlan:
    return ExecutionReplacementPlan(
        decision=ExecutionReplacementDecisionKind.REJECTED,
        replacement_id=request.replacement_id,
        current=request.current,
        failure=failure,
    )


def plan_execution_replacement(
    request: ExecutionReplacementRequest,
) -> ExecutionReplacementPlan:
    """Admit a no-op or freeze the old writer pending proven revocation."""

    if type(request) is not ExecutionReplacementRequest:
        raise TypeError("replacement planning requires an exact request")
    try:
        trusted = ExecutionReplacementRequest.model_validate(request, strict=True)
    except ValidationError as error:
        raise TypeError("replacement planning received an invalid contract") from error
    current = trusted.current
    if trusted.candidate is None:
        observation = trusted.identity_observation
        if observation is None:
            return _reject(trusted, ExecutionReplacementFailure.INVALID_CONTRACT)
        same_execution = all(
            (
                observation.task_ref == current.task_ref,
                observation.effective_writer_ref == current.effective_writer_ref,
                observation.host_ref == current.host_ref,
                observation.machine_ref == current.machine_ref,
            )
        )
        if same_execution:
            return ExecutionReplacementPlan(
                decision=ExecutionReplacementDecisionKind.SAME_EXECUTION_NOOP,
                replacement_id=trusted.replacement_id,
                current=current,
            )
        return _reject(trusted, ExecutionReplacementFailure.INVALID_CONTRACT)

    candidate = trusted.candidate
    if trusted.old_task_available:
        if trusted.checkpoint_ref is None or trusted.checkpoint_commit is None:
            return _reject(trusted, ExecutionReplacementFailure.CHECKPOINT_REQUIRED)
        if trusted.checkpoint_commit != current.last_committed_commit:
            return _reject(trusted, ExecutionReplacementFailure.CHECKPOINT_REQUIRED)
    else:
        if trusted.checkpoint_ref is not None or trusted.checkpoint_commit is not None:
            return _reject(trusted, ExecutionReplacementFailure.LAST_COMMIT_ONLY)
        if candidate.baseline_commit != current.last_committed_commit:
            return _reject(trusted, ExecutionReplacementFailure.LAST_COMMIT_ONLY)
    if (
        candidate.machine_ref != current.machine_ref
        and not candidate.worktree_is_fresh_clean_checkout
    ):
        return _reject(trusted, ExecutionReplacementFailure.CLEAN_CHECKOUT_REQUIRED)

    receipt_changed = _receipt_bound_fields_changed(current, candidate)
    authority = trusted.receipt_authority
    if receipt_changed:
        if (
            authority is None
            or not authority.router_authorized
            or not authority.old_receipt_revoked
            or authority.replacement_receipt != candidate.receipt
            or authority.replacement_receipt.receipt_id == current.receipt.receipt_id
        ):
            return _reject(
                trusted,
                ExecutionReplacementFailure.RECEIPT_REPLACEMENT_REQUIRED,
            )
    elif authority is not None or candidate.receipt != current.receipt:
        return _reject(
            trusted,
            ExecutionReplacementFailure.RECEIPT_REPLACEMENT_REQUIRED,
        )
    pending_receipt = (
        _replace_receipt_lifecycle(current.receipt, ReceiptLifecycle.REVOKED)
        if receipt_changed
        else current.receipt
    )
    pending = _replace_binding_lifecycle(
        current,
        ExecutionBindingLifecycle.REPLACEMENT_PENDING,
        pending_receipt,
    )
    return ExecutionReplacementPlan(
        decision=ExecutionReplacementDecisionKind.REPLACEMENT_READY,
        replacement_id=trusted.replacement_id,
        current=pending,
        candidate=candidate,
        checkpoint_ref=trusted.checkpoint_ref,
        checkpoint_commit=trusted.checkpoint_commit,
        old_receipt_revoked=authority.old_receipt_revoked if authority is not None else False,
    )


def _active_from_candidate(
    candidate: ExecutionReplacementCandidate,
    last_committed_commit: CommitId,
) -> ExecutionBinding:
    return ExecutionBinding(
        binding_ref=candidate.binding_ref,
        binding_revision=candidate.binding_revision,
        lifecycle=ExecutionBindingLifecycle.ACTIVE,
        receipt=candidate.receipt,
        implementation_owner_ref=candidate.implementation_owner_ref,
        task_ref=candidate.task_ref,
        effective_writer_ref=candidate.effective_writer_ref,
        host_ref=candidate.host_ref,
        machine_ref=candidate.machine_ref,
        worktree_ref=candidate.worktree_ref,
        branch_ref=candidate.branch_ref,
        baseline_commit=candidate.baseline_commit,
        correlation_id=candidate.correlation_id,
        model=candidate.model,
        write_lease_ref=candidate.write_lease_ref,
        subscription_id=candidate.subscription_id,
        last_committed_commit=last_committed_commit,
    )


def complete_execution_replacement(
    plan: ExecutionReplacementPlan,
    revocation: ExecutionRevocationReadback,
    activation: ExecutionActivationReadback,
) -> ExecutionReplacementResult:
    """Activate a successor only after exact old-writer revocation readback."""

    if (
        type(plan) is not ExecutionReplacementPlan
        or type(revocation) is not ExecutionRevocationReadback
        or type(activation) is not ExecutionActivationReadback
    ):
        raise TypeError("replacement completion requires exact strong types")
    try:
        trusted_plan = ExecutionReplacementPlan.model_validate(plan, strict=True)
        trusted_revocation = ExecutionRevocationReadback.model_validate(revocation, strict=True)
        trusted_activation = ExecutionActivationReadback.model_validate(activation, strict=True)
    except ValidationError as error:
        raise TypeError("replacement completion received an invalid contract") from error
    candidate = trusted_plan.candidate
    if trusted_plan.decision is not ExecutionReplacementDecisionKind.REPLACEMENT_READY or candidate is None:
        return ExecutionReplacementResult(
            decision=ExecutionReplacementDecisionKind.REJECTED,
            replacement_id=trusted_plan.replacement_id,
            current=trusted_plan.current,
            failure=ExecutionReplacementFailure.INVALID_CONTRACT,
        )
    if (
        trusted_revocation.binding_ref != trusted_plan.current.binding_ref
        or not trusted_revocation.write_disabled
        or not trusted_revocation.subscription_closed
    ):
        return ExecutionReplacementResult(
            decision=ExecutionReplacementDecisionKind.REJECTED,
            replacement_id=trusted_plan.replacement_id,
            current=trusted_plan.current,
            failure=ExecutionReplacementFailure.REVOCATION_UNPROVEN,
        )
    if not all(
        (
            trusted_activation.binding_ref == candidate.binding_ref,
            trusted_activation.task_ref == candidate.task_ref,
            trusted_activation.effective_writer_ref == candidate.effective_writer_ref,
            trusted_activation.host_ref == candidate.host_ref,
            trusted_activation.machine_ref == candidate.machine_ref,
            trusted_activation.write_enabled,
        )
    ):
        return ExecutionReplacementResult(
            decision=ExecutionReplacementDecisionKind.REJECTED,
            replacement_id=trusted_plan.replacement_id,
            current=trusted_plan.current,
            failure=ExecutionReplacementFailure.ACTIVATION_UNPROVEN,
        )
    old = _replace_binding_lifecycle(
        trusted_plan.current,
        ExecutionBindingLifecycle.REPLACED,
    )
    checkpoint = trusted_plan.checkpoint_commit or trusted_plan.current.last_committed_commit
    active = _active_from_candidate(candidate, checkpoint)
    return ExecutionReplacementResult(
        decision=ExecutionReplacementDecisionKind.REPLACED,
        replacement_id=trusted_plan.replacement_id,
        current=old,
        active=active,
    )


def validate_execution_event(
    replacement: ExecutionReplacementResult,
    event: ExecutionEventIdentity,
) -> ExecutionEventStatus:
    """Reject stale old task/correlation events after replacement."""

    active = replacement.active
    if active is None or active.lifecycle is not ExecutionBindingLifecycle.ACTIVE:
        return ExecutionEventStatus.STALE_BINDING
    if all(
        (
            event.binding_ref == active.binding_ref,
            event.task_ref == active.task_ref,
            event.receipt_ref == active.receipt.receipt_id,
            event.correlation_id == active.correlation_id,
        )
    ):
        return ExecutionEventStatus.ACCEPTED
    return ExecutionEventStatus.STALE_BINDING


def rebind_execution_model(
    current: ExecutionBinding,
    evidence: ModelRebindEvidence,
) -> ExecutionReplacementResult:
    """Rebind a model in place only with host proof and identical execution identity."""

    if type(current) is not ExecutionBinding or type(evidence) is not ModelRebindEvidence:
        raise TypeError("model rebind requires exact strong types")
    try:
        binding = ExecutionBinding.model_validate(current, strict=True)
        readback = ModelRebindEvidence.model_validate(evidence, strict=True)
    except ValidationError as error:
        raise TypeError("model rebind received an invalid contract") from error
    allowed = all(
        (
            binding.lifecycle is ExecutionBindingLifecycle.ACTIVE,
            readback.in_place_rebind_proven,
            readback.task_ref == binding.task_ref,
            readback.host_ref == binding.host_ref,
            binding.model is ExecutionModel.LUNA_XHIGH,
            readback.target_model is ExecutionModel.TERRA_HIGH,
            readback.binding_revision != binding.binding_revision,
        )
    )
    if not allowed:
        return ExecutionReplacementResult(
            decision=ExecutionReplacementDecisionKind.REJECTED,
            replacement_id="replacement-model-rebind-rejected",
            current=binding,
            failure=ExecutionReplacementFailure.MODEL_REBIND_UNPROVEN,
        )
    rebound = ExecutionBinding(
        binding_ref=binding.binding_ref,
        binding_revision=readback.binding_revision,
        lifecycle=ExecutionBindingLifecycle.ACTIVE,
        receipt=binding.receipt,
        implementation_owner_ref=binding.implementation_owner_ref,
        task_ref=binding.task_ref,
        effective_writer_ref=binding.effective_writer_ref,
        host_ref=binding.host_ref,
        machine_ref=binding.machine_ref,
        worktree_ref=binding.worktree_ref,
        branch_ref=binding.branch_ref,
        baseline_commit=binding.baseline_commit,
        correlation_id=binding.correlation_id,
        model=readback.target_model,
        write_lease_ref=binding.write_lease_ref,
        subscription_id=binding.subscription_id,
        last_committed_commit=binding.last_committed_commit,
    )
    return ExecutionReplacementResult(
        decision=ExecutionReplacementDecisionKind.MODEL_REBOUND_IN_PLACE,
        replacement_id="replacement-model-rebind-approved",
        current=binding,
        active=rebound,
    )


def close_execution_binding(binding: ExecutionBinding) -> ExecutionBinding:
    """Close write authority after a terminal handoff."""

    if type(binding) is not ExecutionBinding:
        raise TypeError("binding close requires an exact execution binding")
    return _replace_binding_lifecycle(binding, ExecutionBindingLifecycle.CLOSED)


__all__ = [
    "ExecutionActivationReadback",
    "ExecutionBinding",
    "ExecutionBindingLifecycle",
    "ExecutionEventIdentity",
    "ExecutionEventStatus",
    "ExecutionIdentityObservation",
    "ExecutionModel",
    "ExecutionReplacementCandidate",
    "ExecutionReplacementDecisionKind",
    "ExecutionReplacementFailure",
    "ExecutionReplacementPlan",
    "ExecutionReplacementRequest",
    "ExecutionReplacementResult",
    "ExecutionRevocationReadback",
    "ModelRebindEvidence",
    "ReplacementReceiptAuthority",
    "close_execution_binding",
    "complete_execution_replacement",
    "plan_execution_replacement",
    "rebind_execution_model",
    "validate_execution_event",
]
