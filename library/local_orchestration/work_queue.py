"""The next thing to do, written down instead of mentioned.

P2 recorded which ticket is in whose hands. It did not answer what happens to
a worker's return that lands while the control plane is busy with something
else. Until now the answer was that the return was said out loud and then was
gone, because the only copy lived in a conversation and a conversation is not
storage. This module is the durable queue that catches it.

**Pull, never push.** Two things put work here: a worker's return, and a
commit trigger. Nothing here delivers. A consumer that has just finished
something asks for the next item, and gets one or is told there is none. That
is why this module needs no notion of whether anyone is busy, and needs no way
to interrupt anybody: the consumer chooses the moment, and the moment it
chooses is the end of a piece of work.

It is also why this is not polling. A pull happens on an event -- a piece of
work finishing -- and not on a timer.

**What pull-on-completion does not reach, stated rather than repaired.** An
item is delivered at the next completion boundary, so a consumer that is idle
has no boundary to arrive at, and work enqueued during that idleness waits
until something else finishes. Equally, a consumer that takes an item and then
dies leaves that item marked as taken; a read still shows it, but nothing
re-queues it. Both gaps have the same repair available -- something that fires
on its own -- and that repair is forbidden on this line and is not taken here.
Re-queueing in particular would require deciding when a taken item counts as
abandoned, and every such rule is a timer wearing a different noun.

**Order is declared, not inherited from the file.** Items come back in
admission order across both sources: strict FIFO on a `sequence` assigned
inside the same exclusive lock that serialises the write. Priority by source
was considered and rejected -- it can starve, and a return postponed forever
has vanished in exactly the sense this module exists to prevent. The array on
disk is deliberately not required to agree with the sequence, so the order
being served can be proven to come from the recorded field.

A sequence is not a clock. It answers which of two items came first and cannot
answer how old either one is, so no expiry rule can be built on it without
changing the schema in the open. That is the same reason P2 keeps timestamps
out of an assignment record.

**Reading failure is not emptiness.** A read that cannot produce the queue
returns a named refusal and never an empty queue. An implementation that folds
the two together stops the main session silently and emits no signal at all,
which is the C family of the defect register in its scheduler shape.

**What this module may not do.** It schedules and nothing else. It cannot mint
a receipt and cannot bind a worker to one -- it does not import the issuance
gate or the assignment ledger, and refers to a settled assignment only by an
opaque reference its caller passes in. Whether that reference really names a
settled assignment is the wiring layer's obligation, which is out of this
ticket's scope; the separation is pinned by tests rather than left to
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

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from library.workflow_router.contracts import CommitDigest, OpaqueMetadataId

from .file_lock import ExclusiveWindowsFileLock
from .johnny_root_layout import JohnnyRootLayout

_SCHEMA_REVISION: Literal["work-queue-v1"] = "work-queue-v1"
_QUEUE_FILE_NAME = "work-queue-v1.json"
_LOCK_FILE_NAME = "work-queue-v1.lock"
_TEMPORARY_PREFIX = ".work-queue-v1-"
_ITEM_PREFIX = "work-"

# Markers that would turn an opaque reference into a locator. P2 keeps host
# paths out of an assignment record; the same rule applies to anything that
# reaches this queue, because a reference that can address something is a
# reference that can be pointed somewhere else.
_LOCATOR_MARKERS: tuple[str, ...] = ("://", "\\", "/")

_OPAQUE_REFERENCE = TypeAdapter(OpaqueMetadataId)
_COMMIT_REFERENCE = TypeAdapter(CommitDigest)

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


class WorkSource(str, Enum):
    """The two things that put work on this queue. There is no third."""

    WORKER_RETURN = "WORKER_RETURN"
    COMMIT_TRIGGER = "COMMIT_TRIGGER"


class WorkItemLifecycle(str, Enum):
    """The two states one queued item can be in. There is no third.

    A taken item is not removed, so what was handed out stays answerable after
    the conversation that handed it out is gone. There is deliberately no
    "done": this module hands work over and does not supervise it, and adding
    a completion state would immediately raise the question of what to do
    about items that never reach it -- a question only a timer can answer.
    """

    PENDING = "PENDING"
    PULLED = "PULLED"


class WorkEnqueueStatus(str, Enum):
    """Finite outcomes of one enqueue."""

    ENQUEUED = "ENQUEUED"
    REFUSED = "REFUSED"


class WorkEnqueueFailure(str, Enum):
    """Finite reasons an enqueue is refused. Each names a different thing."""

    REQUEST_INVALID = "REQUEST_INVALID"
    ORIGIN_SOURCE_MISMATCH = "ORIGIN_SOURCE_MISMATCH"
    ORIGIN_ALREADY_QUEUED = "ORIGIN_ALREADY_QUEUED"
    QUEUE_INVARIANT_VIOLATED = "QUEUE_INVARIANT_VIOLATED"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class WorkPullStatus(str, Enum):
    """Finite outcomes of one pull.

    `EMPTY` and `REFUSED` are separate on purpose, and the separation is the
    point of the module. "There is nothing to do" and "I could not find out
    whether there is anything to do" are the same shape to a careless caller
    and opposite facts to a session deciding whether to stop working.
    """

    PULLED = "PULLED"
    EMPTY = "EMPTY"
    REFUSED = "REFUSED"


class WorkPullFailure(str, Enum):
    """Finite reasons a pull is refused. Emptiness is not among them."""

    REQUEST_INVALID = "REQUEST_INVALID"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class WorkQueueReadStatus(str, Enum):
    """Whether a read produced the queue, or could not."""

    READ = "READ"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


def _origin_is_opaque(origin_ref: str) -> bool:
    """Reject anything that could address a location rather than name a thing."""

    folded = origin_ref.casefold()
    return not any(marker in folded for marker in _LOCATOR_MARKERS)


def _origin_belongs_to_source(source: WorkSource, origin_ref: str) -> bool:
    """Is this reference drawn from the namespace its source actually uses?

    The two namespaces are disjoint by construction rather than by luck: a
    commit digest carries an underscore that an opaque reference forbids, and
    an opaque reference has no `git_` prefix. So a reference offered under the
    wrong source is detectable, not merely implausible.
    """

    adapter = (
        _OPAQUE_REFERENCE
        if source is WorkSource.WORKER_RETURN
        else _COMMIT_REFERENCE
    )
    try:
        adapter.validate_python(origin_ref, strict=True)
    except ValidationError:
        return False
    return True


class WorkItem(_StrictModel):
    """One piece of work: where it came from, which ticket, and its position.

    `origin_ref` and `ticket_ref` are opaque by contract and never
    interpreted here. What a claim or a commit *is* belongs to whoever
    produced it.
    """

    schema_version: Literal[1] = 1
    item_id: OpaqueMetadataId
    sequence: int = Field(ge=1)
    source: WorkSource
    origin_ref: str = Field(min_length=1, max_length=128)
    ticket_ref: OpaqueMetadataId
    lifecycle: WorkItemLifecycle
    pulled_by_ref: OpaqueMetadataId | None = None

    @model_validator(mode="after")
    def origin_stays_opaque_and_matches_its_source(self) -> Self:
        """The durable invariant, enforced on the way out of storage too.

        A record read back with a source that contradicts its origin has been
        edited by something that did not go through this module, and it is
        refused rather than reinterpreted.
        """

        if not _origin_is_opaque(self.origin_ref):
            raise ValueError("a work origin must be a reference, never a locator")
        if not _origin_belongs_to_source(self.source, self.origin_ref):
            raise ValueError("a work origin must belong to the source that claims it")
        return self

    @model_validator(mode="after")
    def a_taken_item_names_who_took_it(self) -> Self:
        if self.lifecycle is WorkItemLifecycle.PULLED:
            if self.pulled_by_ref is None:
                raise ValueError("a taken item must name its consumer")
        elif self.pulled_by_ref is not None:
            raise ValueError("work nobody has taken has no consumer")
        return self


class WorkEnqueueRequest(_StrictModel):
    """One enqueue: which source, which origin, and which ticket it concerns.

    The source is carried rather than implied by the entry point so that a
    reference offered under the wrong source produces a named refusal instead
    of being unrepresentable and therefore untested. The two constructors
    below are the intended way in.
    """

    schema_version: Literal[1] = 1
    source: WorkSource
    origin_ref: str = Field(min_length=1, max_length=128)
    ticket_ref: OpaqueMetadataId

    @model_validator(mode="after")
    def origin_stays_opaque(self) -> Self:
        if not _origin_is_opaque(self.origin_ref):
            raise ValueError("a work origin must be a reference, never a locator")
        return self

    @classmethod
    def for_worker_return(cls, claim_ref: str, ticket_ref: str) -> Self:
        """Source one: a worker returned, and its settled claim is the cause."""

        return cls(
            source=WorkSource.WORKER_RETURN,
            origin_ref=claim_ref,
            ticket_ref=ticket_ref,
        )

    @classmethod
    def for_commit_trigger(cls, commit_ref: str, ticket_ref: str) -> Self:
        """Source two: a commit landed, and the commit itself is the cause."""

        return cls(
            source=WorkSource.COMMIT_TRIGGER,
            origin_ref=commit_ref,
            ticket_ref=ticket_ref,
        )


class WorkPullRequest(_StrictModel):
    """One pull, naming who is asking.

    The consumer is recorded because a pull asserts *who is holding this now*,
    the same assertion a claim makes in P2, and an assertion nobody signed is
    not answerable after the fact.
    """

    schema_version: Literal[1] = 1
    consumer_ref: OpaqueMetadataId


class WorkEnqueueResult(_StrictModel):
    """Exactly one queued item, or exactly one finite refusal."""

    status: WorkEnqueueStatus
    item: WorkItem | None = None
    failure: WorkEnqueueFailure | None = None

    @model_validator(mode="after")
    def outcome_is_exclusive(self) -> Self:
        if self.status is WorkEnqueueStatus.ENQUEUED:
            if self.item is None or self.failure is not None:
                raise ValueError("an enqueue must carry its item and no failure")
        elif self.item is not None or self.failure is None:
            raise ValueError("a refusal must carry a reason and no item")
        return self

    @classmethod
    def refused(cls, failure: WorkEnqueueFailure) -> Self:
        return cls(status=WorkEnqueueStatus.REFUSED, failure=failure)


class WorkPullResult(_StrictModel):
    """Exactly one item, exactly one empty queue, or exactly one refusal.

    The three-way split is structural, so a caller cannot accidentally read a
    refusal as an empty queue: a refusal always carries a reason and never an
    item, and an empty queue carries neither.
    """

    status: WorkPullStatus
    item: WorkItem | None = None
    failure: WorkPullFailure | None = None

    @model_validator(mode="after")
    def outcome_is_exclusive(self) -> Self:
        if self.status is WorkPullStatus.PULLED:
            if self.item is None or self.failure is not None:
                raise ValueError("a pull must carry the item it took and no failure")
        elif self.status is WorkPullStatus.EMPTY:
            if self.item is not None or self.failure is not None:
                raise ValueError("an empty queue carries no item and no failure")
        elif self.item is not None or self.failure is None:
            raise ValueError("a refusal must carry a reason and no item")
        return self

    @classmethod
    def refused(cls, failure: WorkPullFailure) -> Self:
        return cls(status=WorkPullStatus.REFUSED, failure=failure)


class WorkQueueReadResult(_StrictModel):
    """The queue, or the fact that it could not be read.

    `items` is `None` -- not empty -- when the read failed, so a caller that
    iterates the result without checking the status raises instead of quietly
    concluding that there is nothing to do.
    """

    status: WorkQueueReadStatus
    items: tuple[WorkItem, ...] | None = None

    @model_validator(mode="after")
    def absence_and_failure_stay_distinct(self) -> Self:
        if self.status is WorkQueueReadStatus.READ:
            if self.items is None:
                raise ValueError("a successful read carries a sequence, empty or not")
        elif self.items is not None:
            raise ValueError("an unreadable queue carries no items at all")
        return self


class _WorkLedger(_StrictModel):
    """The durable file. Identity and position uniqueness are enforced on entry.

    Array order is deliberately not constrained to agree with `sequence`. The
    served order is defined by the field, and leaving the array free is what
    lets a test prove that rather than assume it.
    """

    schema_revision: Literal["work-queue-v1"] = _SCHEMA_REVISION
    items: tuple[WorkItem, ...] = ()

    @model_validator(mode="after")
    def identities_and_positions_are_unique(self) -> Self:
        item_ids = tuple(item.item_id for item in self.items)
        origins = tuple(item.origin_ref for item in self.items)
        positions = tuple(item.sequence for item in self.items)
        if len(set(item_ids)) != len(item_ids):
            raise ValueError("work item identifiers must be unique")
        if len(set(origins)) != len(origins):
            raise ValueError("one origin may enqueue at most one item")
        if len(set(positions)) != len(positions):
            raise ValueError("two items may not share one admission position")
        return self


def queue_path(layout: JohnnyRootLayout) -> Path:
    """Where the queued work lives."""

    return layout.queue_root / _QUEUE_FILE_NAME


def lock_path(layout: JohnnyRootLayout) -> Path:
    """The OS-visible lock that makes a pull exactly-once across processes.

    Deliberately its own file rather than the assignment ledger's. Sharing one
    lock between two stores would serialise unrelated work, and worse, would
    make each store's guarantee depend on the other continuing to take it.
    """

    return layout.queue_root / _LOCK_FILE_NAME


def _load(layout: JohnnyRootLayout) -> _WorkLedger:
    """Read the queue, or raise. Never silently returns an empty queue.

    An absent file is genuinely an empty queue and says so. Anything else --
    unreadable, truncated, not the schema, a directory where a file belongs --
    raises, and every caller turns that into a named refusal.
    """

    path = queue_path(layout)
    if not path.exists():
        return _WorkLedger()
    return _WorkLedger.model_validate_json(path.read_text(encoding="utf-8"), strict=True)


def _commit(layout: JohnnyRootLayout, ledger: _WorkLedger) -> None:
    """Replace the queue atomically, or raise."""

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
        os.replace(temporary_path, queue_path(layout))
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _in_declared_order(items: tuple[WorkItem, ...]) -> tuple[WorkItem, ...]:
    """Admission order, taken from the recorded position and nowhere else."""

    return tuple(sorted(items, key=lambda item: item.sequence))


def enqueue_work(
    layout: JohnnyRootLayout, request: WorkEnqueueRequest
) -> WorkEnqueueResult:
    """Put one piece of work on the queue, or refuse with a named reason.

    A repeat of an origin already queued is refused rather than treated as
    idempotent, and stays refused after that item has been taken. One cause
    produces one piece of work; admitting a second would have the consumer do
    the same thing twice, and the copy would look exactly like new work.
    """

    if type(request) is not WorkEnqueueRequest:
        return WorkEnqueueResult.refused(WorkEnqueueFailure.REQUEST_INVALID)
    try:
        trusted = WorkEnqueueRequest.model_validate(request, strict=True)
    except ValidationError:
        return WorkEnqueueResult.refused(WorkEnqueueFailure.REQUEST_INVALID)

    if not _origin_belongs_to_source(trusted.source, trusted.origin_ref):
        return WorkEnqueueResult.refused(WorkEnqueueFailure.ORIGIN_SOURCE_MISMATCH)

    try:
        layout.queue_root.mkdir(parents=True, exist_ok=True)
        with _PROCESS_LOCK, ExclusiveWindowsFileLock(lock_path(layout)):
            ledger = _load(layout)
            if any(item.origin_ref == trusted.origin_ref for item in ledger.items):
                return WorkEnqueueResult.refused(
                    WorkEnqueueFailure.ORIGIN_ALREADY_QUEUED
                )
            # The position is assigned under the same lock that serialises the
            # write. Assigning it outside would let two processes agree on a
            # number and then disagree about who holds it.
            item = WorkItem(
                item_id=f"{_ITEM_PREFIX}{uuid.uuid4().hex}",
                sequence=max((entry.sequence for entry in ledger.items), default=0) + 1,
                source=trusted.source,
                origin_ref=trusted.origin_ref,
                ticket_ref=trusted.ticket_ref,
                lifecycle=WorkItemLifecycle.PENDING,
            )
            try:
                next_ledger = _WorkLedger(items=(*ledger.items, item))
            except (ValidationError, ValueError):
                # The check above already cleared this origin_ref; only the
                # ledger's own identity invariant (also guarding item_id and
                # sequence, which nothing above checks) can still refuse this
                # write. That is the ledger's rule being violated, not the
                # disk being unavailable, and the two must not share a name.
                return WorkEnqueueResult.refused(
                    WorkEnqueueFailure.QUEUE_INVARIANT_VIOLATED
                )
            _commit(layout, next_ledger)
    except (OSError, ValidationError, ValueError):
        return WorkEnqueueResult.refused(WorkEnqueueFailure.STORAGE_UNAVAILABLE)
    return WorkEnqueueResult(status=WorkEnqueueStatus.ENQUEUED, item=item)


def pull_work(layout: JohnnyRootLayout, request: WorkPullRequest) -> WorkPullResult:
    """Take the next piece of work, be told there is none, or be refused.

    Nothing calls this. A consumer calls it when it has finished something,
    which is the only moment the owner's model admits, and is an event rather
    than a tick.
    """

    if type(request) is not WorkPullRequest:
        return WorkPullResult.refused(WorkPullFailure.REQUEST_INVALID)
    try:
        trusted = WorkPullRequest.model_validate(request, strict=True)
    except ValidationError:
        return WorkPullResult.refused(WorkPullFailure.REQUEST_INVALID)

    try:
        layout.queue_root.mkdir(parents=True, exist_ok=True)
        with _PROCESS_LOCK, ExclusiveWindowsFileLock(lock_path(layout)):
            ledger = _load(layout)
            pending = _in_declared_order(
                tuple(
                    item
                    for item in ledger.items
                    if item.lifecycle is WorkItemLifecycle.PENDING
                )
            )
            if not pending:
                return WorkPullResult(status=WorkPullStatus.EMPTY)
            taken = pending[0].model_copy(
                update={
                    "lifecycle": WorkItemLifecycle.PULLED,
                    "pulled_by_ref": trusted.consumer_ref,
                }
            )
            _commit(
                layout,
                _WorkLedger(
                    items=tuple(
                        taken if item.item_id == taken.item_id else item
                        for item in ledger.items
                    )
                ),
            )
    except (OSError, ValidationError, ValueError):
        return WorkPullResult.refused(WorkPullFailure.STORAGE_UNAVAILABLE)
    return WorkPullResult(status=WorkPullStatus.PULLED, item=taken)


def read_work_queue(layout: JohnnyRootLayout) -> WorkQueueReadResult:
    """Everything on the queue in admission order, or the named fact that it is
    unreadable."""

    try:
        layout.queue_root.mkdir(parents=True, exist_ok=True)
        with _PROCESS_LOCK, ExclusiveWindowsFileLock(lock_path(layout)):
            ledger = _load(layout)
    except (OSError, ValidationError, ValueError):
        return WorkQueueReadResult(status=WorkQueueReadStatus.STORAGE_UNAVAILABLE)
    return WorkQueueReadResult(
        status=WorkQueueReadStatus.READ, items=_in_declared_order(ledger.items)
    )


def read_pending_work(layout: JohnnyRootLayout) -> WorkQueueReadResult:
    """What is still waiting, in the order it will be served.

    This is a look, not a reservation: reading tells a caller what is there and
    changes nothing, so two readers see the same thing and neither has taken
    it. Only `pull_work` takes.
    """

    result = read_work_queue(layout)
    if result.status is not WorkQueueReadStatus.READ:
        return result
    assert result.items is not None
    return WorkQueueReadResult(
        status=WorkQueueReadStatus.READ,
        items=tuple(
            item
            for item in result.items
            if item.lifecycle is WorkItemLifecycle.PENDING
        ),
    )


__all__ = [
    "WorkEnqueueFailure",
    "WorkEnqueueRequest",
    "WorkEnqueueResult",
    "WorkEnqueueStatus",
    "WorkItem",
    "WorkItemLifecycle",
    "WorkPullFailure",
    "WorkPullRequest",
    "WorkPullResult",
    "WorkPullStatus",
    "WorkQueueReadResult",
    "WorkQueueReadStatus",
    "WorkSource",
    "enqueue_work",
    "lock_path",
    "pull_work",
    "queue_path",
    "read_pending_work",
    "read_work_queue",
]
