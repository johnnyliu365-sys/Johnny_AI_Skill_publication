"""Which ticket is in whose hands, as a durable fact rather than a memory.

`dispatch_authority` knows a receipt was issued to an owner id. It does not
know whether anything is still holding that id. On 2026-08-21 a worker died
and the control plane did not notice for an hour, because the only copy of
"receipt R is with worker W" lived in a conversation, and a conversation is
not storage. This module is that copy, written down.

**Why there is no timer here, and no clock either.**

Polling, heartbeats and timers are forbidden on this line, and the reason is
worth restating: a heartbeat turns "still alive" into a claim that has to be
purchased continuously, and whatever stops paying looks dead whether it is or
not. So liveness is expressed the way the wake attempts already express it --
declare, then settle. A dispatch *claims*; a returning worker *settles*. An
orphan is a claim that was never settled.

The consequence worth being explicit about: an orphan is discovered **when
somebody reads**, never at a moment of its own choosing. Nothing in this
module fires. If no one reads, an orphan sits there indefinitely, and that is
the accepted cost of not having a timer -- not an oversight to be repaired
later with a background sweep, which would be a timer wearing a different
noun.

That is also why an assignment record carries **no timestamp at all**. A
timestamp here would not be a timer, but it is the only thing a timer needs:
the first person who wants "clean up claims older than an hour" would find
the field already waiting. Age is not part of this definition of an orphan,
so age is not part of the record, and adding the rule later has to start by
changing the schema in the open.

**On reusing the existing lease vocabulary.** `receipt_bound_supervision`
already says "lease", and it was read before this was written. It is not
reused, for three reasons. Its `SupervisionLease` is parameterised by elapsed
milliseconds and can close on `DEADLINE_FIRED`, so time is constitutive of it
-- exactly the shape forbidden here. It is a pure in-process reducer with no
durable store, so it cannot answer the question that actually broke, which is
what survives the conversation ending. And it supervises an execution that is
already running, whereas this records the binding itself. The naming style is
borrowed; the type is deliberately not.

**What this module may not do.** It records bookkeeping and nothing else. It
holds no issuance capability -- it cannot make a receipt, only refer to one --
and it never learns how a worker is spawned. The owner's route is universal;
the moment this file names a particular host, the route is bound to that host
and the property is gone. Both are pinned by tests rather than left to
convention.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from library.workflow_router.contracts import (
    BranchFingerprint,
    OpaqueMetadataId,
    WorktreeFingerprint,
)

from .file_lock import ExclusiveWindowsFileLock
from .johnny_root_layout import JohnnyRootLayout
from .worktree_containment import (
    WorktreeContainmentStatus,
    verify_worktree_contained,
)

_SCHEMA_REVISION: Literal["worker-assignment-v1"] = "worker-assignment-v1"
_LEDGER_FILE_NAME = "worker-assignments-v1.json"
_LOCK_FILE_NAME = "worker-assignments-v1.lock"
_TEMPORARY_PREFIX = ".worker-assignments-v1-"
_CLAIM_PREFIX = "claim-"

# In-process mutual exclusion. The file lock below is what makes the guarantee
# hold between independent processes; this one only keeps two threads of one
# process from interleaving a read-modify-write. W5 recorded what happens when
# only the in-process half exists: exactly-once holds in tests and fails in
# production, and only a real multi-process test can see the difference.
_PROCESS_LOCK = Lock()


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
        revalidate_instances="always",
    )


class AssignmentLifecycle(str, Enum):
    """The two states a recorded assignment can be in. There is no third."""

    CLAIMED = "CLAIMED"
    SETTLED = "SETTLED"


class WorkerClaimStatus(str, Enum):
    """Finite outcomes of one claim."""

    CLAIMED = "CLAIMED"
    REFUSED = "REFUSED"


class WorkerClaimFailure(str, Enum):
    """Finite reasons a claim is refused. Each names a different thing."""

    REQUEST_INVALID = "REQUEST_INVALID"
    WORKTREE_OUTSIDE_REPOSITORY_ROOT = "WORKTREE_OUTSIDE_REPOSITORY_ROOT"
    RECEIPT_ALREADY_CLAIMED = "RECEIPT_ALREADY_CLAIMED"
    ASSIGNMENT_INVARIANT_VIOLATED = "ASSIGNMENT_INVARIANT_VIOLATED"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class WorkerSettlementStatus(str, Enum):
    """Finite outcomes of one settlement."""

    SETTLED = "SETTLED"
    REFUSED = "REFUSED"


class WorkerSettlementFailure(str, Enum):
    """Finite reasons a settlement is refused."""

    REQUEST_INVALID = "REQUEST_INVALID"
    ASSIGNMENT_ABSENT = "ASSIGNMENT_ABSENT"
    SETTLEMENT_RECEIPT_MISMATCH = "SETTLEMENT_RECEIPT_MISMATCH"
    ASSIGNMENT_ALREADY_SETTLED = "ASSIGNMENT_ALREADY_SETTLED"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class AssignmentReadStatus(str, Enum):
    """Whether a read produced the ledger, or could not.

    These are separate on purpose. "The ledger says nobody is working" and
    "the ledger could not be read" are the same shape in a `tuple` return and
    opposite facts on a machine that dispatches work.
    """

    READ = "READ"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class WorkerAssignment(_StrictModel):
    """One receipt, one worktree, one branch, one opaque worker reference.

    `worker_ref` is opaque by contract: `OpaqueMetadataId` admits no path
    delimiter and no scheme, so a worker reference cannot smuggle in a
    locator, and this module never interprets it. What a worker *is* belongs
    to whatever spawned it.
    """

    schema_version: Literal[1] = 1
    claim_id: OpaqueMetadataId
    receipt_ref: OpaqueMetadataId
    worker_ref: OpaqueMetadataId
    worktree_ref: WorktreeFingerprint
    branch_ref: BranchFingerprint
    lifecycle: AssignmentLifecycle


class WorkerClaimRequest(_StrictModel):
    """One claim: the durable identities, plus two host paths for the gate.

    The host paths exist only so containment can be proven and never enter
    the record, exactly as the issuance gate keeps them out of a receipt.
    """

    schema_version: Literal[1] = 1
    receipt_ref: OpaqueMetadataId
    worker_ref: OpaqueMetadataId
    worktree_ref: WorktreeFingerprint
    branch_ref: BranchFingerprint
    repository_root: str = Field(min_length=1, max_length=512)
    host_worktree_path: str = Field(min_length=1, max_length=512)


class WorkerSettlementRequest(_StrictModel):
    """One settlement, naming both the claim and the receipt it was for.

    Carrying the receipt is not redundancy. A settlement that looked up by
    `claim_id` alone would close whatever that id happened to point at, so a
    stale or copied claim id would silently retire a different ticket's
    assignment -- and the orphan it was hiding would disappear with it.
    """

    schema_version: Literal[1] = 1
    claim_id: OpaqueMetadataId
    receipt_ref: OpaqueMetadataId


class WorkerClaimResult(_StrictModel):
    """Exactly one recorded assignment, or exactly one finite refusal."""

    status: WorkerClaimStatus
    assignment: WorkerAssignment | None = None
    failure: WorkerClaimFailure | None = None

    @model_validator(mode="after")
    def outcome_is_exclusive(self) -> Self:
        if self.status is WorkerClaimStatus.CLAIMED:
            if self.assignment is None or self.failure is not None:
                raise ValueError("a claim must carry its assignment and no failure")
        elif self.assignment is not None or self.failure is None:
            raise ValueError("a refusal must carry a reason and no assignment")
        return self

    @classmethod
    def refused(cls, failure: WorkerClaimFailure) -> Self:
        return cls(status=WorkerClaimStatus.REFUSED, failure=failure)


class WorkerSettlementResult(_StrictModel):
    """Exactly one settled assignment, or exactly one finite refusal."""

    status: WorkerSettlementStatus
    assignment: WorkerAssignment | None = None
    failure: WorkerSettlementFailure | None = None

    @model_validator(mode="after")
    def outcome_is_exclusive(self) -> Self:
        if self.status is WorkerSettlementStatus.SETTLED:
            if self.assignment is None or self.failure is not None:
                raise ValueError("a settlement must carry its assignment")
        elif self.assignment is not None or self.failure is None:
            raise ValueError("a refusal must carry a reason and no assignment")
        return self

    @classmethod
    def refused(cls, failure: WorkerSettlementFailure) -> Self:
        return cls(status=WorkerSettlementStatus.REFUSED, failure=failure)


class AssignmentReadResult(_StrictModel):
    """The ledger, or the fact that it could not be read.

    `assignments` is `None` -- not empty -- when the read failed, so a caller
    that iterates the result without checking the status raises instead of
    quietly concluding that nobody is working on anything.
    """

    status: AssignmentReadStatus
    assignments: tuple[WorkerAssignment, ...] | None = None

    @model_validator(mode="after")
    def absence_and_failure_stay_distinct(self) -> Self:
        if self.status is AssignmentReadStatus.READ:
            if self.assignments is None:
                raise ValueError("a successful read carries a sequence, empty or not")
        elif self.assignments is not None:
            raise ValueError("an unreadable ledger carries no assignments at all")
        return self


class _AssignmentLedger(_StrictModel):
    """The durable file. Identity uniqueness is enforced on the way in."""

    schema_revision: Literal["worker-assignment-v1"] = _SCHEMA_REVISION
    assignments: tuple[WorkerAssignment, ...] = ()

    @model_validator(mode="after")
    def identities_are_unique(self) -> Self:
        claim_ids = tuple(item.claim_id for item in self.assignments)
        receipt_refs = tuple(item.receipt_ref for item in self.assignments)
        if len(set(claim_ids)) != len(claim_ids):
            raise ValueError("claim identifiers must be unique")
        if len(set(receipt_refs)) != len(receipt_refs):
            raise ValueError("a receipt may appear at most once in the ledger")
        return self


def ledger_path(layout: JohnnyRootLayout) -> Path:
    """Where the assignments live."""

    return layout.queue_root / _LEDGER_FILE_NAME


def lock_path(layout: JohnnyRootLayout) -> Path:
    """The OS-visible lock that makes a claim exactly-once across processes."""

    return layout.queue_root / _LOCK_FILE_NAME


def _load(layout: JohnnyRootLayout) -> _AssignmentLedger:
    """Read the ledger, or raise. Never silently returns an empty ledger.

    An absent file is genuinely an empty ledger and says so. Anything else --
    unreadable, truncated, not the schema, a directory where a file belongs --
    raises, and every caller turns that into a refusal.
    """

    path = ledger_path(layout)
    if not path.exists():
        return _AssignmentLedger()
    return _AssignmentLedger.model_validate_json(
        path.read_text(encoding="utf-8"), strict=True
    )


def _commit(layout: JohnnyRootLayout, ledger: _AssignmentLedger) -> None:
    """Replace the ledger atomically, or raise."""

    root = layout.queue_root
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=_TEMPORARY_PREFIX, suffix=".json", dir=root
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(ledger.model_dump_json())
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, ledger_path(layout))
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def claim_worker_assignment(
    layout: JohnnyRootLayout, request: WorkerClaimRequest
) -> WorkerClaimResult:
    """Bind one receipt to one worker, or refuse with a named reason.

    A second claim on a receipt is refused, and deliberately not treated as
    idempotent even when every field matches. Issuance can be idempotent
    because a receipt is a function of the artifact, so a repeat asserts the
    same fact. A claim asserts *who is holding this now*, and a second
    assertion is a new fact however similar it looks. Folding the two together
    would quietly accept the one case this module exists to expose: a worker
    replaced without the first ever having settled.
    """

    if type(request) is not WorkerClaimRequest:
        return WorkerClaimResult.refused(WorkerClaimFailure.REQUEST_INVALID)
    try:
        trusted = WorkerClaimRequest.model_validate(request, strict=True)
    except ValidationError:
        return WorkerClaimResult.refused(WorkerClaimFailure.REQUEST_INVALID)

    containment, _ = verify_worktree_contained(
        Path(trusted.repository_root), Path(trusted.host_worktree_path)
    )
    if containment is not WorktreeContainmentStatus.CONTAINED:
        return WorkerClaimResult.refused(
            WorkerClaimFailure.WORKTREE_OUTSIDE_REPOSITORY_ROOT
        )

    assignment = WorkerAssignment(
        claim_id=f"{_CLAIM_PREFIX}{uuid.uuid4().hex}",
        receipt_ref=trusted.receipt_ref,
        worker_ref=trusted.worker_ref,
        worktree_ref=trusted.worktree_ref,
        branch_ref=trusted.branch_ref,
        lifecycle=AssignmentLifecycle.CLAIMED,
    )
    try:
        layout.queue_root.mkdir(parents=True, exist_ok=True)
        with _PROCESS_LOCK, ExclusiveWindowsFileLock(lock_path(layout)):
            ledger = _load(layout)
            if any(
                item.receipt_ref == trusted.receipt_ref for item in ledger.assignments
            ):
                return WorkerClaimResult.refused(
                    WorkerClaimFailure.RECEIPT_ALREADY_CLAIMED
                )
            try:
                next_ledger = _AssignmentLedger(
                    assignments=(*ledger.assignments, assignment)
                )
            except (ValidationError, ValueError):
                # The check above already cleared this receipt_ref; only the
                # ledger's own identity invariant (also guarding claim_id,
                # which nothing above checks) can still refuse this write.
                # That is the ledger's rule being violated, not the disk
                # being unavailable, and the two must not share a name.
                return WorkerClaimResult.refused(
                    WorkerClaimFailure.ASSIGNMENT_INVARIANT_VIOLATED
                )
            _commit(layout, next_ledger)
    except (OSError, ValidationError, ValueError):
        return WorkerClaimResult.refused(WorkerClaimFailure.STORAGE_UNAVAILABLE)
    return WorkerClaimResult(status=WorkerClaimStatus.CLAIMED, assignment=assignment)


def settle_worker_assignment(
    layout: JohnnyRootLayout, request: WorkerSettlementRequest
) -> WorkerSettlementResult:
    """Close one claim, but only the one that was actually made."""

    if type(request) is not WorkerSettlementRequest:
        return WorkerSettlementResult.refused(WorkerSettlementFailure.REQUEST_INVALID)
    try:
        trusted = WorkerSettlementRequest.model_validate(request, strict=True)
    except ValidationError:
        return WorkerSettlementResult.refused(WorkerSettlementFailure.REQUEST_INVALID)

    try:
        layout.queue_root.mkdir(parents=True, exist_ok=True)
        with _PROCESS_LOCK, ExclusiveWindowsFileLock(lock_path(layout)):
            ledger = _load(layout)
            existing = next(
                (
                    item
                    for item in ledger.assignments
                    if item.claim_id == trusted.claim_id
                ),
                None,
            )
            if existing is None:
                return WorkerSettlementResult.refused(
                    WorkerSettlementFailure.ASSIGNMENT_ABSENT
                )
            if existing.receipt_ref != trusted.receipt_ref:
                return WorkerSettlementResult.refused(
                    WorkerSettlementFailure.SETTLEMENT_RECEIPT_MISMATCH
                )
            if existing.lifecycle is not AssignmentLifecycle.CLAIMED:
                return WorkerSettlementResult.refused(
                    WorkerSettlementFailure.ASSIGNMENT_ALREADY_SETTLED
                )
            settled = existing.model_copy(
                update={"lifecycle": AssignmentLifecycle.SETTLED}
            )
            _commit(
                layout,
                _AssignmentLedger(
                    assignments=tuple(
                        settled if item.claim_id == settled.claim_id else item
                        for item in ledger.assignments
                    )
                ),
            )
    except (OSError, ValidationError, ValueError):
        return WorkerSettlementResult.refused(
            WorkerSettlementFailure.STORAGE_UNAVAILABLE
        )
    return WorkerSettlementResult(
        status=WorkerSettlementStatus.SETTLED, assignment=settled
    )


def read_worker_assignments(layout: JohnnyRootLayout) -> AssignmentReadResult:
    """Every recorded assignment, or the named fact that the ledger is unreadable."""

    try:
        layout.queue_root.mkdir(parents=True, exist_ok=True)
        with _PROCESS_LOCK, ExclusiveWindowsFileLock(lock_path(layout)):
            ledger = _load(layout)
    except (OSError, ValidationError, ValueError):
        return AssignmentReadResult(status=AssignmentReadStatus.STORAGE_UNAVAILABLE)
    return AssignmentReadResult(
        status=AssignmentReadStatus.READ, assignments=ledger.assignments
    )


def read_orphan_assignments(layout: JohnnyRootLayout) -> AssignmentReadResult:
    """The claims nobody ever settled -- surfaced because somebody looked.

    Nothing schedules this. An orphan becomes visible at the moment of a read
    and at no other moment, which is what having no timer costs and what
    having no timer is worth.
    """

    result = read_worker_assignments(layout)
    if result.status is not AssignmentReadStatus.READ:
        return result
    assert result.assignments is not None
    return AssignmentReadResult(
        status=AssignmentReadStatus.READ,
        assignments=tuple(
            item
            for item in result.assignments
            if item.lifecycle is AssignmentLifecycle.CLAIMED
        ),
    )


__all__ = [
    "AssignmentLifecycle",
    "AssignmentReadResult",
    "AssignmentReadStatus",
    "WorkerAssignment",
    "WorkerClaimFailure",
    "WorkerClaimRequest",
    "WorkerClaimResult",
    "WorkerClaimStatus",
    "WorkerSettlementFailure",
    "WorkerSettlementRequest",
    "WorkerSettlementResult",
    "WorkerSettlementStatus",
    "claim_worker_assignment",
    "ledger_path",
    "lock_path",
    "read_orphan_assignments",
    "read_worker_assignments",
    "settle_worker_assignment",
]
