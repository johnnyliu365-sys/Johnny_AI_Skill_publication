"""Strong contracts and preflight for one-shot receipt-bound role wake."""

from __future__ import annotations

from enum import Enum
from hashlib import sha256
import json
from typing import Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .contracts import EvidenceDigest, OpaqueMetadataId, ProjectId, RevisionDigest
from .git_handoff_contracts import (
    EventSourceRef,
    GitEventAdapterDecision,
    GitEventAdapterDecisionKind,
    GitEventRegistrationLifecycle,
    GitEventRegistrationState,
    GitObservationMode,
    SubscriptionId,
    SupervisionFaultKind,
)
from .live_dispatch_contracts import ReceiptLifecycle, TicketReceipt
from .review_inbox_contracts import ReviewWakeInstruction
from .thread_dispatch_contracts import derive_ticket_receipt_digest
from .role_supervision_contracts import HandoffId
from .thread_host_contracts import CodexHostId, CodexTaskId, CodexThreadId


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
        revalidate_instances="always",
    )


RoleReference: TypeAlias = OpaqueMetadataId
TaskReference: TypeAlias = OpaqueMetadataId
EvidenceReference: TypeAlias = OpaqueMetadataId
WakeAttemptId: TypeAlias = OpaqueMetadataId
LeaseId: TypeAlias = OpaqueMetadataId
DeliveryReference: TypeAlias = OpaqueMetadataId


class RoleWakeCapabilityState(str, Enum):
    PROVEN = "PROVEN"
    UNAVAILABLE = "UNAVAILABLE"


class DeadlineCapabilityState(str, Enum):
    PROVEN = "PROVEN"
    UNAVAILABLE = "UNAVAILABLE"


class RoleWakeChainStatus(str, Enum):
    PROVEN = "PROVEN"
    REJECTED = "REJECTED"


class RoleWakeChainFailure(str, Enum):
    ROLE_WAKE_CHAIN_UNAVAILABLE = "ROLE_WAKE_CHAIN_UNAVAILABLE"
    HOST_WAKE_CAPABILITY_UNAVAILABLE = "HOST_WAKE_CAPABILITY_UNAVAILABLE"


class RoleWakeTriggerKind(str, Enum):
    REVIEW_HANDOFF = "REVIEW_HANDOFF"
    SUPERVISION_DEADLINE = "SUPERVISION_DEADLINE"
    SUPERVISION_FAULT = "SUPERVISION_FAULT"


class RoleWakeAttemptLifecycle(str, Enum):
    CLAIMED = "CLAIMED"
    HOST_ACCEPTED = "HOST_ACCEPTED"
    NO_EFFECT = "NO_EFFECT"
    EFFECT_UNCERTAIN = "EFFECT_UNCERTAIN"


class WakeAttemptClaimStatus(str, Enum):
    CLAIMED = "CLAIMED"
    ALREADY_CLAIMED = "ALREADY_CLAIMED"
    ATTEMPT_CONFLICT = "ATTEMPT_CONFLICT"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class WakeAttemptSettleStatus(str, Enum):
    SETTLED = "SETTLED"
    ALREADY_SETTLED = "ALREADY_SETTLED"
    CLAIM_MISMATCH = "CLAIM_MISMATCH"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class RoleWakeEffectStatus(str, Enum):
    HOST_ACCEPTED = "HOST_ACCEPTED"
    NO_EFFECT = "NO_EFFECT"
    EFFECT_UNCERTAIN = "EFFECT_UNCERTAIN"


class RoleWakeStatus(str, Enum):
    HOST_ACCEPTED = "HOST_ACCEPTED"
    QUEUED_NO_WAKE = "QUEUED_NO_WAKE"
    NO_EFFECT = "NO_EFFECT"
    EFFECT_UNCERTAIN = "EFFECT_UNCERTAIN"
    ATTEMPT_CONFLICT = "ATTEMPT_CONFLICT"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class RoleWakeCapabilityProof(_StrictModel):
    """Host readback proving one exact named reviewer wake target."""

    project_id: ProjectId
    ticket_ref: OpaqueMetadataId
    router_receipt_ref: OpaqueMetadataId
    bound_event_source_ref: EventSourceRef
    bound_subscription_id: SubscriptionId
    bound_implementation_task_ref: TaskReference
    reviewer_ref: RoleReference
    reviewer_task_id: CodexTaskId
    reviewer_thread_id: CodexThreadId
    host_id: CodexHostId
    wake_port_revision: RevisionDigest
    binding_digest: EvidenceDigest
    state: RoleWakeCapabilityState
    evidence_refs: tuple[EvidenceReference, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def exact_reviewer_identity(self) -> Self:
        if self.reviewer_task_id != self.reviewer_thread_id:
            raise ValueError("reviewer task and thread must be identical")
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("wake capability evidence must be unique")
        return self


class MonotonicDeadlineCapabilityProof(_StrictModel):
    """Proof of a one-shot monotonic deadline implementation."""

    project_id: ProjectId
    ticket_ref: OpaqueMetadataId
    router_receipt_ref: OpaqueMetadataId
    implementation_task_ref: TaskReference
    capability_revision: RevisionDigest
    state: DeadlineCapabilityState
    one_shot_supported: bool
    recurring_callback_required: bool
    evidence_refs: tuple[EvidenceReference, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def evidence_refs_are_unique(self) -> Self:
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("deadline capability evidence must be unique")
        return self


class RoleWakeChainPreflightRequest(_StrictModel):
    """All exact bindings required before implementation dispatch."""

    receipt: TicketReceipt
    registration: GitEventRegistrationState
    reviewer_ref: RoleReference
    implementation_task_ref: TaskReference
    wake_capability: RoleWakeCapabilityProof
    deadline_capability: MonotonicDeadlineCapabilityProof


def _chain_digest(
    receipt: TicketReceipt,
    registration: GitEventRegistrationState,
    reviewer_ref: RoleReference,
    implementation_task_ref: TaskReference,
    wake_capability: RoleWakeCapabilityProof,
    deadline_capability: MonotonicDeadlineCapabilityProof,
) -> EvidenceDigest:
    material = json.dumps(
        {
            "deadline_capability": deadline_capability.model_dump(mode="json"),
            "implementation_task_ref": implementation_task_ref,
            "receipt": receipt.model_dump(mode="json"),
            "registration": registration.model_dump(mode="json"),
            "reviewer_ref": reviewer_ref,
            "wake_capability": wake_capability.model_dump(mode="json"),
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256_" + sha256(material).hexdigest()


class RoleWakeChainProof(RoleWakeChainPreflightRequest):
    """Immutable digest-bound composition proven by preflight."""

    chain_digest: EvidenceDigest

    @model_validator(mode="after")
    def chain_digest_is_exact(self) -> Self:
        expected = _chain_digest(
            self.receipt,
            self.registration,
            self.reviewer_ref,
            self.implementation_task_ref,
            self.wake_capability,
            self.deadline_capability,
        )
        if self.chain_digest != expected:
            raise ValueError("wake-chain digest must bind the exact preflight")
        return self


class RoleWakeChainPreflightResult(_StrictModel):
    status: RoleWakeChainStatus
    proof: RoleWakeChainProof | None = None
    failure: RoleWakeChainFailure | None = None

    @model_validator(mode="after")
    def exact_proof_or_failure(self) -> Self:
        if self.status is RoleWakeChainStatus.PROVEN:
            if self.proof is None or self.failure is not None:
                raise ValueError("proven wake chain requires one proof")
        elif self.proof is not None or self.failure is None:
            raise ValueError("rejected wake chain requires one failure")
        return self


def _chain_bindings_match(request: RoleWakeChainPreflightRequest) -> bool:
    receipt = request.receipt
    registration = request.registration
    wake = request.wake_capability
    deadline = request.deadline_capability
    return all(
        (
            receipt.lifecycle is ReceiptLifecycle.ACTIVE,
            registration.lifecycle is GitEventRegistrationLifecycle.ACTIVE,
            registration.mode is GitObservationMode.NATIVE_REF_EVENT,
            registration.project_id == receipt.project_id,
            registration.ticket_ref == receipt.ticket_reference,
            registration.router_receipt_ref == receipt.receipt_id,
            registration.implementation_task_ref == request.implementation_task_ref,
            registration.worktree_ref == receipt.worktree_fingerprint,
            registration.branch_ref == receipt.branch_fingerprint,
            registration.baseline_commit == receipt.baseline_commit,
            registration.correlation_id == receipt.correlation_id,
            wake.state is RoleWakeCapabilityState.PROVEN,
            wake.project_id == receipt.project_id,
            wake.ticket_ref == receipt.ticket_reference,
            wake.router_receipt_ref == receipt.receipt_id,
            wake.bound_event_source_ref == registration.event_source_ref,
            wake.bound_subscription_id == registration.subscription_id,
            wake.bound_implementation_task_ref == request.implementation_task_ref,
            wake.reviewer_ref == request.reviewer_ref,
            deadline.state is DeadlineCapabilityState.PROVEN,
            deadline.project_id == receipt.project_id,
            deadline.ticket_ref == receipt.ticket_reference,
            deadline.router_receipt_ref == receipt.receipt_id,
            deadline.implementation_task_ref == request.implementation_task_ref,
            deadline.one_shot_supported,
            not deadline.recurring_callback_required,
        )
    )


def _preflight_failure(
    request: RoleWakeChainPreflightRequest,
) -> RoleWakeChainFailure:
    """Keep a missing host capability distinct from an invalid bound chain."""

    if request.wake_capability.state is RoleWakeCapabilityState.UNAVAILABLE and (
        _chain_bindings_match(
            request.model_copy(
                update={
                    "wake_capability": request.wake_capability.model_copy(
                        update={"state": RoleWakeCapabilityState.PROVEN}
                    )
                }
            )
        )
    ):
        return RoleWakeChainFailure.HOST_WAKE_CAPABILITY_UNAVAILABLE
    return RoleWakeChainFailure.ROLE_WAKE_CHAIN_UNAVAILABLE


def preflight_role_wake_chain(
    request: RoleWakeChainPreflightRequest,
) -> RoleWakeChainPreflightResult:
    """Fail closed before host effect unless one exact wake chain is proven."""

    if type(request) is not RoleWakeChainPreflightRequest:
        return RoleWakeChainPreflightResult(
            status=RoleWakeChainStatus.REJECTED,
            failure=RoleWakeChainFailure.ROLE_WAKE_CHAIN_UNAVAILABLE,
        )
    try:
        trusted = RoleWakeChainPreflightRequest.model_validate(request, strict=True)
    except ValidationError:
        return RoleWakeChainPreflightResult(
            status=RoleWakeChainStatus.REJECTED,
            failure=RoleWakeChainFailure.ROLE_WAKE_CHAIN_UNAVAILABLE,
        )
    if not _chain_bindings_match(trusted):
        return RoleWakeChainPreflightResult(
            status=RoleWakeChainStatus.REJECTED,
            failure=_preflight_failure(trusted),
        )
    proof = RoleWakeChainProof(
        receipt=trusted.receipt,
        registration=trusted.registration,
        reviewer_ref=trusted.reviewer_ref,
        implementation_task_ref=trusted.implementation_task_ref,
        wake_capability=trusted.wake_capability,
        deadline_capability=trusted.deadline_capability,
        chain_digest=_chain_digest(
            trusted.receipt,
            trusted.registration,
            trusted.reviewer_ref,
            trusted.implementation_task_ref,
            trusted.wake_capability,
            trusted.deadline_capability,
        ),
    )
    return RoleWakeChainPreflightResult(
        status=RoleWakeChainStatus.PROVEN,
        proof=proof,
    )


class RoleWakeRequest(_StrictModel):
    """One trigger-specific reviewer wake request."""

    attempt_id: WakeAttemptId
    chain: RoleWakeChainProof
    trigger: RoleWakeTriggerKind
    observed_commit: str | None
    handoff_id: HandoffId | None
    lease_id: LeaseId | None
    fault_kind: SupervisionFaultKind | None
    review_instruction: ReviewWakeInstruction | None = None

    @model_validator(mode="after")
    def trigger_shape_is_exact(self) -> Self:
        if self.trigger is RoleWakeTriggerKind.REVIEW_HANDOFF:
            if (
                self.observed_commit is None
                or self.handoff_id is None
                or self.lease_id is not None
                or self.fault_kind is not None
            ):
                raise ValueError("review handoff wake requires commit and handoff only")
        elif self.trigger is RoleWakeTriggerKind.SUPERVISION_DEADLINE:
            if (
                self.observed_commit is not None
                or self.handoff_id is not None
                or self.lease_id is None
                or self.fault_kind is not None
            ):
                raise ValueError("deadline wake requires one lease only")
        elif (
            self.observed_commit is None
            or self.handoff_id is not None
            or self.lease_id is not None
            or self.fault_kind is None
        ):
            raise ValueError("fault wake requires commit and sanitized fault kind only")
        if (
            self.trigger is not RoleWakeTriggerKind.REVIEW_HANDOFF
            and self.review_instruction is not None
        ):
            raise ValueError("only review handoff may carry review read instructions")
        return self

    def render_identifiers_only_payload(self) -> str:
        registration = self.chain.registration
        receipt = self.chain.receipt
        wake = self.chain.wake_capability
        values = (
            ("protocol", "ROLE_WAKE_V1"),
            ("action", self.trigger.value),
            ("project_id", receipt.project_id),
            ("ticket_reference", receipt.ticket_reference),
            ("receipt_id", receipt.receipt_id),
            ("implementation_task_ref", self.chain.implementation_task_ref),
            ("reviewer_ref", self.chain.reviewer_ref),
            ("reviewer_task_id", wake.reviewer_task_id),
            ("reviewer_thread_id", wake.reviewer_thread_id),
            ("host_id", wake.host_id),
            ("event_source_ref", registration.event_source_ref),
            ("subscription_id", registration.subscription_id),
            ("correlation_id", receipt.correlation_id),
            ("chain_digest", self.chain.chain_digest),
            ("observed_commit", self.observed_commit or "-"),
            ("handoff_id", self.handoff_id or "-"),
            ("lease_id", self.lease_id or "-"),
            ("fault_kind", self.fault_kind.value if self.fault_kind is not None else "-"),
        )
        lines = [key + "=" + value for key, value in values]
        if self.review_instruction is not None:
            lines.extend(self.review_instruction.render_identifiers_only_lines())
        return "\n".join(lines) + "\n"


class RoleWakeAttemptIdentity(_StrictModel):
    attempt_id: WakeAttemptId
    trigger: RoleWakeTriggerKind
    project_id: ProjectId
    ticket_ref: OpaqueMetadataId
    receipt_ref: OpaqueMetadataId
    receipt_digest: EvidenceDigest
    reviewer_ref: RoleReference
    reviewer_task_id: CodexTaskId
    reviewer_thread_id: CodexThreadId
    host_id: CodexHostId
    event_source_ref: EventSourceRef
    subscription_id: SubscriptionId
    chain_digest: EvidenceDigest
    payload_digest: EvidenceDigest


def derive_role_wake_attempt_identity(request: RoleWakeRequest) -> RoleWakeAttemptIdentity:
    if type(request) is not RoleWakeRequest:
        raise TypeError("wake identity requires an exact request")
    receipt = request.chain.receipt
    wake = request.chain.wake_capability
    registration = request.chain.registration
    payload_digest = "sha256_" + sha256(
        request.render_identifiers_only_payload().encode("utf-8")
    ).hexdigest()
    return RoleWakeAttemptIdentity(
        attempt_id=request.attempt_id,
        trigger=request.trigger,
        project_id=receipt.project_id,
        ticket_ref=receipt.ticket_reference,
        receipt_ref=receipt.receipt_id,
        receipt_digest=derive_ticket_receipt_digest(receipt),
        reviewer_ref=request.chain.reviewer_ref,
        reviewer_task_id=wake.reviewer_task_id,
        reviewer_thread_id=wake.reviewer_thread_id,
        host_id=wake.host_id,
        event_source_ref=registration.event_source_ref,
        subscription_id=registration.subscription_id,
        chain_digest=request.chain.chain_digest,
        payload_digest=payload_digest,
    )


class RoleWakeAttemptRecord(_StrictModel):
    identity: RoleWakeAttemptIdentity
    lifecycle: RoleWakeAttemptLifecycle
    delivery_reference: DeliveryReference | None = None

    @model_validator(mode="after")
    def delivery_matches_lifecycle(self) -> Self:
        accepted = self.lifecycle is RoleWakeAttemptLifecycle.HOST_ACCEPTED
        if accepted != (self.delivery_reference is not None):
            raise ValueError("only accepted wake attempts carry delivery identity")
        return self


class RoleWakeAttemptClaimRequest(_StrictModel):
    identity: RoleWakeAttemptIdentity


class RoleWakeAttemptClaimResult(_StrictModel):
    status: WakeAttemptClaimStatus
    record: RoleWakeAttemptRecord | None = None

    @model_validator(mode="after")
    def exact_claim_shape(self) -> Self:
        success = self.status in (
            WakeAttemptClaimStatus.CLAIMED,
            WakeAttemptClaimStatus.ALREADY_CLAIMED,
        )
        if success != (self.record is not None):
            raise ValueError("successful wake claims require one record")
        return self


class RoleWakeEffectResult(_StrictModel):
    status: RoleWakeEffectStatus
    delivery_reference: DeliveryReference | None = None

    @model_validator(mode="after")
    def exact_effect_shape(self) -> Self:
        accepted = self.status is RoleWakeEffectStatus.HOST_ACCEPTED
        if accepted != (self.delivery_reference is not None):
            raise ValueError("only accepted wake effects carry delivery identity")
        return self


class WakeAttemptReadStatus(str, Enum):
    """Finite outcomes of one wake-attempt read."""

    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class RoleWakeAttemptReadRequest(_StrictModel):
    """Ask whether a reviewer was really woken for one exact receipt.

    Keyed by the dispatch identity rather than the attempt id, because the
    caller proving a wake happened knows which ticket it is reviewing, not
    which attempt the runner minted for it.
    """

    project_id: ProjectId
    ticket_ref: OpaqueMetadataId
    receipt_ref: OpaqueMetadataId


class RoleWakeAttemptReadResult(_StrictModel):
    """Every recorded attempt for that receipt, newest state included."""

    status: WakeAttemptReadStatus
    records: tuple[RoleWakeAttemptRecord, ...] = ()

    @model_validator(mode="after")
    def exact_read_shape(self) -> Self:
        if self.status is WakeAttemptReadStatus.FOUND:
            if not self.records:
                raise ValueError("a found read must carry at least one record")
        elif self.records:
            raise ValueError("only a found read may carry records")
        return self


class RoleWakeAttemptSettleRequest(_StrictModel):
    identity: RoleWakeAttemptIdentity
    effect: RoleWakeEffectResult


class RoleWakeAttemptSettleResult(_StrictModel):
    status: WakeAttemptSettleStatus
    record: RoleWakeAttemptRecord | None = None

    @model_validator(mode="after")
    def exact_settlement_shape(self) -> Self:
        success = self.status in (
            WakeAttemptSettleStatus.SETTLED,
            WakeAttemptSettleStatus.ALREADY_SETTLED,
        )
        if success != (self.record is not None):
            raise ValueError("successful wake settlements require one record")
        return self


class RoleWakeCommand(_StrictModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=False,
        revalidate_instances="always",
    )

    attempt_id: WakeAttemptId
    reviewer_task_id: CodexTaskId
    reviewer_thread_id: CodexThreadId
    host_id: CodexHostId
    payload: str
    payload_digest: EvidenceDigest

    @model_validator(mode="after")
    def command_is_exact(self) -> Self:
        if self.reviewer_task_id != self.reviewer_thread_id:
            raise ValueError("wake command task and thread must match")
        expected = "sha256_" + sha256(self.payload.encode("utf-8")).hexdigest()
        if self.payload_digest != expected:
            raise ValueError("wake command digest must match its payload")
        return self


class RoleWakeResult(_StrictModel):
    status: RoleWakeStatus
    record: RoleWakeAttemptRecord | None = None

    @model_validator(mode="after")
    def exact_result_shape(self) -> Self:
        settled = self.status in (RoleWakeStatus.HOST_ACCEPTED, RoleWakeStatus.NO_EFFECT)
        uncertain = self.status is RoleWakeStatus.EFFECT_UNCERTAIN
        if settled:
            if self.record is None or self.record.lifecycle.value != self.status.value:
                raise ValueError("settled wake result requires matching record")
        elif uncertain:
            if self.record is not None and self.record.lifecycle is not RoleWakeAttemptLifecycle.EFFECT_UNCERTAIN:
                raise ValueError("uncertain wake may carry only uncertain record")
        elif self.record is not None:
            raise ValueError("pre-effect wake failure cannot carry a record")
        return self


def wake_request_from_git_decision(
    attempt_id: WakeAttemptId,
    chain: RoleWakeChainProof,
    decision: GitEventAdapterDecision,
) -> RoleWakeRequest | None:
    """Map only terminal/fault Git results to a reviewer wake request."""

    if decision.decision is GitEventAdapterDecisionKind.TERMINAL_HANDOFF_ACCEPTED:
        if decision.handoff is None or decision.registration is None:
            return None
        return RoleWakeRequest(
            attempt_id=attempt_id,
            chain=chain,
            trigger=RoleWakeTriggerKind.REVIEW_HANDOFF,
            observed_commit=decision.registration.last_observed_commit,
            handoff_id=decision.handoff.handoff_id,
            lease_id=None,
            fault_kind=None,
            review_instruction=None,
        )
    if decision.decision in (
        GitEventAdapterDecisionKind.INVALID_HANDOFF_FAULT,
        GitEventAdapterDecisionKind.STALE_BINDING_FAULT,
    ):
        if decision.fault is None:
            return None
        return RoleWakeRequest(
            attempt_id=attempt_id,
            chain=chain,
            trigger=RoleWakeTriggerKind.SUPERVISION_FAULT,
            observed_commit=decision.fault.observed_commit,
            handoff_id=None,
            lease_id=None,
            fault_kind=decision.fault.kind,
            review_instruction=None,
        )
    return None


__all__ = [
    "DeadlineCapabilityState",
    "MonotonicDeadlineCapabilityProof",
    "RoleWakeAttemptClaimRequest",
    "RoleWakeAttemptClaimResult",
    "RoleWakeAttemptIdentity",
    "RoleWakeAttemptLifecycle",
    "RoleWakeAttemptReadRequest",
    "RoleWakeAttemptReadResult",
    "RoleWakeAttemptRecord",
    "RoleWakeAttemptSettleRequest",
    "RoleWakeAttemptSettleResult",
    "RoleWakeCapabilityProof",
    "RoleWakeCapabilityState",
    "RoleWakeChainFailure",
    "RoleWakeChainPreflightRequest",
    "RoleWakeChainPreflightResult",
    "RoleWakeChainProof",
    "RoleWakeChainStatus",
    "RoleWakeCommand",
    "RoleWakeEffectResult",
    "RoleWakeEffectStatus",
    "RoleWakeRequest",
    "RoleWakeResult",
    "RoleWakeStatus",
    "RoleWakeTriggerKind",
    "WakeAttemptClaimStatus",
    "WakeAttemptReadStatus",
    "WakeAttemptSettleStatus",
    "derive_role_wake_attempt_identity",
    "preflight_role_wake_chain",
    "wake_request_from_git_decision",
]
