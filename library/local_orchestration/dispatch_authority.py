"""Dispatch authority admission: the workstation entry that may issue receipts.

This is the phase-C landing the E8 closures deferred: receipt issuance stops
being a test fixture and becomes an explicit workstation entry with an
admission gate. The gate runs fail-closed and in a fixed order — owner grant,
strict request validation, worktree containment, artifact registration,
CAS issuance (the store's reviewed semantics untouched), and a readback that
proves the issued receipt is claimable through the same read path the runner
uses. Every outcome is journaled with the host principal.

**What the grant is, honestly.** The dispatch-authority grant is an owner
intent marker and audit anchor on a single-user machine. It is *not* a
cryptographic boundary: any code in the same process could create one. The
real principal separation — issuance as an OS-level process privilege —
remains this line's later work, exactly as CLOSURE-E8-02 recorded. What the
grant does buy today: no accidental issuance (the entry refuses until the
owner has explicitly said "this machine dispatches"), and every issuance
tied to a grant id and principal in the journal.

**The second entry: ending a receipt.** A receipt is one ticket's live
authority and the store keys it by (project, ticket), so while it stands no
other receipt for that ticket can be issued. That is the property that makes
dispatch exactly-once, and until P5 it was also a trap: when a spawn failed
and the claim was compensated, the receipt stayed `ACTIVE` with nothing left
to authorise, the terminal lifecycles had readers but no writer, and the
ticket was out of the wired path permanently. `revoke_dispatch_receipt` is
the way back — the same gate shape as issuance (grant, validation, proof,
store, journal) applied to ending a receipt instead of making one, and it
refuses unless the ledger shows the claim genuinely came home first.
"""

from __future__ import annotations

import getpass
import json
import os
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from library.workflow_router.contracts import ProjectId
from library.workflow_router.live_dispatch_contracts import (
    ApprovedDispatchArtifactRecord,
    ApprovedDispatchArtifactRegisterRequest,
    ArtifactRegistrationStatus,
    ReceiptId,
    ReceiptIssueStatus,
    TicketReceipt,
    TicketReceiptIssueRequest,
    TicketReference,
)

from .issuance_scoped_boundary import IssuanceScopedDispatchBoundary
from .johnny_root_layout import JohnnyRootLayout
from .live_dispatch_metadata_boundary import (
    JohnnyMetadataRoot as _JohnnyMetadataRoot,
    LiveDispatchMetadataBoundary as _LiveDispatchMetadataBoundary,
    ReceiptRevokeStatus as _ReceiptRevokeStatus,
    TicketReceiptRevokeRequest as _TicketReceiptRevokeRequest,
    TicketReceiptRevokeResult as _TicketReceiptRevokeResult,
)
from .runner_receipt_seeding import (
    ReceiptVerificationStatus,
    verify_receipt_claimable,
)
from .worker_assignment import (
    AssignmentLifecycle,
    AssignmentReadStatus,
    read_worker_assignments,
)
from .worktree_containment import (
    WorktreeContainmentStatus,
    verify_worktree_contained,
)

_GRANT_FILE_NAME = "dispatch-authority.json"
_JOURNAL_FILE_NAME = "dispatch-journal.jsonl"
_OPAQUE = r"^[a-z][a-z0-9-]{2,127}$"
_WORKTREE = r"^worktree-[a-z0-9]+-[0-9]{2}$"
_BRANCH = r"^branch-[a-z0-9]+-[0-9]{2}$"


class DispatchGrantStatus(str, Enum):
    """Finite outcomes of one grant creation."""

    GRANTED = "GRANTED"
    ALREADY_GRANTED = "ALREADY_GRANTED"
    REFUSED = "REFUSED"


class DispatchAdmissionStatus(str, Enum):
    """Finite outcomes of one dispatch admission."""

    DISPATCHED = "DISPATCHED"
    REFUSED = "REFUSED"


class DispatchAdmissionFailure(str, Enum):
    """Finite reasons an admission is refused."""

    DISPATCH_AUTHORITY_ABSENT = "DISPATCH_AUTHORITY_ABSENT"
    REQUEST_INVALID = "REQUEST_INVALID"
    WORKTREE_OUTSIDE_REPOSITORY_ROOT = "WORKTREE_OUTSIDE_REPOSITORY_ROOT"
    ARTIFACT_CONFLICT = "ARTIFACT_CONFLICT"
    RECEIPT_CONFLICT = "RECEIPT_CONFLICT"
    ISSUANCE_NOT_READABLE = "ISSUANCE_NOT_READABLE"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class ReceiptRevocationStatus(str, Enum):
    """Finite outcomes of one revocation admission."""

    REVOKED = "REVOKED"
    ALREADY_REVOKED = "ALREADY_REVOKED"
    REFUSED = "REFUSED"


class ReceiptRevocationFailure(str, Enum):
    """Finite reasons a revocation is refused. No two share a name.

    The three the redispatch path must keep apart are `CLAIM_STILL_OPEN`
    (the worker never came back, so the books are not closed and must not be
    reopened), `RECEIPT_NOT_REVOCABLE` (this receipt has no route to REVOKED
    from where it stands) and `STORAGE_UNAVAILABLE` (nothing is known, so
    nothing is done). Folding any two would let "we could not read the
    ledger" be reported as "the ledger says nobody is holding this".
    """

    DISPATCH_AUTHORITY_ABSENT = "DISPATCH_AUTHORITY_ABSENT"
    REQUEST_INVALID = "REQUEST_INVALID"
    REPLACEMENT_NOT_DISTINCT = "REPLACEMENT_NOT_DISTINCT"
    ASSIGNMENT_LEDGER_UNAVAILABLE = "ASSIGNMENT_LEDGER_UNAVAILABLE"
    ASSIGNMENT_ABSENT = "ASSIGNMENT_ABSENT"
    CLAIM_STILL_OPEN = "CLAIM_STILL_OPEN"
    RECEIPT_NOT_FOUND = "RECEIPT_NOT_FOUND"
    RECEIPT_MISMATCH = "RECEIPT_MISMATCH"
    RECEIPT_NOT_REVOCABLE = "RECEIPT_NOT_REVOCABLE"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class ReceiptRevocationRequest(BaseModel):
    """One revocation: which receipt ends, and which receipt takes over.

    The successor is named here and not only at the next issuance for two
    reasons. It is refused up front when it is not distinct from the receipt
    being ended, so a doomed redispatch never closes the old books first. And
    it puts "ended in favour of X" on one journal line, which is what makes
    reopening the books auditable as a single act.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: int = Field(default=1, ge=1, le=1)
    project_id: ProjectId
    ticket_reference: TicketReference
    receipt_id: ReceiptId
    replacement_receipt_id: ReceiptId


class ReceiptRevocationResult(BaseModel):
    """Exactly one ended receipt or one finite refusal."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    status: ReceiptRevocationStatus
    receipt: TicketReceipt | None = None
    failure: ReceiptRevocationFailure | None = None

    @classmethod
    def refused(cls, failure: ReceiptRevocationFailure) -> Self:
        return cls(status=ReceiptRevocationStatus.REFUSED, failure=failure)


class _RevocationScopedDispatchBoundary:
    """Exactly the surface a revocation may hold: one method, nothing else.

    The mirror of `IssuanceScopedDispatchBoundary` for the lifecycle side.
    Revocation must not hold an issuing method (the successor is issued by the
    ordinary admission gate, under its own journal line) and must not hold a
    wake method, so the class that reaches the store is built here and exposes
    the one call it needs. The full boundary is imported privately for the
    same reason the boundary imports its file lock privately: it is machinery
    this module uses, not surface this module offers.
    """

    def __init__(self, metadata_root: Path) -> None:
        self.__full_boundary = _LiveDispatchMetadataBoundary(
            _JohnnyMetadataRoot(metadata_root.resolve(strict=True))
        )

    def revoke_receipt(
        self, request: _TicketReceiptRevokeRequest
    ) -> _TicketReceiptRevokeResult:
        return self.__full_boundary.revoke_receipt(request)


class DispatchGrant(BaseModel):
    """The durable owner grant this workstation dispatches under."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: int = Field(default=1, ge=1, le=1)
    grant_id: str = Field(min_length=8, max_length=64)
    granted_by: str = Field(min_length=1, max_length=128)
    granted_at_utc: str = Field(min_length=1, max_length=64)


class DispatchAdmissionRequest(BaseModel):
    """One issuance request: the reviewed artifact plus issue-only identity.

    The `TicketReceiptIssueRequest` is derived from the artifact, so the
    descriptor fields cannot disagree by construction. The two host paths
    exist only for the containment gate and never enter the receipt.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: int = Field(default=1, ge=1, le=1)
    artifact: ApprovedDispatchArtifactRecord
    receipt_id: str = Field(pattern=_OPAQUE)
    correlation_id: str = Field(pattern=_OPAQUE)
    dispatch_question_id: str = Field(pattern=_OPAQUE)
    worktree_fingerprint: str = Field(pattern=_WORKTREE)
    branch_fingerprint: str = Field(pattern=_BRANCH)
    repository_root: str = Field(min_length=1, max_length=512)
    host_worktree_path: str = Field(min_length=1, max_length=512)


class DispatchAdmissionResult(BaseModel):
    """Exactly one dispatched receipt or one finite refusal."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    status: DispatchAdmissionStatus
    receipt: TicketReceipt | None = None
    failure: DispatchAdmissionFailure | None = None

    @classmethod
    def refused(cls, failure: DispatchAdmissionFailure) -> Self:
        return cls(status=DispatchAdmissionStatus.REFUSED, failure=failure)


def grant_path(layout: JohnnyRootLayout) -> Path:
    return layout.base / _GRANT_FILE_NAME


def journal_path(layout: JohnnyRootLayout) -> Path:
    return layout.queue_root / _JOURNAL_FILE_NAME


def create_dispatch_grant(
    layout: JohnnyRootLayout,
) -> tuple[DispatchGrantStatus, DispatchGrant | None]:
    """Record the owner's explicit decision that this machine dispatches."""

    path = grant_path(layout)
    existing = read_dispatch_grant(layout)
    if existing is not None:
        return DispatchGrantStatus.ALREADY_GRANTED, existing
    grant = DispatchGrant(
        grant_id=uuid.uuid4().hex,
        granted_by=getpass.getuser(),
        granted_at_utc=datetime.now(timezone.utc).isoformat(),
    )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(grant.model_dump_json(), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        return DispatchGrantStatus.REFUSED, None
    return DispatchGrantStatus.GRANTED, grant


def read_dispatch_grant(layout: JohnnyRootLayout) -> DispatchGrant | None:
    """The current grant, or None when this machine has never been granted."""

    path = grant_path(layout)
    if not path.is_file():
        return None
    try:
        return DispatchGrant.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError):
        return None


def _issue_request(request: DispatchAdmissionRequest) -> TicketReceiptIssueRequest:
    artifact = request.artifact
    return TicketReceiptIssueRequest(
        artifact_identity=artifact.identity,
        ticket_revision=artifact.ticket_revision,
        ticket_digest=artifact.ticket_digest,
        ticket_document_commit=artifact.ticket_document_commit,
        handoff_revision=artifact.handoff_revision,
        handoff_digest=artifact.handoff_digest,
        handoff_document_commit=artifact.handoff_document_commit,
        baseline_commit=artifact.baseline_commit,
        receipt_id=request.receipt_id,
        expected_return=artifact.expected_return,
        descriptor_binding=artifact.descriptor_binding,
        correlation_id=request.correlation_id,
        dispatch_question_id=request.dispatch_question_id,
        worktree_fingerprint=request.worktree_fingerprint,
        branch_fingerprint=request.branch_fingerprint,
    )


def _append_journal(
    layout: JohnnyRootLayout,
    grant: DispatchGrant | None,
    outcome: str,
    *,
    receipt_id: str | None,
    ticket_reference: str | None,
    host_worktree_path: str | None,
    superseded_by_receipt_id: str | None = None,
) -> None:
    """Append one audit line; journaling failure never blocks the outcome.

    Every line carries the same key set so a reader never has to ask whether
    an absent key means "not applicable" or "written by an older build".
    `superseded_by_receipt_id` is the one key an admission never fills: it is
    populated exactly when the line records a receipt being ended in favour of
    a named successor, which makes reopening the books greppable as a single
    self-contained fact rather than a pair of lines a reader has to correlate.
    """

    entry = {
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "principal": getpass.getuser(),
        "grant_id": grant.grant_id if grant is not None else None,
        "receipt_id": receipt_id,
        "ticket_reference": ticket_reference,
        "host_worktree_path": host_worktree_path,
        "superseded_by_receipt_id": superseded_by_receipt_id,
        "outcome": outcome,
    }
    try:
        path = journal_path(layout)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
    except OSError:
        pass


def _journal(
    layout: JohnnyRootLayout,
    grant: DispatchGrant | None,
    request: DispatchAdmissionRequest | None,
    outcome: str,
) -> None:
    """Journal one admission outcome."""

    _append_journal(
        layout,
        grant,
        outcome,
        receipt_id=request.receipt_id if request is not None else None,
        ticket_reference=(
            request.artifact.ticket_reference if request is not None else None
        ),
        host_worktree_path=(
            request.host_worktree_path if request is not None else None
        ),
    )


def _journal_revocation(
    layout: JohnnyRootLayout,
    grant: DispatchGrant | None,
    request: ReceiptRevocationRequest | None,
    outcome: str,
) -> None:
    """Journal one revocation outcome, naming both receipts.

    The outcome is prefixed so a revocation line can never be mistaken for an
    admission line that happens to share a refusal name.
    """

    _append_journal(
        layout,
        grant,
        f"REVOCATION_{outcome}",
        receipt_id=request.receipt_id if request is not None else None,
        ticket_reference=request.ticket_reference if request is not None else None,
        host_worktree_path=None,
        superseded_by_receipt_id=(
            request.replacement_receipt_id if request is not None else None
        ),
    )


def admit_dispatch(
    layout: JohnnyRootLayout, request: DispatchAdmissionRequest
) -> DispatchAdmissionResult:
    """Admit one issuance through the full gate, or refuse finitely."""

    grant = read_dispatch_grant(layout)
    if grant is None:
        _journal(layout, None, None, "DISPATCH_AUTHORITY_ABSENT")
        return DispatchAdmissionResult.refused(
            DispatchAdmissionFailure.DISPATCH_AUTHORITY_ABSENT
        )
    if type(request) is not DispatchAdmissionRequest:
        _journal(layout, grant, None, "REQUEST_INVALID")
        return DispatchAdmissionResult.refused(
            DispatchAdmissionFailure.REQUEST_INVALID
        )

    containment, _ = verify_worktree_contained(
        Path(request.repository_root), Path(request.host_worktree_path)
    )
    if containment is not WorktreeContainmentStatus.CONTAINED:
        _journal(layout, grant, request, "WORKTREE_OUTSIDE_REPOSITORY_ROOT")
        return DispatchAdmissionResult.refused(
            DispatchAdmissionFailure.WORKTREE_OUTSIDE_REPOSITORY_ROOT
        )

    metadata_root = layout.queue_root / "metadata"
    try:
        metadata_root.mkdir(parents=True, exist_ok=True)
        boundary = IssuanceScopedDispatchBoundary(metadata_root)
    except OSError:
        _journal(layout, grant, request, "STORAGE_UNAVAILABLE")
        return DispatchAdmissionResult.refused(
            DispatchAdmissionFailure.STORAGE_UNAVAILABLE
        )

    registered = boundary.register_artifact(
        ApprovedDispatchArtifactRegisterRequest(artifact=request.artifact)
    )
    if registered.status not in (
        ArtifactRegistrationStatus.REGISTERED,
        ArtifactRegistrationStatus.ALREADY_REGISTERED,
    ):
        outcome = (
            "ARTIFACT_CONFLICT"
            if registered.status is ArtifactRegistrationStatus.IDENTITY_CONFLICT
            else "STORAGE_UNAVAILABLE"
        )
        _journal(layout, grant, request, outcome)
        return DispatchAdmissionResult.refused(
            DispatchAdmissionFailure[outcome]
        )

    issued = boundary.issue_receipt(_issue_request(request))
    if issued.status not in (
        ReceiptIssueStatus.ISSUED,
        ReceiptIssueStatus.ALREADY_ISSUED,
    ) or issued.receipt is None:
        outcome = (
            "STORAGE_UNAVAILABLE"
            if issued.status is ReceiptIssueStatus.STORAGE_UNAVAILABLE
            else "RECEIPT_CONFLICT"
        )
        _journal(layout, grant, request, outcome)
        return DispatchAdmissionResult.refused(
            DispatchAdmissionFailure[outcome]
        )

    verification, _ = verify_receipt_claimable(boundary, issued.receipt)
    if verification is not ReceiptVerificationStatus.CLAIMABLE:
        _journal(layout, grant, request, "ISSUANCE_NOT_READABLE")
        return DispatchAdmissionResult.refused(
            DispatchAdmissionFailure.ISSUANCE_NOT_READABLE
        )

    _journal(layout, grant, request, "DISPATCHED")
    return DispatchAdmissionResult(
        status=DispatchAdmissionStatus.DISPATCHED,
        receipt=issued.receipt,
    )


_REVOCATION_OUTCOMES: dict[_ReceiptRevokeStatus, ReceiptRevocationFailure] = {
    _ReceiptRevokeStatus.NOT_FOUND: ReceiptRevocationFailure.RECEIPT_NOT_FOUND,
    _ReceiptRevokeStatus.RECEIPT_MISMATCH: ReceiptRevocationFailure.RECEIPT_MISMATCH,
    _ReceiptRevokeStatus.NOT_REVOCABLE: (
        ReceiptRevocationFailure.RECEIPT_NOT_REVOCABLE
    ),
    _ReceiptRevokeStatus.STORAGE_UNAVAILABLE: (
        ReceiptRevocationFailure.STORAGE_UNAVAILABLE
    ),
}


def revoke_dispatch_receipt(
    layout: JohnnyRootLayout, request: ReceiptRevocationRequest
) -> ReceiptRevocationResult:
    """End one receipt so its ticket can be dispatched again — or refuse finitely.

    This is the named reopening. It runs fail-closed and in a fixed order, and
    the order carries the guarantee, so it is worth stating: owner grant,
    strict request validation, a distinct successor, **the compensation proof**,
    and only then the store write.

    **The compensation proof is the whole reason exactly-once survives.** A
    receipt is released only when the assignment ledger holds a record for it
    *and* that record is `SETTLED`. Both halves matter and neither is
    decoration:

    - `SETTLED` means the claim the failed spawn left behind was actually
      compensated. Releasing the key while a claim is open would put a second
      live receipt beside a worker that may still exist, which is the double
      dispatch this whole line is built against.
    - The record merely *existing* is what keeps the ended receipt ended. The
      ledger refuses any second claim on a receipt reference it already holds,
      whatever that record's lifecycle, so the settled row is a permanent
      tombstone: the receipt being retired can never be claimed again, and the
      successor is therefore the only claimable receipt on the ticket. Revoking
      a receipt that was never claimed would leave it hand-claimable *beside*
      its successor, so that case refuses under `ASSIGNMENT_ABSENT` rather
      than being waved through as "nothing to compensate".

    The proof is taken here rather than by the caller because a caller-supplied
    proof is a caller-forgeable proof. The dependency is read-only in the
    strong sense: this module holds `read_worker_assignments` and holds no
    entry that can claim or settle anything, which the tests pin by identity.
    """

    grant = read_dispatch_grant(layout)
    if grant is None:
        _journal_revocation(layout, None, None, "DISPATCH_AUTHORITY_ABSENT")
        return ReceiptRevocationResult.refused(
            ReceiptRevocationFailure.DISPATCH_AUTHORITY_ABSENT
        )
    if type(request) is not ReceiptRevocationRequest:
        _journal_revocation(layout, grant, None, "REQUEST_INVALID")
        return ReceiptRevocationResult.refused(
            ReceiptRevocationFailure.REQUEST_INVALID
        )
    try:
        trusted = ReceiptRevocationRequest.model_validate(request, strict=True)
    except ValidationError:
        _journal_revocation(layout, grant, None, "REQUEST_INVALID")
        return ReceiptRevocationResult.refused(
            ReceiptRevocationFailure.REQUEST_INVALID
        )

    if trusted.replacement_receipt_id == trusted.receipt_id:
        _journal_revocation(layout, grant, trusted, "REPLACEMENT_NOT_DISTINCT")
        return ReceiptRevocationResult.refused(
            ReceiptRevocationFailure.REPLACEMENT_NOT_DISTINCT
        )

    ledger = read_worker_assignments(layout)
    if ledger.status is not AssignmentReadStatus.READ or ledger.assignments is None:
        _journal_revocation(layout, grant, trusted, "ASSIGNMENT_LEDGER_UNAVAILABLE")
        return ReceiptRevocationResult.refused(
            ReceiptRevocationFailure.ASSIGNMENT_LEDGER_UNAVAILABLE
        )
    held = next(
        (
            item
            for item in ledger.assignments
            if item.receipt_ref == trusted.receipt_id
        ),
        None,
    )
    if held is None:
        _journal_revocation(layout, grant, trusted, "ASSIGNMENT_ABSENT")
        return ReceiptRevocationResult.refused(
            ReceiptRevocationFailure.ASSIGNMENT_ABSENT
        )
    if held.lifecycle is not AssignmentLifecycle.SETTLED:
        _journal_revocation(layout, grant, trusted, "CLAIM_STILL_OPEN")
        return ReceiptRevocationResult.refused(
            ReceiptRevocationFailure.CLAIM_STILL_OPEN
        )

    metadata_root = layout.queue_root / "metadata"
    try:
        metadata_root.mkdir(parents=True, exist_ok=True)
        boundary = _RevocationScopedDispatchBoundary(metadata_root)
    except OSError:
        _journal_revocation(layout, grant, trusted, "STORAGE_UNAVAILABLE")
        return ReceiptRevocationResult.refused(
            ReceiptRevocationFailure.STORAGE_UNAVAILABLE
        )

    revoked = boundary.revoke_receipt(
        _TicketReceiptRevokeRequest(
            project_id=trusted.project_id,
            ticket_reference=trusted.ticket_reference,
            receipt_id=trusted.receipt_id,
        )
    )
    if revoked.status is _ReceiptRevokeStatus.REVOKED and revoked.receipt is not None:
        _journal_revocation(layout, grant, trusted, "REVOKED")
        return ReceiptRevocationResult(
            status=ReceiptRevocationStatus.REVOKED, receipt=revoked.receipt
        )
    if (
        revoked.status is _ReceiptRevokeStatus.ALREADY_REVOKED
        and revoked.receipt is not None
    ):
        # Converging rather than refusing is what makes an interrupted
        # redispatch resumable: old books closed, new books not yet open is
        # the one intermediate state this path may leave, and repeating the
        # call carries it forward instead of stranding the ticket again.
        _journal_revocation(layout, grant, trusted, "ALREADY_REVOKED")
        return ReceiptRevocationResult(
            status=ReceiptRevocationStatus.ALREADY_REVOKED, receipt=revoked.receipt
        )
    failure = _REVOCATION_OUTCOMES.get(
        revoked.status, ReceiptRevocationFailure.STORAGE_UNAVAILABLE
    )
    _journal_revocation(layout, grant, trusted, failure.value)
    return ReceiptRevocationResult.refused(failure)


__all__ = [
    "DispatchAdmissionFailure",
    "DispatchAdmissionRequest",
    "DispatchAdmissionResult",
    "DispatchAdmissionStatus",
    "DispatchGrant",
    "DispatchGrantStatus",
    "ReceiptRevocationFailure",
    "ReceiptRevocationRequest",
    "ReceiptRevocationResult",
    "ReceiptRevocationStatus",
    "admit_dispatch",
    "create_dispatch_grant",
    "grant_path",
    "journal_path",
    "read_dispatch_grant",
    "revoke_dispatch_receipt",
]
