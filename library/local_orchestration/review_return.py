"""The reviewer return path: the last segment of the Router's closed loop.

Dispatch issues a receipt, the runner arms on the exact ref, a commit
delivers a real wake, and an agent acts. This is the way back.

A verdict is an authority-bearing artifact, so it must not be mintable. Two
durable facts are *read* before one is recorded, and neither may be asserted
by the caller:

* the receipt exists in the durable checkpoint and is `ACTIVE` — the ticket
  really was dispatched;
* a role wake attempt for that receipt is recorded `HOST_ACCEPTED` — the
  reviewer really was woken. A verdict for a review nobody was asked to
  perform is refused, and a wake that ended `NO_EFFECT` or `EFFECT_UNCERTAIN`
  is not a delivery.

Returns live in an append-only file under the Johnny root rather than in the
durable checkpoint: the checkpoint's schema is reviewed and frozen, and a
return is control-plane bookkeeping, following the install-journal and
dispatch-journal precedent.
"""

from __future__ import annotations

import getpass
import json
import os
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from library.workflow_router.live_dispatch_contracts import (
    ReceiptLifecycle,
    ReceiptReadStatus,
    TicketReceiptReadRequest,
)
from library.workflow_router.review_inbox_contracts import ReviewTicketVerdict
from library.workflow_router.role_wake_contracts import (
    RoleWakeAttemptLifecycle,
    RoleWakeAttemptReadRequest,
    WakeAttemptReadStatus,
)

from .file_lock import ExclusiveWindowsFileLock
from .johnny_root_layout import JohnnyRootLayout
from .review_return_boundary import ReviewReturnScopedDispatchBoundary

_RETURNS_FILE_NAME = "review-returns.jsonl"
_RETURNS_LOCK_NAME = "review-returns.lock"
_OPAQUE = r"^[a-z][a-z0-9-]{2,127}$"
_REVISION = r"^rev-[0-9a-f]{16,64}$"
_COMMIT = r"^[0-9a-f]{7,64}$"
_PROJECT = r"^prj_[0-9a-f]{16}$"


class ReviewReturnStatus(str, Enum):
    """Finite outcomes of one verdict return."""

    RECORDED = "RECORDED"
    ALREADY_RECORDED = "ALREADY_RECORDED"
    REFUSED = "REFUSED"


class ReviewReturnFailure(str, Enum):
    """Finite reasons a verdict is refused."""

    REQUEST_INVALID = "REQUEST_INVALID"
    RECEIPT_NOT_DISPATCHED = "RECEIPT_NOT_DISPATCHED"
    WAKE_NOT_DELIVERED = "WAKE_NOT_DELIVERED"
    VERDICT_CONFLICT = "VERDICT_CONFLICT"
    RETURN_UNWRITABLE = "RETURN_UNWRITABLE"
    RETURN_NOT_READABLE = "RETURN_NOT_READABLE"


class ReviewReturnRequest(BaseModel):
    """One reviewer's verdict on one reviewed handoff."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: int = Field(default=1, ge=1, le=1)
    project_id: str = Field(pattern=_PROJECT)
    ticket_reference: str = Field(pattern=_OPAQUE)
    ticket_revision: str = Field(pattern=_REVISION)
    receipt_id: str = Field(pattern=_OPAQUE)
    handoff_id: str = Field(pattern=_OPAQUE)
    reviewed_commit: str = Field(pattern=_COMMIT)
    reviewer_ref: str = Field(pattern=_OPAQUE)
    verdict: ReviewTicketVerdict


class ReviewReturnRecord(BaseModel):
    """One durable return, as written and read back."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: int = Field(default=1, ge=1, le=1)
    project_id: str
    ticket_reference: str
    receipt_id: str
    handoff_id: str
    reviewed_commit: str
    reviewer_ref: str
    verdict: ReviewTicketVerdict
    recorded_at_utc: str
    recorded_by: str

    @property
    def key(self) -> tuple[str, str, str, str]:
        """What makes two returns the same return."""

        return (
            self.project_id,
            self.receipt_id,
            self.handoff_id,
            self.reviewer_ref,
        )


def returns_path(layout: JohnnyRootLayout) -> Path:
    return layout.queue_root / _RETURNS_FILE_NAME


def returns_lock_path(layout: JohnnyRootLayout) -> Path:
    """One lock guards submit and consume: they contend for the same file."""

    return layout.queue_root / _RETURNS_LOCK_NAME


def read_returns(layout: JohnnyRootLayout) -> tuple[ReviewReturnRecord, ...]:
    """Every verdict recorded so far; unreadable lines are skipped, not guessed."""

    path = returns_path(layout)
    if not path.is_file():
        return ()
    records: list[ReviewReturnRecord] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()
    for line in lines:
        if not line.strip():
            continue
        try:
            records.append(ReviewReturnRecord.model_validate_json(line))
        except (ValidationError, ValueError):
            continue
    return tuple(records)


def _wake_was_delivered(
    boundary: ReviewReturnScopedDispatchBoundary, request: ReviewReturnRequest
) -> bool:
    read = boundary.read_role_wake_attempt(
        RoleWakeAttemptReadRequest(
            project_id=request.project_id,
            ticket_ref=request.ticket_reference,
            receipt_ref=request.receipt_id,
        )
    )
    if read.status is not WakeAttemptReadStatus.FOUND:
        return False
    return any(
        record.lifecycle is RoleWakeAttemptLifecycle.HOST_ACCEPTED
        for record in read.records
    )


def submit_review_return(
    layout: JohnnyRootLayout, request: ReviewReturnRequest
) -> tuple[ReviewReturnStatus, ReviewReturnFailure | None]:
    """Record one verdict, or refuse finitely."""

    if type(request) is not ReviewReturnRequest:
        return ReviewReturnStatus.REFUSED, ReviewReturnFailure.REQUEST_INVALID

    metadata_root = layout.queue_root / "metadata"
    try:
        metadata_root.mkdir(parents=True, exist_ok=True)
        boundary = ReviewReturnScopedDispatchBoundary(metadata_root)
    except OSError:
        return ReviewReturnStatus.REFUSED, ReviewReturnFailure.RETURN_UNWRITABLE

    read = boundary.read_receipt(
        TicketReceiptReadRequest(
            project_id=request.project_id,
            ticket_reference=request.ticket_reference,
            ticket_revision=request.ticket_revision,
        )
    )
    if (
        read.status is not ReceiptReadStatus.FOUND
        or read.receipt is None
        or read.receipt.receipt_id != request.receipt_id
        or read.receipt.lifecycle is not ReceiptLifecycle.ACTIVE
    ):
        return ReviewReturnStatus.REFUSED, ReviewReturnFailure.RECEIPT_NOT_DISPATCHED

    if not _wake_was_delivered(boundary, request):
        return ReviewReturnStatus.REFUSED, ReviewReturnFailure.WAKE_NOT_DELIVERED

    # W5: the idempotence and conflict checks below are read-check-append.
    # Correct within one process and worthless across two, exactly the
    # orphan-lease family: shared durable state with per-process reasoning.
    # The OS-visible lock makes the whole section mutually exclusive.
    try:
        returns_lock_path(layout).parent.mkdir(parents=True, exist_ok=True)
        lock = ExclusiveWindowsFileLock(returns_lock_path(layout))
    except OSError:
        return ReviewReturnStatus.REFUSED, ReviewReturnFailure.RETURN_UNWRITABLE
    with lock:
        return _submit_locked(layout, request)


def _submit_locked(
    layout: JohnnyRootLayout, request: ReviewReturnRequest
) -> tuple[ReviewReturnStatus, ReviewReturnFailure | None]:
    candidate = ReviewReturnRecord(
        project_id=request.project_id,
        ticket_reference=request.ticket_reference,
        receipt_id=request.receipt_id,
        handoff_id=request.handoff_id,
        reviewed_commit=request.reviewed_commit,
        reviewer_ref=request.reviewer_ref,
        verdict=request.verdict,
        recorded_at_utc=datetime.now(timezone.utc).isoformat(),
        recorded_by=getpass.getuser(),
    )
    for existing in read_returns(layout):
        if existing.key != candidate.key:
            continue
        if (
            existing.verdict is candidate.verdict
            and existing.reviewed_commit == candidate.reviewed_commit
        ):
            return ReviewReturnStatus.ALREADY_RECORDED, None
        return ReviewReturnStatus.REFUSED, ReviewReturnFailure.VERDICT_CONFLICT

    path = returns_path(layout)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(candidate.model_dump_json() + "\n")
    except OSError:
        return ReviewReturnStatus.REFUSED, ReviewReturnFailure.RETURN_UNWRITABLE

    if not any(
        record.key == candidate.key and record.verdict is candidate.verdict
        for record in read_returns(layout)
    ):
        return ReviewReturnStatus.REFUSED, ReviewReturnFailure.RETURN_NOT_READABLE
    return ReviewReturnStatus.RECORDED, None


__all__ = [
    "ReviewReturnFailure",
    "ReviewReturnRecord",
    "ReviewReturnRequest",
    "ReviewReturnStatus",
    "read_returns",
    "returns_lock_path",
    "returns_path",
    "submit_review_return",
]
