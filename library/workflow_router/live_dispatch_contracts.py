"""Strict metadata contracts for durable live-dispatch admission state."""

from __future__ import annotations

from enum import Enum
from typing import Self, TypeAlias

from pydantic import BaseModel, ConfigDict, model_validator

from .contracts import (
    BranchFingerprint,
    EvidenceDigest,
    OpaqueMetadataId,
    ProjectId,
    ReviewedCommitReference,
    RevisionDigest,
    TicketDispatchReceipt,
    WorktreeFingerprint,
)


class _StrictModel(BaseModel):
    """Immutable, strict, extra-free metadata crossing the live boundary."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
    )


TicketReference: TypeAlias = OpaqueMetadataId
TicketRevision: TypeAlias = RevisionDigest
ContentDigest: TypeAlias = EvidenceDigest
CommitId: TypeAlias = ReviewedCommitReference
HandoffReference: TypeAlias = OpaqueMetadataId
ReceiptId: TypeAlias = OpaqueMetadataId
RoleReference: TypeAlias = OpaqueMetadataId
ExpectedReturnReference: TypeAlias = OpaqueMetadataId
DescriptorBinding: TypeAlias = OpaqueMetadataId
CorrelationId: TypeAlias = OpaqueMetadataId
DispatchQuestionId: TypeAlias = OpaqueMetadataId


class ReceiptLifecycle(str, Enum):
    """The finite durable lifecycle of one canonical live receipt."""

    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    CLOSED = "CLOSED"
    QUARANTINED = "QUARANTINED"


class ApprovedArtifactLifecycle(str, Enum):
    """The finite lifecycle of a registered reviewed artifact."""

    REGISTERED = "REGISTERED"
    CLOSED = "CLOSED"


class ArtifactRegistrationStatus(str, Enum):
    """Finite registration outcomes."""

    REGISTERED = "REGISTERED"
    ALREADY_REGISTERED = "ALREADY_REGISTERED"
    IDENTITY_CONFLICT = "IDENTITY_CONFLICT"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class ArtifactRegistrationFailure(str, Enum):
    """Finite registration rejection reasons."""

    IDENTITY_CONFLICT = "IDENTITY_CONFLICT"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class ArtifactReadStatus(str, Enum):
    """Finite artifact lookup outcomes."""

    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    STALE_REVISION = "STALE_REVISION"
    CLOSED = "CLOSED"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class ArtifactReadFailure(str, Enum):
    """Finite artifact lookup rejection reasons."""

    NOT_FOUND = "NOT_FOUND"
    STALE_REVISION = "STALE_REVISION"
    CLOSED = "CLOSED"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class ReceiptIssueStatus(str, Enum):
    """Finite compare-and-swap receipt issuance outcomes."""

    ISSUED = "ISSUED"
    ALREADY_ISSUED = "ALREADY_ISSUED"
    ARTIFACT_NOT_APPROVED = "ARTIFACT_NOT_APPROVED"
    PENDING_DESCRIPTOR_MISMATCH = "PENDING_DESCRIPTOR_MISMATCH"
    RECEIPT_CONFLICT = "RECEIPT_CONFLICT"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class ReceiptIssueFailure(str, Enum):
    """Finite receipt issuance rejection reasons."""

    ARTIFACT_NOT_APPROVED = "ARTIFACT_NOT_APPROVED"
    PENDING_DESCRIPTOR_MISMATCH = "PENDING_DESCRIPTOR_MISMATCH"
    RECEIPT_CONFLICT = "RECEIPT_CONFLICT"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class ReceiptReadStatus(str, Enum):
    """Finite canonical receipt lookup outcomes."""

    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    STALE_REVISION = "STALE_REVISION"
    CLOSED = "CLOSED"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class ReceiptReadFailure(str, Enum):
    """Finite canonical receipt lookup rejection reasons."""

    NOT_FOUND = "NOT_FOUND"
    STALE_REVISION = "STALE_REVISION"
    CLOSED = "CLOSED"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class ApprovedDispatchArtifactIdentity(_StrictModel):
    """The immutable registry key for one reviewed ticket/handoff artifact."""

    project_id: ProjectId
    ticket_reference: TicketReference
    handoff_reference: HandoffReference
    implementation_owner_id: RoleReference


class ApprovedDispatchArtifactRecord(_StrictModel):
    """The complete approved artifact identity persisted by the live registry."""

    project_id: ProjectId
    ticket_reference: TicketReference
    ticket_revision: TicketRevision
    ticket_digest: ContentDigest
    ticket_document_commit: CommitId
    handoff_reference: HandoffReference
    handoff_revision: TicketRevision
    handoff_digest: ContentDigest
    handoff_document_commit: CommitId
    baseline_commit: CommitId
    implementation_owner_id: RoleReference
    expected_return: ExpectedReturnReference
    descriptor_binding: DescriptorBinding
    lifecycle: ApprovedArtifactLifecycle = ApprovedArtifactLifecycle.REGISTERED

    @property
    def identity(self) -> ApprovedDispatchArtifactIdentity:
        """Return the exact registry identity without exposing raw source."""

        return ApprovedDispatchArtifactIdentity(
            project_id=self.project_id,
            ticket_reference=self.ticket_reference,
            handoff_reference=self.handoff_reference,
            implementation_owner_id=self.implementation_owner_id,
        )


class ApprovedDispatchArtifactRegisterRequest(_StrictModel):
    """Request to immutably register one reviewed artifact."""

    artifact: ApprovedDispatchArtifactRecord


class ApprovedDispatchArtifactReadRequest(_StrictModel):
    """Request to read an exact artifact identity and expected revisions."""

    identity: ApprovedDispatchArtifactIdentity
    ticket_revision: TicketRevision
    handoff_revision: TicketRevision


class ApprovedDispatchArtifactRegisterResult(_StrictModel):
    """Registration result with a record on success and one failure on rejection."""

    status: ArtifactRegistrationStatus
    record: ApprovedDispatchArtifactRecord | None = None
    failure: ArtifactRegistrationFailure | None = None

    @model_validator(mode="after")
    def exact_success_or_failure(self) -> Self:
        success = self.status in (
            ArtifactRegistrationStatus.REGISTERED,
            ArtifactRegistrationStatus.ALREADY_REGISTERED,
        )
        if success and (self.record is None or self.failure is not None):
            raise ValueError("successful registration requires one record and no failure")
        if not success and (self.record is not None or self.failure is None):
            raise ValueError("rejected registration requires one failure and no record")
        if not success and self.failure is not None and self.failure.value != self.status.value:
            raise ValueError("registration status and failure must match")
        return self


class ApprovedDispatchArtifactReadResult(_StrictModel):
    """Artifact lookup result with no record on finite rejection."""

    status: ArtifactReadStatus
    record: ApprovedDispatchArtifactRecord | None = None
    failure: ArtifactReadFailure | None = None

    @model_validator(mode="after")
    def exact_found_or_failure(self) -> Self:
        if self.status is ArtifactReadStatus.FOUND:
            if self.record is None or self.failure is not None:
                raise ValueError("found artifact requires one record and no failure")
            return self
        if self.record is not None or self.failure is None:
            raise ValueError("rejected artifact read requires one failure and no record")
        if self.failure.value != self.status.value:
            raise ValueError("artifact read status and failure must match")
        return self


class TicketReceiptIssueRequest(_StrictModel):
    """The pending descriptor and exact identity used for receipt CAS issuance."""

    artifact_identity: ApprovedDispatchArtifactIdentity
    ticket_revision: TicketRevision
    ticket_digest: ContentDigest
    ticket_document_commit: CommitId
    handoff_revision: TicketRevision
    handoff_digest: ContentDigest
    handoff_document_commit: CommitId
    baseline_commit: CommitId
    receipt_id: ReceiptId
    expected_return: ExpectedReturnReference
    descriptor_binding: DescriptorBinding
    correlation_id: CorrelationId
    dispatch_question_id: DispatchQuestionId
    worktree_fingerprint: WorktreeFingerprint
    branch_fingerprint: BranchFingerprint


class TicketReceiptReadRequest(_StrictModel):
    """Request to read the canonical project/ticket receipt."""

    project_id: ProjectId
    ticket_reference: TicketReference
    ticket_revision: TicketRevision


class TicketReceipt(_StrictModel):
    """The one durable live authority for a project/ticket dispatch."""

    project_id: ProjectId
    receipt_id: ReceiptId
    ticket_reference: TicketReference
    ticket_revision: TicketRevision
    ticket_digest: ContentDigest
    ticket_document_commit: CommitId
    handoff_reference: HandoffReference
    handoff_revision: TicketRevision
    handoff_digest: ContentDigest
    handoff_document_commit: CommitId
    baseline_commit: CommitId
    implementation_owner_id: RoleReference
    expected_return: ExpectedReturnReference
    descriptor_binding: DescriptorBinding
    correlation_id: CorrelationId
    dispatch_question_id: DispatchQuestionId
    worktree_fingerprint: WorktreeFingerprint
    branch_fingerprint: BranchFingerprint
    lifecycle: ReceiptLifecycle = ReceiptLifecycle.ACTIVE

    @property
    def artifact_identity(self) -> ApprovedDispatchArtifactIdentity:
        """Return the reviewed artifact key bound to this receipt."""

        return ApprovedDispatchArtifactIdentity(
            project_id=self.project_id,
            ticket_reference=self.ticket_reference,
            handoff_reference=self.handoff_reference,
            implementation_owner_id=self.implementation_owner_id,
        )


class TicketReceiptIssueResult(_StrictModel):
    """Receipt issuance result with exactly one success record or failure."""

    status: ReceiptIssueStatus
    receipt: TicketReceipt | None = None
    failure: ReceiptIssueFailure | None = None

    @model_validator(mode="after")
    def exact_issuance_shape(self) -> Self:
        success = self.status in (ReceiptIssueStatus.ISSUED, ReceiptIssueStatus.ALREADY_ISSUED)
        if success and (self.receipt is None or self.failure is not None):
            raise ValueError("successful issuance requires one receipt and no failure")
        if not success and (self.receipt is not None or self.failure is None):
            raise ValueError("rejected issuance requires one failure and no receipt")
        if not success and self.failure is not None and self.failure.value != self.status.value:
            raise ValueError("issuance status and failure must match")
        return self


class TicketReceiptReadResult(_StrictModel):
    """Canonical receipt lookup result with no receipt on finite rejection."""

    status: ReceiptReadStatus
    receipt: TicketReceipt | None = None
    failure: ReceiptReadFailure | None = None

    @model_validator(mode="after")
    def exact_read_shape(self) -> Self:
        if self.status is ReceiptReadStatus.FOUND:
            if self.receipt is None or self.failure is not None:
                raise ValueError("found receipt requires one receipt and no failure")
            return self
        if self.receipt is not None or self.failure is None:
            raise ValueError("rejected receipt read requires one failure and no receipt")
        if self.failure.value != self.status.value:
            raise ValueError("receipt read status and failure must match")
        return self


def to_legacy_ticket_dispatch_receipt(receipt: TicketReceipt) -> TicketDispatchReceipt:
    """Derive the old Router projection; it is never accepted as live authority."""

    if type(receipt) is not TicketReceipt:
        raise TypeError("legacy projection requires the exact live TicketReceipt")
    return TicketDispatchReceipt(
        ticket_reference=receipt.ticket_reference,
        implementation_owner_id=receipt.implementation_owner_id,
        handoff_reference=receipt.handoff_reference,
        expected_main_revision=receipt.ticket_revision,
        correlation_id=receipt.correlation_id,
        dispatch_question_id=receipt.dispatch_question_id,
        worktree_fingerprint=receipt.worktree_fingerprint,
        branch_fingerprint=receipt.branch_fingerprint,
    )


__all__ = [
    "ApprovedArtifactLifecycle",
    "ApprovedDispatchArtifactIdentity",
    "ApprovedDispatchArtifactReadRequest",
    "ApprovedDispatchArtifactReadResult",
    "ApprovedDispatchArtifactRecord",
    "ApprovedDispatchArtifactRegisterRequest",
    "ApprovedDispatchArtifactRegisterResult",
    "ArtifactReadFailure",
    "ArtifactReadStatus",
    "ArtifactRegistrationFailure",
    "ArtifactRegistrationStatus",
    "CommitId",
    "ContentDigest",
    "CorrelationId",
    "DescriptorBinding",
    "DispatchQuestionId",
    "ExpectedReturnReference",
    "HandoffReference",
    "ReceiptId",
    "ReceiptIssueFailure",
    "ReceiptIssueStatus",
    "ReceiptLifecycle",
    "ReceiptReadFailure",
    "ReceiptReadStatus",
    "RoleReference",
    "TicketReceipt",
    "TicketReceiptIssueRequest",
    "TicketReceiptIssueResult",
    "TicketReceiptReadRequest",
    "TicketReceiptReadResult",
    "TicketReference",
    "TicketRevision",
    "to_legacy_ticket_dispatch_receipt",
]
