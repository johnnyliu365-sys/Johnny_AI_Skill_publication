"""The wire between a commit landing on a watched ref and the work queue.

P3 built the socket: `work_queue` already knows `COMMIT_TRIGGER` and already
has the constructor that names a commit as an origin. P6 found that nothing
was ever plugged into it -- the runner's product was a wake, the queue's
second source had no producer, and the two modules did not reference each
other at all. This module is that wire and nothing else.

**Where the wire is soldered.** The runner does not poll and must not start
polling to gain this. It already owns a native exact-ref watch whose signal
callback is the only moment a ref change is known, so the intake hangs off
that same callback: `CommitTriggerSignalTee` sits between the native
notification port and the supervision controller, hands every signal to the
controller first and only then offers it to the intake. No timer, no scan,
and no second watch on the same ref -- a second watch would be a second
mechanism to keep in agreement with the first.

**The wake path goes first, and is not conditional on this one.** The
controller is called before the intake and its result is not inspected, so
everything the runner did before this module existed still happens in the
same order. The reverse is deliberately not symmetric: an exception raised by
the controller propagates exactly as it did before, because swallowing it
here would hide a supervision fault that the watcher thread is written to
report.

**A signal callback is not a place to raise.** The native watcher thread
calls this sink directly and its own handler catches only `OSError`; anything
else would kill the thread, and an `OSError` would be reported as a lost
notification capability, halting supervision over a queue write. So the
intake is total by contract -- every failure comes back as a named result --
and the tee keeps a second catch for the case where that contract is broken
by an implementation it did not write.

**A failure to enqueue is a fact, not a non-event.** A commit really landed;
if the item cannot be written, the runner records that by name in its own
file rather than claiming a trigger it did not create. This is the same rule
the runner already follows for wakes it cannot deliver, where a candidate is
recorded instead of a wake being asserted.

**Unreadable is not "no commit".** `read_ref` distinguishes a ref that
resolves to no commit from a ref that could not be read, and both are named
and recorded rather than collapsed into silence. Folding either into "nothing
happened" is the C family of the defect register on the admission side, the
mirror of the rule `work_queue` enforces on the pull side.

**Convergence is the queue's rule, not a second one here.** The native watch
fires more than once per ref update -- the loose ref and `packed-refs` are
separate watches, and a rewrite touches the directory more than once -- so
repeated signals for one commit are ordinary, not exceptional. Every signal
is offered to the queue with the commit itself as the origin, and
`enqueue_work` refuses a repeat of a queued origin with
`ORIGIN_ALREADY_QUEUED`. One commit therefore produces exactly one item
because one origin produces exactly one item, which is a rule that already
existed and is already tested. Adding a memo of seen commits here would be a
second answer to the same question, and the two would eventually disagree.

**What this does not reach, stated rather than repaired.** Origin identity is
the commit, and a queued origin stays refused forever, so a ref moved back
onto a commit it already carried produces no new item; that is the same
"one cause, one piece of work" rule the queue is built on, seen from the far
side. And if the failure record itself cannot be written, the named result
still reaches this module's caller but nothing durable survives the process
-- the callback has no second store to fall back to, and inventing one would
duplicate the queue it is failing to reach.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from library.workflow_router.git_handoff_contracts import (
    GitNativeFailureSignal,
    GitRefRegistrationRequest,
    GitRefSignal,
    GitRefSnapshotStatus,
)

from .git_handoff_event_adapter import (
    GitCliReadbackPort,
    GitReadbackPort,
    NativeGitRefNotificationFactory,
    NativeGitRefNotificationPort,
    NativeGitRefSignalSink,
)
from .johnny_root_layout import JohnnyRootLayout
from .one_shot_deadline import (
    MonotonicOneShotDeadlineFactory,
    SystemMonotonicClock,
)
from .receipt_bound_supervision import ReceiptBoundSupervisionController
from .senior_review_inbox import ReviewWakeSubmissionPort
from .windows_native_git_ref import WindowsNativeGitRefNotificationFactory
from .windows_supervision_composition import SingleHandoffReviewSubmission
from .work_queue import (
    WorkEnqueueFailure,
    WorkEnqueueRequest,
    WorkEnqueueStatus,
    enqueue_work,
)

_FAILURE_FILE_NAME = "commit-trigger-failures.jsonl"

# `work_queue` accepts a commit origin only in the router's commit-digest
# shape. The prefix is applied here rather than assumed of the readback,
# whose commit identifiers are bare hexadecimal by contract.
_COMMIT_PREFIX = "git_"


class CommitTriggerStatus(str, Enum):
    """Finite outcomes of offering one native signal to the queue."""

    ENQUEUED = "ENQUEUED"
    ALREADY_QUEUED = "ALREADY_QUEUED"
    NOT_BOUND = "NOT_BOUND"
    REFUSED = "REFUSED"


class CommitTriggerFailure(str, Enum):
    """Finite reasons one signal produced no item. Each names a different thing.

    `COMMIT_ABSENT` and `COMMIT_UNREADABLE` are separate on purpose: a ref
    that resolves to nothing and a ref that could not be consulted are the
    same shape to a careless caller and opposite facts to anyone deciding
    whether a commit happened.
    """

    SIGNAL_INVALID = "SIGNAL_INVALID"
    COMMIT_ABSENT = "COMMIT_ABSENT"
    COMMIT_UNREADABLE = "COMMIT_UNREADABLE"
    ENQUEUE_REFUSED = "ENQUEUE_REFUSED"
    INTAKE_FAULTED = "INTAKE_FAULTED"


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
        revalidate_instances="always",
    )


class CommitTriggerResult(_StrictModel):
    """Exactly one queued item, one convergence, one non-event, or one refusal."""

    status: CommitTriggerStatus
    failure: CommitTriggerFailure | None = None
    enqueue_failure: WorkEnqueueFailure | None = None
    origin_ref: str | None = None
    item_id: str | None = None

    @model_validator(mode="after")
    def outcome_is_exclusive(self) -> Self:
        if self.status is CommitTriggerStatus.ENQUEUED:
            if self.item_id is None or self.origin_ref is None or self.failure:
                raise ValueError("an enqueued trigger carries its item and no failure")
        elif self.status is CommitTriggerStatus.ALREADY_QUEUED:
            if self.origin_ref is None or self.item_id is not None or self.failure:
                raise ValueError("a converged trigger names its origin and no item")
        elif self.status is CommitTriggerStatus.NOT_BOUND:
            if self.failure is not None or self.origin_ref or self.item_id:
                raise ValueError("a signal for another subscription carries nothing")
        elif self.failure is None or self.item_id is not None:
            raise ValueError("a refusal must carry a reason and no item")
        if (
            self.enqueue_failure is not None
            and self.failure is not CommitTriggerFailure.ENQUEUE_REFUSED
        ):
            raise ValueError("only a refused enqueue carries the queue's own reason")
        return self


class CommitTriggerFailureRecord(BaseModel):
    """One recorded failure to turn a real commit into queued work.

    Identifiers and finite reasons only: what the commit contained is never
    this module's business, and a record that carried content would make the
    honest log a second copy of the repository.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
    )

    schema_version: int = Field(default=1, ge=1, le=1)
    subscription_id: str = Field(min_length=1, max_length=256)
    exact_git_ref: str = Field(min_length=1, max_length=256)
    failure: CommitTriggerFailure
    enqueue_failure: WorkEnqueueFailure | None = None
    origin_ref: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def identifiers_carry_no_line_breaks(self) -> Self:
        for value in (self.subscription_id, self.exact_git_ref, self.origin_ref):
            if value is not None and ("\n" in value or "\r" in value):
                raise ValueError("recorded identifiers must not carry line breaks")
        return self


def commit_trigger_failure_path(layout: JohnnyRootLayout) -> Path:
    """Where failures to enqueue a real commit are written down."""

    return layout.queue_root / _FAILURE_FILE_NAME


def read_commit_trigger_failures(
    layout: JohnnyRootLayout,
) -> tuple[CommitTriggerFailureRecord, ...]:
    """Every recorded failure; an unreadable line invalidates the read."""

    path = commit_trigger_failure_path(layout)
    if not path.is_file():
        return ()
    records: list[CommitTriggerFailureRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        records.append(CommitTriggerFailureRecord.model_validate_json(stripped))
    return tuple(records)


class CommitTriggerIntake:
    """Turn one native ref signal into at most one queued commit trigger.

    Bound to exactly one registration, so a signal belonging to another
    subscription is not this intake's business rather than an error, and the
    ticket and ref it enqueues under come from the registration the runner
    already validated instead of from the signal, which carries no authority.
    """

    def __init__(
        self,
        layout: JohnnyRootLayout,
        registration: GitRefRegistrationRequest,
        readback: GitReadbackPort,
    ) -> None:
        self._layout = layout
        self._registration = registration
        self._readback = readback

    def on_signal(self, signal: GitRefSignal) -> CommitTriggerResult:
        """Offer one signal to the queue. Never raises; every failure is named."""

        try:
            return self._admit(signal)
        except Exception:
            # The callers are a native watcher thread and the tee above it.
            # An escaping exception there ends the subscription, so an
            # unforeseen fault becomes a recorded refusal instead.
            return self._refuse(CommitTriggerFailure.INTAKE_FAULTED)

    def record_fault(self) -> None:
        """Record that the intake itself failed, for the tee's outer catch."""

        self._record(CommitTriggerFailure.INTAKE_FAULTED, None, None)

    def _admit(self, signal: GitRefSignal) -> CommitTriggerResult:
        if type(signal) is not GitRefSignal:
            return self._refuse(CommitTriggerFailure.SIGNAL_INVALID)
        if (
            signal.subscription_id != self._registration.subscription_id
            or signal.event_source_ref != self._registration.event_source_ref
        ):
            return CommitTriggerResult(status=CommitTriggerStatus.NOT_BOUND)

        snapshot = self._readback.read_ref(self._registration.exact_git_ref)
        if snapshot.status is GitRefSnapshotStatus.NOT_FOUND:
            return self._refuse(CommitTriggerFailure.COMMIT_ABSENT)
        if (
            snapshot.status is not GitRefSnapshotStatus.FOUND
            or snapshot.commit_id is None
        ):
            return self._refuse(CommitTriggerFailure.COMMIT_UNREADABLE)

        origin_ref = _COMMIT_PREFIX + snapshot.commit_id
        try:
            request = WorkEnqueueRequest.for_commit_trigger(
                origin_ref, self._registration.ticket_ref
            )
        except ValueError:
            return self._refuse(
                CommitTriggerFailure.ENQUEUE_REFUSED,
                WorkEnqueueFailure.REQUEST_INVALID,
                origin_ref,
            )

        outcome = enqueue_work(self._layout, request)
        if outcome.status is WorkEnqueueStatus.ENQUEUED:
            assert outcome.item is not None
            return CommitTriggerResult(
                status=CommitTriggerStatus.ENQUEUED,
                origin_ref=outcome.item.origin_ref,
                item_id=outcome.item.item_id,
            )
        if outcome.failure is WorkEnqueueFailure.ORIGIN_ALREADY_QUEUED:
            # The queue's own answer to "this cause is already work", and the
            # only convergence rule this module relies on.
            return CommitTriggerResult(
                status=CommitTriggerStatus.ALREADY_QUEUED, origin_ref=origin_ref
            )
        return self._refuse(
            CommitTriggerFailure.ENQUEUE_REFUSED, outcome.failure, origin_ref
        )

    def _refuse(
        self,
        failure: CommitTriggerFailure,
        enqueue_failure: WorkEnqueueFailure | None = None,
        origin_ref: str | None = None,
    ) -> CommitTriggerResult:
        self._record(failure, enqueue_failure, origin_ref)
        return CommitTriggerResult(
            status=CommitTriggerStatus.REFUSED,
            failure=failure,
            enqueue_failure=enqueue_failure,
            origin_ref=origin_ref,
        )

    def _record(
        self,
        failure: CommitTriggerFailure,
        enqueue_failure: WorkEnqueueFailure | None,
        origin_ref: str | None,
    ) -> None:
        """Write the failure down. A record that cannot be written is not raised."""

        try:
            record = CommitTriggerFailureRecord(
                subscription_id=self._registration.subscription_id,
                exact_git_ref=self._registration.exact_git_ref,
                failure=failure,
                enqueue_failure=enqueue_failure,
                origin_ref=origin_ref,
            )
            path = commit_trigger_failure_path(self._layout)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(record.model_dump_json() + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except (OSError, ValueError):
            return


class CommitTriggerSignalTee:
    """Deliver every native signal to supervision, then offer it to the queue.

    Ordering is a decision, not an accident. The controller runs first so the
    wake path is never delayed by a Git read or a queue lock, and so nothing
    about the runner's existing behaviour depends on this module succeeding.
    """

    def __init__(
        self, inner: NativeGitRefSignalSink, intake: CommitTriggerIntake
    ) -> None:
        self._inner = inner
        self._intake = intake

    def on_signal(self, signal: GitRefSignal) -> None:
        self._inner.on_signal(signal)
        try:
            self._intake.on_signal(signal)
        except Exception:
            # `CommitTriggerIntake.on_signal` is total, so reaching here means
            # a different implementation broke that contract. Record it if the
            # object can still record, then keep the watcher thread alive:
            # a dead watcher costs every future event, not just this one.
            try:
                self._intake.record_fault()
            except Exception:
                return

    def on_failure(self, signal: GitNativeFailureSignal) -> None:
        # A lost native capability is supervision's terminal event and is
        # forwarded untouched. It says nothing about a commit, so there is
        # nothing here to enqueue.
        self._inner.on_failure(signal)


@dataclass(frozen=True, slots=True)
class CommitTriggerNotificationFactory:
    """Wrap whatever sink the controller registers with the commit-trigger tee.

    The controller passes itself as the sink when it builds its native port,
    so decorating the factory is the one place where the intake can join the
    existing callback without the controller knowing it exists.
    """

    inner: NativeGitRefNotificationFactory
    intake: CommitTriggerIntake

    def create(self, sink: NativeGitRefSignalSink) -> NativeGitRefNotificationPort:
        return self.inner.create(CommitTriggerSignalTee(sink, self.intake))


def build_supervision_with_commit_trigger_intake(
    repository_root: Path,
    wake_submission: ReviewWakeSubmissionPort,
    layout: JohnnyRootLayout,
    registration: GitRefRegistrationRequest,
) -> ReceiptBoundSupervisionController:
    """The unbatched supervision composition, with the commit trigger teed in.

    This restates `build_windows_supervision_without_review_batching` with one
    substitution -- the native factory is wrapped -- because that builder
    takes no factory argument and this ticket may not change it. The review
    submission wrapper is imported from there rather than rebuilt, so the part
    that carries policy has exactly one definition and only the assembly is
    written twice. It inherits that builder's warning in full: there is no
    FIFO batching here and no caller may present it as the batched path.

    One readback port serves both the adapter and the intake. It is stateless
    -- every call is one bounded exact Git query -- so sharing it saves a
    second construction probe rather than sharing any state.
    """

    clock = SystemMonotonicClock()
    readback = GitCliReadbackPort(repository_root)
    intake = CommitTriggerIntake(layout, registration, readback)
    return ReceiptBoundSupervisionController(
        readback,
        CommitTriggerNotificationFactory(
            WindowsNativeGitRefNotificationFactory(repository_root), intake
        ),
        MonotonicOneShotDeadlineFactory(clock),
        SingleHandoffReviewSubmission(wake_submission),
        clock,
    )


__all__ = [
    "CommitTriggerFailure",
    "CommitTriggerFailureRecord",
    "CommitTriggerIntake",
    "CommitTriggerNotificationFactory",
    "CommitTriggerResult",
    "CommitTriggerSignalTee",
    "CommitTriggerStatus",
    "build_supervision_with_commit_trigger_intake",
    "commit_trigger_failure_path",
    "read_commit_trigger_failures",
]
