"""Windows durable checkpoint boundary for live-dispatch metadata."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import TracebackType
from typing import BinaryIO, Literal, Self
import os
import tempfile

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from library.workflow_router.contracts import ProjectId
from library.workflow_router.live_dispatch_contracts import (
    ApprovedArtifactLifecycle,
    ApprovedDispatchArtifactReadRequest,
    ApprovedDispatchArtifactReadResult,
    ApprovedDispatchArtifactRecord,
    ApprovedDispatchArtifactRegisterRequest,
    ApprovedDispatchArtifactRegisterResult,
    ArtifactReadFailure,
    ArtifactReadStatus,
    ArtifactRegistrationFailure,
    ArtifactRegistrationStatus,
    ReceiptId,
    ReceiptIssueFailure,
    ReceiptIssueStatus,
    ReceiptLifecycle,
    ReceiptReadFailure,
    ReceiptReadStatus,
    TicketReceipt,
    TicketReceiptIssueRequest,
    TicketReceiptIssueResult,
    TicketReceiptReadRequest,
    TicketReceiptReadResult,
    TicketReference,
)
from library.workflow_router.thread_dispatch_contracts import (
    CodexThreadDispatchAttemptRecord,
    CodexThreadDispatchClaimIdentity,
    CodexThreadDispatchClaimRequest,
    CodexThreadDispatchClaimResult,
    CodexThreadDispatchEffectStatus,
    CodexThreadDispatchLifecycle,
    CodexThreadDispatchSettlementRequest,
    CodexThreadDispatchSettlementResult,
    DispatchClaimFailure,
    DispatchClaimStatus,
    DispatchSettlementFailure,
    DispatchSettlementStatus,
    derive_ticket_receipt_digest,
)
from .file_lock import ExclusiveWindowsFileLock as _ExclusiveWindowsFileLock
from library.workflow_router.role_wake_contracts import (
    RoleWakeAttemptReadRequest,
    RoleWakeAttemptReadResult,
    WakeAttemptReadStatus,
    RoleWakeAttemptClaimRequest,
    RoleWakeAttemptClaimResult,
    RoleWakeAttemptIdentity,
    RoleWakeAttemptLifecycle,
    RoleWakeAttemptRecord,
    RoleWakeAttemptSettleRequest,
    RoleWakeAttemptSettleResult,
    WakeAttemptClaimStatus,
    WakeAttemptSettleStatus,
)


_SCHEMA_REVISION: Literal["live-dispatch-metadata-v1"] = "live-dispatch-metadata-v1"
_CHECKPOINT_NAME = "live-dispatch-metadata-v1.json"
_LOCK_NAME = "live-dispatch-metadata-v1.lock"
_TEMP_PREFIX = ".live-dispatch-metadata-v1-"

# The lifecycles that end a receipt's authority. `read_receipt` already
# reported both as CLOSED; naming the pair once means "terminal" has a single
# definition rather than one copy per call site, and the copies cannot drift.
_TERMINAL_RECEIPT_LIFECYCLES = (ReceiptLifecycle.CLOSED, ReceiptLifecycle.REVOKED)


class ReceiptRevokeStatus(str, Enum):
    """Finite outcomes of one receipt revocation."""

    REVOKED = "REVOKED"
    ALREADY_REVOKED = "ALREADY_REVOKED"
    NOT_FOUND = "NOT_FOUND"
    RECEIPT_MISMATCH = "RECEIPT_MISMATCH"
    NOT_REVOCABLE = "NOT_REVOCABLE"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class ReceiptRevokeFailure(str, Enum):
    """Finite reasons a revocation is refused, one name per refusal status."""

    NOT_FOUND = "NOT_FOUND"
    RECEIPT_MISMATCH = "RECEIPT_MISMATCH"
    NOT_REVOCABLE = "NOT_REVOCABLE"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class TicketReceiptRevokeRequest(BaseModel):
    """Which canonical receipt to end, named exactly.

    The receipt id is carried beside the (project, ticket) key for the reason
    a settlement carries its receipt: a request keyed only by the ticket would
    end whichever receipt happened to hold the key, so a stale request from a
    caller that has not seen the current books would silently retire somebody
    else's live authority.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
    )

    project_id: ProjectId
    ticket_reference: TicketReference
    receipt_id: ReceiptId


class TicketReceiptRevokeResult(BaseModel):
    """Exactly one ended receipt, or exactly one finite refusal."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
    )

    status: ReceiptRevokeStatus
    receipt: TicketReceipt | None = None
    failure: ReceiptRevokeFailure | None = None

    @model_validator(mode="after")
    def exact_revocation_shape(self) -> Self:
        ended = self.status in (
            ReceiptRevokeStatus.REVOKED,
            ReceiptRevokeStatus.ALREADY_REVOKED,
        )
        if ended and (self.receipt is None or self.failure is not None):
            raise ValueError("an ended receipt requires one receipt and no failure")
        if not ended and (self.receipt is not None or self.failure is None):
            raise ValueError("a refused revocation requires one failure and no receipt")
        if not ended and self.failure is not None and self.failure.value != self.status.value:
            raise ValueError("revocation status and failure must match")
        return self


@dataclass(frozen=True, slots=True)
class JohnnyMetadataRoot:
    """An installer-resolved, existing Johnny-owned metadata directory."""

    root: Path

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path):
            raise TypeError("metadata root must be a Path")
        if not self.root.is_absolute():
            raise ValueError("metadata root must be absolute")
        resolved = self.root.resolve(strict=True)
        if resolved != self.root or not resolved.is_dir():
            raise ValueError("metadata root must be an existing resolved directory")


class _Checkpoint(BaseModel):
    """Strict deterministic state persisted beneath one Johnny-owned root."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
    )

    schema_revision: Literal["live-dispatch-metadata-v1"] = _SCHEMA_REVISION
    generation: int = Field(ge=0)
    artifacts: tuple[ApprovedDispatchArtifactRecord, ...] = ()
    receipts: tuple[TicketReceipt, ...] = ()
    dispatch_attempts: tuple[CodexThreadDispatchAttemptRecord, ...] = ()
    wake_attempts: tuple[RoleWakeAttemptRecord, ...] = ()

    @model_validator(mode="after")
    def unique_authority_keys(self) -> Self:
        artifact_keys = tuple(_artifact_key(record) for record in self.artifacts)
        receipt_keys = tuple(_receipt_key(receipt) for receipt in self.receipts)
        attempt_ids = tuple(
            record.identity.attempt_id for record in self.dispatch_attempts
        )
        attempt_keys = tuple(
            _dispatch_attempt_key(record.identity) for record in self.dispatch_attempts
        )
        wake_attempt_ids = tuple(record.identity.attempt_id for record in self.wake_attempts)
        wake_attempt_keys = tuple(
            _wake_attempt_key(record.identity) for record in self.wake_attempts
        )
        if len(artifact_keys) != len(set(artifact_keys)):
            raise ValueError("checkpoint contains duplicate artifact identities")
        if len(receipt_keys) != len(set(receipt_keys)):
            raise ValueError("checkpoint contains duplicate receipt identities")
        if len(attempt_ids) != len(set(attempt_ids)):
            raise ValueError("checkpoint contains duplicate dispatch attempt IDs")
        if len(attempt_keys) != len(set(attempt_keys)):
            raise ValueError("checkpoint contains duplicate dispatch authorities")
        if len(wake_attempt_ids) != len(set(wake_attempt_ids)):
            raise ValueError("checkpoint contains duplicate wake attempt IDs")
        if len(wake_attempt_keys) != len(set(wake_attempt_keys)):
            raise ValueError("checkpoint contains duplicate wake authorities")
        return self

    @classmethod
    def empty(cls) -> _Checkpoint:
        return cls(generation=0)


def _artifact_key(record: ApprovedDispatchArtifactRecord) -> tuple[str, str, str, str]:
    return (
        record.project_id,
        record.ticket_reference,
        record.handoff_reference,
        record.implementation_owner_id,
    )


def _artifact_request_key(
    request: ApprovedDispatchArtifactReadRequest,
) -> tuple[str, str, str, str]:
    identity = request.identity
    return (
        identity.project_id,
        identity.ticket_reference,
        identity.handoff_reference,
        identity.implementation_owner_id,
    )


def _receipt_key(receipt: TicketReceipt) -> tuple[str, str]:
    return (receipt.project_id, receipt.ticket_reference)


def _receipt_request_key(request: TicketReceiptReadRequest) -> tuple[str, str]:
    return (request.project_id, request.ticket_reference)


def _dispatch_attempt_key(
    identity: CodexThreadDispatchClaimIdentity,
) -> tuple[str, str, str]:
    return (
        identity.project_id,
        identity.ticket_reference,
        identity.receipt_id,
    )


def _wake_attempt_key(
    identity: RoleWakeAttemptIdentity,
) -> tuple[str, str, str, str, str]:
    return (
        identity.project_id,
        identity.ticket_ref,
        identity.receipt_ref,
        identity.trigger.value,
        identity.payload_digest,
    )


def _receipt_from_request(request: TicketReceiptIssueRequest) -> TicketReceipt:
    identity = request.artifact_identity
    return TicketReceipt(
        project_id=identity.project_id,
        receipt_id=request.receipt_id,
        ticket_reference=identity.ticket_reference,
        ticket_revision=request.ticket_revision,
        ticket_digest=request.ticket_digest,
        ticket_document_commit=request.ticket_document_commit,
        handoff_reference=identity.handoff_reference,
        handoff_revision=request.handoff_revision,
        handoff_digest=request.handoff_digest,
        handoff_document_commit=request.handoff_document_commit,
        baseline_commit=request.baseline_commit,
        implementation_owner_id=identity.implementation_owner_id,
        expected_return=request.expected_return,
        descriptor_binding=request.descriptor_binding,
        correlation_id=request.correlation_id,
        dispatch_question_id=request.dispatch_question_id,
        worktree_fingerprint=request.worktree_fingerprint,
        branch_fingerprint=request.branch_fingerprint,
    )


def _receipt_with_lifecycle(
    receipt: TicketReceipt, lifecycle: ReceiptLifecycle
) -> TicketReceipt:
    """Rebuild one receipt at a new lifecycle, field for field.

    Written out rather than copied through a model helper so that adding a
    field to `TicketReceipt` breaks this function loudly instead of letting a
    silently dropped field travel into the checkpoint. The router's own
    `execution_replacement._replace_receipt_lifecycle` is the precedent.
    """

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


def _storage_register_failure() -> ApprovedDispatchArtifactRegisterResult:
    return ApprovedDispatchArtifactRegisterResult(
        status=ArtifactRegistrationStatus.STORAGE_UNAVAILABLE,
        failure=ArtifactRegistrationFailure.STORAGE_UNAVAILABLE,
    )


def _storage_artifact_read_failure() -> ApprovedDispatchArtifactReadResult:
    return ApprovedDispatchArtifactReadResult(
        status=ArtifactReadStatus.STORAGE_UNAVAILABLE,
        failure=ArtifactReadFailure.STORAGE_UNAVAILABLE,
    )


def _storage_issue_failure() -> TicketReceiptIssueResult:
    return TicketReceiptIssueResult(
        status=ReceiptIssueStatus.STORAGE_UNAVAILABLE,
        failure=ReceiptIssueFailure.STORAGE_UNAVAILABLE,
    )


def _storage_revoke_failure() -> TicketReceiptRevokeResult:
    return TicketReceiptRevokeResult(
        status=ReceiptRevokeStatus.STORAGE_UNAVAILABLE,
        failure=ReceiptRevokeFailure.STORAGE_UNAVAILABLE,
    )


def _storage_receipt_read_failure() -> TicketReceiptReadResult:
    return TicketReceiptReadResult(
        status=ReceiptReadStatus.STORAGE_UNAVAILABLE,
        failure=ReceiptReadFailure.STORAGE_UNAVAILABLE,
    )


def _storage_dispatch_claim_failure() -> CodexThreadDispatchClaimResult:
    return CodexThreadDispatchClaimResult(
        status=DispatchClaimStatus.STORAGE_UNAVAILABLE,
        failure=DispatchClaimFailure.STORAGE_UNAVAILABLE,
    )


def _storage_dispatch_settlement_failure() -> CodexThreadDispatchSettlementResult:
    return CodexThreadDispatchSettlementResult(
        status=DispatchSettlementStatus.STORAGE_UNAVAILABLE,
        failure=DispatchSettlementFailure.STORAGE_UNAVAILABLE,
    )


def _storage_wake_claim_failure() -> RoleWakeAttemptClaimResult:
    return RoleWakeAttemptClaimResult(status=WakeAttemptClaimStatus.STORAGE_UNAVAILABLE)


def _storage_wake_settlement_failure() -> RoleWakeAttemptSettleResult:
    return RoleWakeAttemptSettleResult(status=WakeAttemptSettleStatus.STORAGE_UNAVAILABLE)


class LiveDispatchMetadataBoundary:
    """Durable registry and receipt CAS boundary over one atomic checkpoint."""

    def __init__(self, metadata_root: JohnnyMetadataRoot) -> None:
        if type(metadata_root) is not JohnnyMetadataRoot:
            raise TypeError("boundary requires JohnnyMetadataRoot")
        self._checkpoint_path = metadata_root.root / _CHECKPOINT_NAME
        self._lock_path = metadata_root.root / _LOCK_NAME

    def _load_checkpoint(self) -> _Checkpoint:
        if not self._checkpoint_path.exists():
            return _Checkpoint.empty()
        payload = self._checkpoint_path.read_bytes()
        return _Checkpoint.model_validate_json(payload, strict=True)

    def _commit_checkpoint(self, checkpoint: _Checkpoint) -> None:
        payload = checkpoint.model_dump_json().encode("utf-8") + b"\n"
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=_TEMP_PREFIX,
            suffix=".tmp",
            dir=self._checkpoint_path.parent,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as temporary:
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self._checkpoint_path)
        finally:
            temporary_path.unlink(missing_ok=True)

    def register_artifact(
        self,
        request: ApprovedDispatchArtifactRegisterRequest,
    ) -> ApprovedDispatchArtifactRegisterResult:
        if type(request) is not ApprovedDispatchArtifactRegisterRequest:
            return _storage_register_failure()
        try:
            with _ExclusiveWindowsFileLock(self._lock_path):
                checkpoint = self._load_checkpoint()
                key = _artifact_key(request.artifact)
                existing = next(
                    (record for record in checkpoint.artifacts if _artifact_key(record) == key),
                    None,
                )
                if existing is not None:
                    if existing == request.artifact:
                        return ApprovedDispatchArtifactRegisterResult(
                            status=ArtifactRegistrationStatus.ALREADY_REGISTERED,
                            record=existing,
                        )
                    return ApprovedDispatchArtifactRegisterResult(
                        status=ArtifactRegistrationStatus.IDENTITY_CONFLICT,
                        failure=ArtifactRegistrationFailure.IDENTITY_CONFLICT,
                    )
                artifacts = tuple(
                    sorted(
                        (*checkpoint.artifacts, request.artifact),
                        key=_artifact_key,
                    )
                )
                updated = _Checkpoint(
                    schema_revision=checkpoint.schema_revision,
                    generation=checkpoint.generation + 1,
                    artifacts=artifacts,
                    receipts=checkpoint.receipts,
                    dispatch_attempts=checkpoint.dispatch_attempts,
                    wake_attempts=checkpoint.wake_attempts,
                )
                self._commit_checkpoint(updated)
                return ApprovedDispatchArtifactRegisterResult(
                    status=ArtifactRegistrationStatus.REGISTERED,
                    record=request.artifact,
                )
        except (OSError, UnicodeError, ValidationError):
            return _storage_register_failure()

    def read_artifact(
        self,
        request: ApprovedDispatchArtifactReadRequest,
    ) -> ApprovedDispatchArtifactReadResult:
        if type(request) is not ApprovedDispatchArtifactReadRequest:
            return _storage_artifact_read_failure()
        try:
            with _ExclusiveWindowsFileLock(self._lock_path):
                checkpoint = self._load_checkpoint()
                key = _artifact_request_key(request)
                record = next(
                    (item for item in checkpoint.artifacts if _artifact_key(item) == key),
                    None,
                )
                if record is None:
                    return ApprovedDispatchArtifactReadResult(
                        status=ArtifactReadStatus.NOT_FOUND,
                        failure=ArtifactReadFailure.NOT_FOUND,
                    )
                if record.lifecycle is ApprovedArtifactLifecycle.CLOSED:
                    return ApprovedDispatchArtifactReadResult(
                        status=ArtifactReadStatus.CLOSED,
                        failure=ArtifactReadFailure.CLOSED,
                    )
                if (
                    record.ticket_revision != request.ticket_revision
                    or record.handoff_revision != request.handoff_revision
                ):
                    return ApprovedDispatchArtifactReadResult(
                        status=ArtifactReadStatus.STALE_REVISION,
                        failure=ArtifactReadFailure.STALE_REVISION,
                    )
                return ApprovedDispatchArtifactReadResult(
                    status=ArtifactReadStatus.FOUND,
                    record=record,
                )
        except (OSError, UnicodeError, ValidationError):
            return _storage_artifact_read_failure()

    def issue_receipt(self, request: TicketReceiptIssueRequest) -> TicketReceiptIssueResult:
        if type(request) is not TicketReceiptIssueRequest:
            return _storage_issue_failure()
        try:
            with _ExclusiveWindowsFileLock(self._lock_path):
                checkpoint = self._load_checkpoint()
                identity = request.artifact_identity
                artifact_key = (
                    identity.project_id,
                    identity.ticket_reference,
                    identity.handoff_reference,
                    identity.implementation_owner_id,
                )
                artifact = next(
                    (
                        record
                        for record in checkpoint.artifacts
                        if _artifact_key(record) == artifact_key
                    ),
                    None,
                )
                if artifact is None or artifact.lifecycle is ApprovedArtifactLifecycle.CLOSED:
                    return TicketReceiptIssueResult(
                        status=ReceiptIssueStatus.ARTIFACT_NOT_APPROVED,
                        failure=ReceiptIssueFailure.ARTIFACT_NOT_APPROVED,
                    )
                if (
                    artifact.ticket_revision != request.ticket_revision
                    or artifact.ticket_digest != request.ticket_digest
                    or artifact.ticket_document_commit != request.ticket_document_commit
                    or artifact.handoff_revision != request.handoff_revision
                    or artifact.handoff_digest != request.handoff_digest
                    or artifact.handoff_document_commit != request.handoff_document_commit
                    or artifact.baseline_commit != request.baseline_commit
                    or artifact.expected_return != request.expected_return
                    or artifact.descriptor_binding != request.descriptor_binding
                ):
                    return TicketReceiptIssueResult(
                        status=ReceiptIssueStatus.PENDING_DESCRIPTOR_MISMATCH,
                        failure=ReceiptIssueFailure.PENDING_DESCRIPTOR_MISMATCH,
                    )
                candidate = _receipt_from_request(request)
                receipt_key = _receipt_key(candidate)
                existing = next(
                    (receipt for receipt in checkpoint.receipts if _receipt_key(receipt) == receipt_key),
                    None,
                )
                if existing is not None:
                    if existing.lifecycle not in _TERMINAL_RECEIPT_LIFECYCLES:
                        # A live receipt still holds the key: identical repeats
                        # converge, everything else conflicts, exactly as before.
                        if existing == candidate:
                            return TicketReceiptIssueResult(
                                status=ReceiptIssueStatus.ALREADY_ISSUED,
                                receipt=existing,
                            )
                        return TicketReceiptIssueResult(
                            status=ReceiptIssueStatus.RECEIPT_CONFLICT,
                            failure=ReceiptIssueFailure.RECEIPT_CONFLICT,
                        )
                    # A terminal receipt has no authority left to defend, so it
                    # stops holding (project, ticket) and a successor may be
                    # issued. Its own id, though, is spent: reissuing it would
                    # undo a revocation by replay, and the router's replacement
                    # policy already requires a successor to differ from the
                    # receipt it replaces.
                    if existing.receipt_id == candidate.receipt_id:
                        return TicketReceiptIssueResult(
                            status=ReceiptIssueStatus.RECEIPT_CONFLICT,
                            failure=ReceiptIssueFailure.RECEIPT_CONFLICT,
                        )
                retained = tuple(
                    receipt
                    for receipt in checkpoint.receipts
                    if _receipt_key(receipt) != receipt_key
                )
                receipts = tuple(
                    sorted(
                        (*retained, candidate),
                        key=_receipt_key,
                    )
                )
                updated = _Checkpoint(
                    schema_revision=checkpoint.schema_revision,
                    generation=checkpoint.generation + 1,
                    artifacts=checkpoint.artifacts,
                    receipts=receipts,
                    dispatch_attempts=checkpoint.dispatch_attempts,
                    wake_attempts=checkpoint.wake_attempts,
                )
                self._commit_checkpoint(updated)
                return TicketReceiptIssueResult(
                    status=ReceiptIssueStatus.ISSUED,
                    receipt=candidate,
                )
        except (OSError, UnicodeError, ValidationError):
            return _storage_issue_failure()

    def read_receipt(self, request: TicketReceiptReadRequest) -> TicketReceiptReadResult:
        if type(request) is not TicketReceiptReadRequest:
            return _storage_receipt_read_failure()
        try:
            with _ExclusiveWindowsFileLock(self._lock_path):
                checkpoint = self._load_checkpoint()
                key = _receipt_request_key(request)
                receipt = next(
                    (item for item in checkpoint.receipts if _receipt_key(item) == key),
                    None,
                )
                if receipt is None:
                    return TicketReceiptReadResult(
                        status=ReceiptReadStatus.NOT_FOUND,
                        failure=ReceiptReadFailure.NOT_FOUND,
                    )
                if receipt.ticket_revision != request.ticket_revision:
                    return TicketReceiptReadResult(
                        status=ReceiptReadStatus.STALE_REVISION,
                        failure=ReceiptReadFailure.STALE_REVISION,
                    )
                if receipt.lifecycle in _TERMINAL_RECEIPT_LIFECYCLES:
                    return TicketReceiptReadResult(
                        status=ReceiptReadStatus.CLOSED,
                        failure=ReceiptReadFailure.CLOSED,
                    )
                return TicketReceiptReadResult(
                    status=ReceiptReadStatus.FOUND,
                    receipt=receipt,
                )
        except (OSError, UnicodeError, ValidationError):
            return _storage_receipt_read_failure()

    def revoke_receipt(
        self, request: TicketReceiptRevokeRequest
    ) -> TicketReceiptRevokeResult:
        """End one exact canonical receipt, releasing its (project, ticket) key.

        Until this method existed the terminal lifecycles were read-only: every
        reader knew what `REVOKED` meant and no writer could ever produce it,
        so one failed spawn ended a ticket's life on the wired path for good.
        The compensation closed the books correctly and nobody could reopen
        them.

        This is the CAS half of reopening them, and only the CAS half. It
        proves nothing about whether reopening is *allowed* — that the claim
        came back, that the caller may dispatch at all — and it deliberately
        cannot: the assignment ledger and the owner grant are not readable from
        here. `dispatch_authority.revoke_dispatch_receipt` is the entry that
        holds those proofs, and it is the only caller that should exist.

        Ending an already-ended receipt converges rather than refusing, so a
        revocation interrupted before its successor was issued can be resumed
        by repeating it. Every other disagreement with the books — no receipt,
        a different receipt on the key, a lifecycle with no route to REVOKED —
        refuses under its own name and writes nothing.
        """

        if type(request) is not TicketReceiptRevokeRequest:
            return _storage_revoke_failure()
        try:
            with _ExclusiveWindowsFileLock(self._lock_path):
                checkpoint = self._load_checkpoint()
                key = (request.project_id, request.ticket_reference)
                existing = next(
                    (
                        receipt
                        for receipt in checkpoint.receipts
                        if _receipt_key(receipt) == key
                    ),
                    None,
                )
                if existing is None:
                    return TicketReceiptRevokeResult(
                        status=ReceiptRevokeStatus.NOT_FOUND,
                        failure=ReceiptRevokeFailure.NOT_FOUND,
                    )
                if existing.receipt_id != request.receipt_id:
                    return TicketReceiptRevokeResult(
                        status=ReceiptRevokeStatus.RECEIPT_MISMATCH,
                        failure=ReceiptRevokeFailure.RECEIPT_MISMATCH,
                    )
                if existing.lifecycle is ReceiptLifecycle.REVOKED:
                    return TicketReceiptRevokeResult(
                        status=ReceiptRevokeStatus.ALREADY_REVOKED,
                        receipt=existing,
                    )
                if existing.lifecycle is not ReceiptLifecycle.ACTIVE:
                    return TicketReceiptRevokeResult(
                        status=ReceiptRevokeStatus.NOT_REVOCABLE,
                        failure=ReceiptRevokeFailure.NOT_REVOCABLE,
                    )
                revoked = _receipt_with_lifecycle(existing, ReceiptLifecycle.REVOKED)
                receipts = tuple(
                    revoked if _receipt_key(receipt) == key else receipt
                    for receipt in checkpoint.receipts
                )
                updated = _Checkpoint(
                    schema_revision=checkpoint.schema_revision,
                    generation=checkpoint.generation + 1,
                    artifacts=checkpoint.artifacts,
                    receipts=receipts,
                    dispatch_attempts=checkpoint.dispatch_attempts,
                    wake_attempts=checkpoint.wake_attempts,
                )
                self._commit_checkpoint(updated)
                return TicketReceiptRevokeResult(
                    status=ReceiptRevokeStatus.REVOKED,
                    receipt=revoked,
                )
        except (OSError, UnicodeError, ValidationError):
            return _storage_revoke_failure()

    def claim_dispatch_attempt(
        self,
        request: CodexThreadDispatchClaimRequest,
    ) -> CodexThreadDispatchClaimResult:
        """Durably claim one exact host attempt before any external effect."""

        if type(request) is not CodexThreadDispatchClaimRequest:
            return _storage_dispatch_claim_failure()
        try:
            with _ExclusiveWindowsFileLock(self._lock_path):
                checkpoint = self._load_checkpoint()
                identity = request.identity
                canonical_receipt = next(
                    (
                        receipt
                        for receipt in checkpoint.receipts
                        if receipt.project_id == identity.project_id
                        and receipt.ticket_reference == identity.ticket_reference
                    ),
                    None,
                )
                if (
                    canonical_receipt is None
                    or canonical_receipt.lifecycle is not ReceiptLifecycle.ACTIVE
                    or canonical_receipt.receipt_id != identity.receipt_id
                    or derive_ticket_receipt_digest(canonical_receipt)
                    != identity.receipt_digest
                ):
                    return CodexThreadDispatchClaimResult(
                        status=DispatchClaimStatus.RECEIPT_UNAVAILABLE,
                        failure=DispatchClaimFailure.RECEIPT_UNAVAILABLE,
                    )
                existing = next(
                    (
                        record
                        for record in checkpoint.dispatch_attempts
                        if record.identity.attempt_id == identity.attempt_id
                        or _dispatch_attempt_key(record.identity)
                        == _dispatch_attempt_key(identity)
                    ),
                    None,
                )
                if existing is not None:
                    if existing.identity == identity:
                        return CodexThreadDispatchClaimResult(
                            status=DispatchClaimStatus.ALREADY_CLAIMED,
                            record=existing,
                        )
                    return CodexThreadDispatchClaimResult(
                        status=DispatchClaimStatus.ATTEMPT_CONFLICT,
                        failure=DispatchClaimFailure.ATTEMPT_CONFLICT,
                    )
                candidate = CodexThreadDispatchAttemptRecord(
                    identity=identity,
                    lifecycle=CodexThreadDispatchLifecycle.CLAIMED,
                )
                attempts = tuple(
                    sorted(
                        (*checkpoint.dispatch_attempts, candidate),
                        key=lambda record: record.identity.attempt_id,
                    )
                )
                updated = _Checkpoint(
                    schema_revision=checkpoint.schema_revision,
                    generation=checkpoint.generation + 1,
                    artifacts=checkpoint.artifacts,
                    receipts=checkpoint.receipts,
                    dispatch_attempts=attempts,
                    wake_attempts=checkpoint.wake_attempts,
                )
                self._commit_checkpoint(updated)
                return CodexThreadDispatchClaimResult(
                    status=DispatchClaimStatus.CLAIMED,
                    record=candidate,
                )
        except (OSError, UnicodeError, ValidationError):
            return _storage_dispatch_claim_failure()

    def settle_dispatch_attempt(
        self,
        request: CodexThreadDispatchSettlementRequest,
    ) -> CodexThreadDispatchSettlementResult:
        """Settle only the exact previously claimed attempt."""

        if type(request) is not CodexThreadDispatchSettlementRequest:
            return _storage_dispatch_settlement_failure()
        try:
            with _ExclusiveWindowsFileLock(self._lock_path):
                checkpoint = self._load_checkpoint()
                existing = next(
                    (
                        record
                        for record in checkpoint.dispatch_attempts
                        if record.identity.attempt_id == request.identity.attempt_id
                    ),
                    None,
                )
                if existing is None:
                    return CodexThreadDispatchSettlementResult(
                        status=DispatchSettlementStatus.CLAIM_NOT_FOUND,
                        failure=DispatchSettlementFailure.CLAIM_NOT_FOUND,
                    )
                if existing.identity != request.identity:
                    return CodexThreadDispatchSettlementResult(
                        status=DispatchSettlementStatus.CLAIM_MISMATCH,
                        failure=DispatchSettlementFailure.CLAIM_MISMATCH,
                    )
                lifecycle = CodexThreadDispatchLifecycle(request.effect.status.value)
                candidate = CodexThreadDispatchAttemptRecord(
                    identity=existing.identity,
                    lifecycle=lifecycle,
                    delivery_reference=request.effect.delivery_reference,
                )
                if existing.lifecycle is not CodexThreadDispatchLifecycle.CLAIMED:
                    if existing == candidate:
                        return CodexThreadDispatchSettlementResult(
                            status=DispatchSettlementStatus.ALREADY_SETTLED,
                            record=existing,
                        )
                    return CodexThreadDispatchSettlementResult(
                        status=DispatchSettlementStatus.CLAIM_MISMATCH,
                        failure=DispatchSettlementFailure.CLAIM_MISMATCH,
                    )
                attempts = tuple(
                    candidate if record.identity == existing.identity else record
                    for record in checkpoint.dispatch_attempts
                )
                updated = _Checkpoint(
                    schema_revision=checkpoint.schema_revision,
                    generation=checkpoint.generation + 1,
                    artifacts=checkpoint.artifacts,
                    receipts=checkpoint.receipts,
                    dispatch_attempts=attempts,
                    wake_attempts=checkpoint.wake_attempts,
                )
                self._commit_checkpoint(updated)
                return CodexThreadDispatchSettlementResult(
                    status=DispatchSettlementStatus.SETTLED,
                    record=candidate,
                )
        except (OSError, UnicodeError, ValidationError, ValueError):
            return _storage_dispatch_settlement_failure()

    def read_role_wake_attempt(
        self,
        request: RoleWakeAttemptReadRequest,
    ) -> RoleWakeAttemptReadResult:
        """Report every wake attempt recorded for one exact receipt.

        Read-only, added for the reviewer return path: a verdict may only be
        recorded for a review someone was actually woken to perform, and that
        fact has to be readable without granting the reader any power to
        claim or settle an attempt.
        """

        if type(request) is not RoleWakeAttemptReadRequest:
            return RoleWakeAttemptReadResult(
                status=WakeAttemptReadStatus.STORAGE_UNAVAILABLE
            )
        try:
            with _ExclusiveWindowsFileLock(self._lock_path):
                checkpoint = self._load_checkpoint()
                records = tuple(
                    record
                    for record in checkpoint.wake_attempts
                    if record.identity.project_id == request.project_id
                    and record.identity.ticket_ref == request.ticket_ref
                    and record.identity.receipt_ref == request.receipt_ref
                )
                if not records:
                    return RoleWakeAttemptReadResult(
                        status=WakeAttemptReadStatus.NOT_FOUND
                    )
                return RoleWakeAttemptReadResult(
                    status=WakeAttemptReadStatus.FOUND,
                    records=records,
                )
        except (OSError, UnicodeError, ValidationError):
            return RoleWakeAttemptReadResult(
                status=WakeAttemptReadStatus.STORAGE_UNAVAILABLE
            )

    def claim_role_wake_attempt(
        self,
        request: RoleWakeAttemptClaimRequest,
    ) -> RoleWakeAttemptClaimResult:
        """Durably claim one exact reviewer wake before the host effect."""

        if type(request) is not RoleWakeAttemptClaimRequest:
            return _storage_wake_claim_failure()
        try:
            with _ExclusiveWindowsFileLock(self._lock_path):
                checkpoint = self._load_checkpoint()
                identity = request.identity
                canonical_receipt = next(
                    (
                        receipt
                        for receipt in checkpoint.receipts
                        if receipt.project_id == identity.project_id
                        and receipt.ticket_reference == identity.ticket_ref
                    ),
                    None,
                )
                if (
                    canonical_receipt is None
                    or canonical_receipt.lifecycle is not ReceiptLifecycle.ACTIVE
                    or canonical_receipt.receipt_id != identity.receipt_ref
                    or derive_ticket_receipt_digest(canonical_receipt)
                    != identity.receipt_digest
                ):
                    return RoleWakeAttemptClaimResult(
                        status=WakeAttemptClaimStatus.ATTEMPT_CONFLICT
                    )
                existing = next(
                    (
                        record
                        for record in checkpoint.wake_attempts
                        if record.identity.attempt_id == identity.attempt_id
                        or _wake_attempt_key(record.identity) == _wake_attempt_key(identity)
                    ),
                    None,
                )
                if existing is not None:
                    if existing.identity == identity:
                        return RoleWakeAttemptClaimResult(
                            status=WakeAttemptClaimStatus.ALREADY_CLAIMED,
                            record=existing,
                        )
                    return RoleWakeAttemptClaimResult(
                        status=WakeAttemptClaimStatus.ATTEMPT_CONFLICT
                    )
                candidate = RoleWakeAttemptRecord(
                    identity=identity,
                    lifecycle=RoleWakeAttemptLifecycle.CLAIMED,
                )
                attempts = tuple(
                    sorted(
                        (*checkpoint.wake_attempts, candidate),
                        key=lambda record: record.identity.attempt_id,
                    )
                )
                updated = _Checkpoint(
                    schema_revision=checkpoint.schema_revision,
                    generation=checkpoint.generation + 1,
                    artifacts=checkpoint.artifacts,
                    receipts=checkpoint.receipts,
                    dispatch_attempts=checkpoint.dispatch_attempts,
                    wake_attempts=attempts,
                )
                self._commit_checkpoint(updated)
                return RoleWakeAttemptClaimResult(
                    status=WakeAttemptClaimStatus.CLAIMED,
                    record=candidate,
                )
        except (OSError, UnicodeError, ValidationError):
            return _storage_wake_claim_failure()

    def settle_role_wake_attempt(
        self,
        request: RoleWakeAttemptSettleRequest,
    ) -> RoleWakeAttemptSettleResult:
        """Settle only an exact already-claimed reviewer wake."""

        if type(request) is not RoleWakeAttemptSettleRequest:
            return _storage_wake_settlement_failure()
        try:
            with _ExclusiveWindowsFileLock(self._lock_path):
                checkpoint = self._load_checkpoint()
                existing = next(
                    (
                        record
                        for record in checkpoint.wake_attempts
                        if record.identity.attempt_id == request.identity.attempt_id
                    ),
                    None,
                )
                if existing is None or existing.identity != request.identity:
                    return RoleWakeAttemptSettleResult(
                        status=WakeAttemptSettleStatus.CLAIM_MISMATCH
                    )
                candidate = RoleWakeAttemptRecord(
                    identity=existing.identity,
                    lifecycle=RoleWakeAttemptLifecycle(request.effect.status.value),
                    delivery_reference=request.effect.delivery_reference,
                )
                if existing.lifecycle is not RoleWakeAttemptLifecycle.CLAIMED:
                    if existing == candidate:
                        return RoleWakeAttemptSettleResult(
                            status=WakeAttemptSettleStatus.ALREADY_SETTLED,
                            record=existing,
                        )
                    return RoleWakeAttemptSettleResult(
                        status=WakeAttemptSettleStatus.CLAIM_MISMATCH
                    )
                attempts = tuple(
                    candidate if record.identity == existing.identity else record
                    for record in checkpoint.wake_attempts
                )
                updated = _Checkpoint(
                    schema_revision=checkpoint.schema_revision,
                    generation=checkpoint.generation + 1,
                    artifacts=checkpoint.artifacts,
                    receipts=checkpoint.receipts,
                    dispatch_attempts=checkpoint.dispatch_attempts,
                    wake_attempts=attempts,
                )
                self._commit_checkpoint(updated)
                return RoleWakeAttemptSettleResult(
                    status=WakeAttemptSettleStatus.SETTLED,
                    record=candidate,
                )
        except (OSError, UnicodeError, ValidationError, ValueError):
            return _storage_wake_settlement_failure()


__all__ = [
    "JohnnyMetadataRoot",
    "LiveDispatchMetadataBoundary",
    "ReceiptRevokeFailure",
    "ReceiptRevokeStatus",
    "TicketReceiptRevokeRequest",
    "TicketReceiptRevokeResult",
]
