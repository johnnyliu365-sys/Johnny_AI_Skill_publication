"""Strict contracts for one-shot receipt-bound Codex thread dispatch."""

from __future__ import annotations

from enum import Enum
from hashlib import sha256
from typing import Self, TypeAlias

from pydantic import BaseModel, ConfigDict, model_validator

from .contracts import EvidenceDigest, OpaqueMetadataId, ProjectId
from .live_dispatch_contracts import ReceiptLifecycle, TicketReceipt
from .thread_host_contracts import (
    CodexHostId,
    CodexProjectId,
    CodexTaskId,
    CodexThreadHostBinding,
    CodexThreadId,
)


DispatchAttemptId: TypeAlias = OpaqueMetadataId
DeliveryReference: TypeAlias = OpaqueMetadataId
DispatchPayloadDigest: TypeAlias = EvidenceDigest


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
    )


class CodexThreadDispatchAction(str, Enum):
    """The sole host effect admitted by this module."""

    DELIVER_TICKET = "DELIVER_TICKET"


class CodexThreadDispatchLifecycle(str, Enum):
    """Durable states of one non-retryable dispatch attempt."""

    CLAIMED = "CLAIMED"
    HOST_ACCEPTED = "HOST_ACCEPTED"
    NO_EFFECT = "NO_EFFECT"
    EFFECT_UNCERTAIN = "EFFECT_UNCERTAIN"


class DispatchClaimStatus(str, Enum):
    """Finite compare-and-swap claim outcomes."""

    CLAIMED = "CLAIMED"
    ALREADY_CLAIMED = "ALREADY_CLAIMED"
    RECEIPT_UNAVAILABLE = "RECEIPT_UNAVAILABLE"
    ATTEMPT_CONFLICT = "ATTEMPT_CONFLICT"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class DispatchClaimFailure(str, Enum):
    """Finite claim failures."""

    RECEIPT_UNAVAILABLE = "RECEIPT_UNAVAILABLE"
    ATTEMPT_CONFLICT = "ATTEMPT_CONFLICT"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class DispatchSettlementStatus(str, Enum):
    """Finite durable settlement outcomes."""

    SETTLED = "SETTLED"
    ALREADY_SETTLED = "ALREADY_SETTLED"
    CLAIM_NOT_FOUND = "CLAIM_NOT_FOUND"
    CLAIM_MISMATCH = "CLAIM_MISMATCH"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class DispatchSettlementFailure(str, Enum):
    """Finite settlement failures."""

    CLAIM_NOT_FOUND = "CLAIM_NOT_FOUND"
    CLAIM_MISMATCH = "CLAIM_MISMATCH"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class CodexThreadDispatchEffectStatus(str, Enum):
    """Normalized result of exactly one host call."""

    HOST_ACCEPTED = "HOST_ACCEPTED"
    NO_EFFECT = "NO_EFFECT"
    EFFECT_UNCERTAIN = "EFFECT_UNCERTAIN"


class CodexThreadDispatchStatus(str, Enum):
    """Finite caller-visible dispatch outcomes."""

    HOST_ACCEPTED = "HOST_ACCEPTED"
    NO_EFFECT = "NO_EFFECT"
    EFFECT_UNCERTAIN = "EFFECT_UNCERTAIN"
    RECEIPT_UNAVAILABLE = "RECEIPT_UNAVAILABLE"
    ATTEMPT_CONFLICT = "ATTEMPT_CONFLICT"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class CodexThreadDispatchFailure(str, Enum):
    """Finite failures that carry no successful delivery claim."""

    EFFECT_UNCERTAIN = "EFFECT_UNCERTAIN"
    RECEIPT_UNAVAILABLE = "RECEIPT_UNAVAILABLE"
    ATTEMPT_CONFLICT = "ATTEMPT_CONFLICT"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


def derive_ticket_receipt_digest(receipt: TicketReceipt) -> EvidenceDigest:
    """Hash the exact canonical receipt without retaining its serialized bytes."""

    if type(receipt) is not TicketReceipt:
        raise TypeError("receipt digest requires the exact TicketReceipt")
    material = receipt.model_dump_json().encode("utf-8")
    return "sha256_" + sha256(material).hexdigest()


class CodexThreadDispatchRequest(_StrictModel):
    """One exact active receipt and verified host binding to deliver once."""

    attempt_id: DispatchAttemptId
    action: CodexThreadDispatchAction = CodexThreadDispatchAction.DELIVER_TICKET
    receipt: TicketReceipt
    binding: CodexThreadHostBinding

    @model_validator(mode="after")
    def receipt_matches_binding(self) -> Self:
        receipt = self.receipt
        target = self.binding.target
        if receipt.lifecycle is not ReceiptLifecycle.ACTIVE:
            raise ValueError("dispatch requires an active receipt")
        if (
            target.router_project_id != receipt.project_id
            or target.ticket_reference != receipt.ticket_reference
            or target.receipt_id != receipt.receipt_id
            or target.worktree_fingerprint != receipt.worktree_fingerprint
            or target.branch_fingerprint != receipt.branch_fingerprint
        ):
            raise ValueError("dispatch receipt and host binding must match exactly")
        return self

    def render_identifiers_only_payload(self) -> str:
        """Render the fixed host payload; no source, prompt history or path is included."""

        receipt = self.receipt
        target = self.binding.target
        values = (
            ("protocol", "CODEX_THREAD_DISPATCH_V1"),
            ("action", self.action.value),
            ("project_id", receipt.project_id),
            ("ticket_reference", receipt.ticket_reference),
            ("ticket_revision", receipt.ticket_revision),
            ("ticket_document_commit", receipt.ticket_document_commit),
            ("receipt_id", receipt.receipt_id),
            ("handoff_reference", receipt.handoff_reference),
            ("handoff_revision", receipt.handoff_revision),
            ("handoff_document_commit", receipt.handoff_document_commit),
            ("implementation_owner_id", receipt.implementation_owner_id),
            ("expected_return", receipt.expected_return),
            ("descriptor_binding", receipt.descriptor_binding),
            ("correlation_id", receipt.correlation_id),
            ("dispatch_question_id", receipt.dispatch_question_id),
            ("task_id", target.task_id),
            ("thread_id", target.thread_id),
            ("host_id", target.host_id),
            ("codex_project_id", target.codex_project_id),
            ("worktree_fingerprint", target.worktree_fingerprint),
            ("branch_fingerprint", target.branch_fingerprint),
        )
        return "\n".join(key + "=" + value for key, value in values) + "\n"


def derive_dispatch_payload_digest(request: CodexThreadDispatchRequest) -> EvidenceDigest:
    """Hash the exact identifiers-only payload used by the host call."""

    if type(request) is not CodexThreadDispatchRequest:
        raise TypeError("payload digest requires the exact dispatch request")
    return "sha256_" + sha256(
        request.render_identifiers_only_payload().encode("utf-8")
    ).hexdigest()


class CodexThreadDispatchClaimIdentity(_StrictModel):
    """Durable metadata identity of one non-retryable host attempt."""

    attempt_id: DispatchAttemptId
    action: CodexThreadDispatchAction
    project_id: ProjectId
    ticket_reference: OpaqueMetadataId
    receipt_id: OpaqueMetadataId
    receipt_digest: EvidenceDigest
    binding_digest: EvidenceDigest
    payload_digest: DispatchPayloadDigest
    correlation_id: OpaqueMetadataId
    task_id: CodexTaskId
    thread_id: CodexThreadId
    host_id: CodexHostId
    codex_project_id: CodexProjectId

    @model_validator(mode="after")
    def task_is_thread(self) -> Self:
        if self.task_id != self.thread_id:
            raise ValueError("dispatch task and thread identity must match")
        return self


def dispatch_claim_identity(
    request: CodexThreadDispatchRequest,
) -> CodexThreadDispatchClaimIdentity:
    """Project a validated request into metadata-only durable claim identity."""

    if type(request) is not CodexThreadDispatchRequest:
        raise TypeError("claim identity requires the exact dispatch request")
    receipt = request.receipt
    target = request.binding.target
    return CodexThreadDispatchClaimIdentity(
        attempt_id=request.attempt_id,
        action=request.action,
        project_id=receipt.project_id,
        ticket_reference=receipt.ticket_reference,
        receipt_id=receipt.receipt_id,
        receipt_digest=derive_ticket_receipt_digest(receipt),
        binding_digest=request.binding.binding_digest,
        payload_digest=derive_dispatch_payload_digest(request),
        correlation_id=receipt.correlation_id,
        task_id=target.task_id,
        thread_id=target.thread_id,
        host_id=target.host_id,
        codex_project_id=target.codex_project_id,
    )


class CodexThreadDispatchAttemptRecord(_StrictModel):
    """Durable claim and its terminal host-call classification."""

    identity: CodexThreadDispatchClaimIdentity
    lifecycle: CodexThreadDispatchLifecycle
    delivery_reference: DeliveryReference | None = None

    @model_validator(mode="after")
    def delivery_reference_matches_lifecycle(self) -> Self:
        if self.lifecycle is CodexThreadDispatchLifecycle.HOST_ACCEPTED:
            if self.delivery_reference is None:
                raise ValueError("accepted host call requires one delivery reference")
            return self
        if self.delivery_reference is not None:
            raise ValueError("only accepted host calls may carry a delivery reference")
        return self


class CodexThreadDispatchClaimRequest(_StrictModel):
    """CAS request that must be committed before the host effect."""

    identity: CodexThreadDispatchClaimIdentity


class CodexThreadDispatchClaimResult(_StrictModel):
    """Exactly one claimed/existing record or one finite failure."""

    status: DispatchClaimStatus
    record: CodexThreadDispatchAttemptRecord | None = None
    failure: DispatchClaimFailure | None = None

    @model_validator(mode="after")
    def exact_record_or_failure(self) -> Self:
        success = self.status in (
            DispatchClaimStatus.CLAIMED,
            DispatchClaimStatus.ALREADY_CLAIMED,
        )
        if success and (self.record is None or self.failure is not None):
            raise ValueError("successful claim requires one record and no failure")
        if not success and (self.record is not None or self.failure is None):
            raise ValueError("failed claim requires one failure and no record")
        if not success and self.failure is not None and self.status.value != self.failure.value:
            raise ValueError("claim status and failure must match")
        return self


class CodexThreadDispatchEffectResult(_StrictModel):
    """Typed normalization of one and only one host invocation."""

    status: CodexThreadDispatchEffectStatus
    delivery_reference: DeliveryReference | None = None

    @model_validator(mode="after")
    def exact_delivery_reference(self) -> Self:
        if self.status is CodexThreadDispatchEffectStatus.HOST_ACCEPTED:
            if self.delivery_reference is None:
                raise ValueError("accepted effect requires a delivery reference")
            return self
        if self.delivery_reference is not None:
            raise ValueError("non-accepted effect cannot carry a delivery reference")
        return self


class CodexThreadDispatchSettlementRequest(_StrictModel):
    """Terminal classification of an exact previously claimed attempt."""

    identity: CodexThreadDispatchClaimIdentity
    effect: CodexThreadDispatchEffectResult


class CodexThreadDispatchSettlementResult(_StrictModel):
    """Exactly one settled record or one finite settlement failure."""

    status: DispatchSettlementStatus
    record: CodexThreadDispatchAttemptRecord | None = None
    failure: DispatchSettlementFailure | None = None

    @model_validator(mode="after")
    def exact_record_or_failure(self) -> Self:
        success = self.status in (
            DispatchSettlementStatus.SETTLED,
            DispatchSettlementStatus.ALREADY_SETTLED,
        )
        if success and (self.record is None or self.failure is not None):
            raise ValueError("successful settlement requires one record and no failure")
        if not success and (self.record is not None or self.failure is None):
            raise ValueError("failed settlement requires one failure and no record")
        if not success and self.failure is not None and self.status.value != self.failure.value:
            raise ValueError("settlement status and failure must match")
        return self


class CodexThreadDispatchCommand(_StrictModel):
    """Ephemeral exact arguments for one send_message_to_thread host call."""

    attempt_id: DispatchAttemptId
    thread_id: CodexThreadId
    host_id: CodexHostId
    prompt: str
    payload_digest: DispatchPayloadDigest

    @model_validator(mode="after")
    def payload_digest_is_exact(self) -> Self:
        expected = "sha256_" + sha256(self.prompt.encode("utf-8")).hexdigest()
        if self.payload_digest != expected:
            raise ValueError("dispatch command digest must match its exact prompt")
        return self


class CodexThreadDispatchResult(_StrictModel):
    """Finite caller-visible result; only HOST_ACCEPTED is a delivery claim."""

    status: CodexThreadDispatchStatus
    record: CodexThreadDispatchAttemptRecord | None = None
    failure: CodexThreadDispatchFailure | None = None

    @model_validator(mode="after")
    def exact_result_shape(self) -> Self:
        if self.status in (
            CodexThreadDispatchStatus.HOST_ACCEPTED,
            CodexThreadDispatchStatus.NO_EFFECT,
        ):
            if self.record is None or self.failure is not None:
                raise ValueError("settled dispatch requires one record and no failure")
            if self.record.lifecycle.value != self.status.value:
                raise ValueError("dispatch status must match the stored lifecycle")
            return self
        if self.status is CodexThreadDispatchStatus.EFFECT_UNCERTAIN:
            if self.failure is not CodexThreadDispatchFailure.EFFECT_UNCERTAIN:
                raise ValueError("uncertain dispatch requires its exact failure")
            return self
        if self.record is not None or self.failure is None:
            raise ValueError("failed dispatch requires one failure and no record")
        if self.status.value != self.failure.value:
            raise ValueError("dispatch status and failure must match")
        return self


__all__ = [
    "CodexThreadDispatchAction",
    "CodexThreadDispatchAttemptRecord",
    "CodexThreadDispatchClaimIdentity",
    "CodexThreadDispatchClaimRequest",
    "CodexThreadDispatchClaimResult",
    "CodexThreadDispatchCommand",
    "CodexThreadDispatchEffectResult",
    "CodexThreadDispatchEffectStatus",
    "CodexThreadDispatchFailure",
    "CodexThreadDispatchLifecycle",
    "CodexThreadDispatchRequest",
    "CodexThreadDispatchResult",
    "CodexThreadDispatchSettlementRequest",
    "CodexThreadDispatchSettlementResult",
    "CodexThreadDispatchStatus",
    "DeliveryReference",
    "DispatchAttemptId",
    "DispatchClaimFailure",
    "DispatchClaimStatus",
    "DispatchSettlementFailure",
    "DispatchSettlementStatus",
    "dispatch_claim_identity",
    "derive_dispatch_payload_digest",
    "derive_ticket_receipt_digest",
]
