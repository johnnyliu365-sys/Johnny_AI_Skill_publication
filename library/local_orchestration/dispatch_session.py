"""The one dispatch path and the one integration path, wired instead of remembered.

P2 records who holds a ticket, P3 catches a worker's return, 08's gate judges
what may become shared truth — and until this module, all three waited for the
control plane to remember to call them. Every integration on 2026-08-21 was a
hand-typed merge or a hand-built mutation request. A gate nobody calls
protects nothing; this module is the calling, written down as the only route.

**Path one — dispatch.** Issue a receipt through the admission gate, claim the
assignment, hand the worker to the host's spawn port. Three steps, one
function, and a failure at any step is a named refusal that leaves the books
whole:

- Admission refused: nothing was written that was not already true — the
  admission gate is itself fail-closed and idempotent.
- Claim refused: the receipt stands, unclaimed. That is not half a state; a
  receipt is born unclaimed, issuance is idempotent, and re-dispatching the
  same request converges instead of duplicating.
- Spawn failed: the claim is settled on the spot. A claim asserts *a worker is
  holding this*; when no worker ever existed, leaving the claim open would
  plant a permanent orphan that no read could distinguish from a dead worker.
  Settling it makes the books say what happened: the claim is closed. When
  even that compensation cannot be written, the result says so under its own
  name — never folded into the spawn failure it failed to clean up — and the
  orphan it leaves is exactly what `read_orphan_assignments` exists to surface.

**Path one, taken twice — redispatch.** The compensation above closes the
claim honestly, and the first live run of this route found what closing
honestly was not enough for: the receipt survives its own dead dispatch. It
holds the (project, ticket) key that issuance is keyed on, so the ticket that
lost a spawn could never be dispatched again — the same receipt refused
because its claim was spent, a new receipt refused because the key was taken,
a whole new identity refused because the key does not care about identity.
`redispatch_worker` is the way back, and it is deliberately not a second
dispatch path: it ends the old receipt through the authority's revocation
gate, which refuses unless the ledger shows the claim genuinely settled, and
then calls `dispatch_worker` itself. One path, entered again.

**Path two — return, then integration, with the queue between them.** A
worker's return settles its claim and lands on the durable queue in one call;
the main session pulls at its own completion boundary and the pulled work is
integrated **through the mutation gate and through nothing else**. Return and
integration are deliberately two entries on one path: the queue exists so a
return does not interrupt a busy session, so welding them into one call would
delete the very decoupling P3 was built for.

**Fail-closed on the return, concretely.** The two stores are two files, and
no cross-store transaction exists, so the order of operations is the whole
guarantee. Both stores are read before either is written: an unreadable queue
refuses *before* the settlement, an unreadable ledger refuses *before* the
enqueue, and each precondition failure names itself. Settle comes before
enqueue because the queue's contract makes the wiring layer responsible for
"this origin names a settled assignment" — enqueue-first would let a
fabricated claim reference become work. The residue that ordering cannot
remove is the window between the module's own two writes: a crash exactly
there leaves a settled claim with no queued item, the call that hits the
window returns its own failure name, and calling again completes the enqueue
without duplicating the settlement — the decision table distinguishes an
interrupted return (settled, not queued: finish it) from a repeated one
(settled and queued: refuse it) from a state this module never produces
(queued but never settled: refuse loudly, repair nothing).

**Why there is no second integration path.** This module cannot run Git. It
imports no process-spawning machinery and no filesystem machinery — every
durable effect goes through the four upstream modules, and the only
integration capability in its namespace *is* `admit_document_mutation`. That
is pinned by tests as an identity, not a convention: the gate entry this
module holds is the gate module's own function, and the namespace holds
nothing that could reach a repository behind the gate's back.

**What is honestly not achieved.** Integration pulls before it judges, because
a pull is the consumer taking the work, and P3 already states the cost: a
consumer that takes an item and fails leaves it PULLED, readable but never
re-queued. This module narrows that window — the ticket is resolved against
the *peeked* head before anything is taken, so an unresolvable ticket consumes
nothing — but a gate refusal after the pull consumes the item, and that is
correct: the work was taken, judged, and refused by name in the gate's own
journal. A commit-trigger item at the head is not integration work and is left
pending for its own wiring, which is outside this ticket; strict FIFO means it
blocks the returns behind it until that wiring exists.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from library.workflow_router.contracts import OpaqueMetadataId
from library.workflow_router.live_dispatch_contracts import TicketReceipt

from .dispatch_authority import (
    DispatchAdmissionRequest,
    DispatchAdmissionStatus,
    ReceiptRevocationRequest,
    ReceiptRevocationStatus,
    admit_dispatch,
    revoke_dispatch_receipt,
)
from .document_mutation_gate import (
    DocumentMutationFailure,
    DocumentMutationRequest,
    DocumentMutationStatus,
    admit_document_mutation,
)
from .johnny_root_layout import JohnnyRootLayout
from .work_queue import (
    WorkEnqueueRequest,
    WorkEnqueueStatus,
    WorkItem,
    WorkPullRequest,
    WorkPullStatus,
    WorkQueueReadStatus,
    WorkSource,
    enqueue_work,
    pull_work,
    read_pending_work,
    read_work_queue,
)
from .worker_assignment import (
    AssignmentLifecycle,
    AssignmentReadStatus,
    WorkerAssignment,
    WorkerClaimRequest,
    WorkerClaimStatus,
    WorkerSettlementFailure,
    WorkerSettlementRequest,
    WorkerSettlementStatus,
    claim_worker_assignment,
    read_worker_assignments,
    settle_worker_assignment,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
        revalidate_instances="always",
    )


# --------------------------------------------------------------------------
# Ports: what the host supplies, and what this module refuses to know
# --------------------------------------------------------------------------


class WorkerSpawnStatus(str, Enum):
    """The two things a spawn attempt can report. Anything else is a failure."""

    SPAWNED = "SPAWNED"
    FAILED = "FAILED"


class WorkerSpawnPort(Protocol):
    """How a worker comes to exist — the host's business, never this module's.

    The port receives the durable identities and nothing about how to run
    anything, so the route stays universal. A port that raises, or answers
    with anything that is not `SPAWNED`, is a failed spawn: fail-closed
    admits no third reading of a strange answer.
    """

    def spawn_worker(
        self, receipt: TicketReceipt, assignment: WorkerAssignment
    ) -> WorkerSpawnStatus: ...


class TicketResolution(_StrictModel):
    """Where a ticket lives and which candidate carries its work.

    Field bounds mirror `DocumentMutationRequest` exactly, so a resolution
    that validates here always constructs a gate request — there is no gap
    where a resolved ticket fails to become a judgement.
    """

    schema_version: Literal[1] = 1
    ticket_path: str = Field(min_length=1, max_length=512)
    candidate_ref: str = Field(min_length=1, max_length=256)


class TicketResolutionPort(Protocol):
    """Map an opaque ticket reference to repository facts, or decline.

    A lookup, not a capability: the port names where the ticket is and which
    ref is the candidate, and the gate still judges both. Returning `None`,
    raising, or returning anything that is not a `TicketResolution` all mean
    the same thing — this ticket cannot be resolved, and nothing is taken.
    """

    def resolve_ticket(self, ticket_ref: str) -> TicketResolution | None: ...


# --------------------------------------------------------------------------
# Path one: dispatch
# --------------------------------------------------------------------------


class WorkerDispatchStatus(str, Enum):
    """Finite outcomes of one dispatch."""

    DISPATCHED = "DISPATCHED"
    REFUSED = "REFUSED"


class WorkerDispatchFailure(str, Enum):
    """Finite reasons a dispatch is refused. One name per step, never folded.

    `SPAWN_COMPENSATION_FAILED` exists apart from `WORKER_SPAWN_FAILED`
    because the two leave different books behind: the first leaves an orphan
    claim for `read_orphan_assignments` to surface, the second leaves a claim
    honestly closed.
    """

    REQUEST_INVALID = "REQUEST_INVALID"
    RECEIPT_REFUSED = "RECEIPT_REFUSED"
    CLAIM_REFUSED = "CLAIM_REFUSED"
    WORKER_SPAWN_FAILED = "WORKER_SPAWN_FAILED"
    SPAWN_COMPENSATION_FAILED = "SPAWN_COMPENSATION_FAILED"


class WorkerDispatchRequest(_StrictModel):
    """One dispatch: the admission request plus the worker the host will bind.

    The claim is derived from the admission request and the issued receipt,
    so the fingerprints, the paths and the receipt reference cannot disagree
    by construction — the same collapse of duplicate fields the admission
    gate performs on the artifact.
    """

    schema_version: Literal[1] = 1
    admission: DispatchAdmissionRequest
    worker_ref: OpaqueMetadataId


class WorkerDispatchResult(_StrictModel):
    """Exactly one dispatched worker, or exactly one finite refusal.

    `upstream_failure` carries the refusing module's own code as text, so the
    step name and the step's reason travel together without this module
    re-encoding another module's vocabulary.
    """

    status: WorkerDispatchStatus
    receipt: TicketReceipt | None = None
    assignment: WorkerAssignment | None = None
    failure: WorkerDispatchFailure | None = None
    upstream_failure: str | None = None

    @model_validator(mode="after")
    def outcome_is_exclusive(self) -> Self:
        if self.status is WorkerDispatchStatus.DISPATCHED:
            if self.receipt is None or self.assignment is None:
                raise ValueError("a dispatch must carry its receipt and assignment")
            if self.failure is not None or self.upstream_failure is not None:
                raise ValueError("a dispatch carries no failure")
        elif self.failure is None:
            raise ValueError("a refusal must carry a reason")
        return self

    @classmethod
    def refused(
        cls, failure: WorkerDispatchFailure, upstream_failure: str | None = None
    ) -> Self:
        return cls(
            status=WorkerDispatchStatus.REFUSED,
            failure=failure,
            upstream_failure=upstream_failure,
        )


def dispatch_worker(
    layout: JohnnyRootLayout,
    request: WorkerDispatchRequest,
    spawn_port: WorkerSpawnPort,
) -> WorkerDispatchResult:
    """Issue, claim, spawn — one path, and no step's failure leaves a lie.

    The claim precedes the spawn because the record must exist before the
    thing it records: a worker running with no recorded binding is the exact
    disaster P2 was built against. The price is that a failed spawn leaves a
    claim to clean up, and the cleanup is immediate and durable — the claim
    is settled, closing it, in the same call that reports the failure.
    """

    if type(request) is not WorkerDispatchRequest:
        return WorkerDispatchResult.refused(WorkerDispatchFailure.REQUEST_INVALID)
    try:
        trusted = WorkerDispatchRequest.model_validate(request, strict=True)
    except ValidationError:
        return WorkerDispatchResult.refused(WorkerDispatchFailure.REQUEST_INVALID)

    admitted = admit_dispatch(layout, trusted.admission)
    if admitted.status is not DispatchAdmissionStatus.DISPATCHED or (
        admitted.receipt is None
    ):
        return WorkerDispatchResult.refused(
            WorkerDispatchFailure.RECEIPT_REFUSED,
            None if admitted.failure is None else admitted.failure.value,
        )
    receipt = admitted.receipt

    try:
        claim_request = WorkerClaimRequest(
            receipt_ref=receipt.receipt_id,
            worker_ref=trusted.worker_ref,
            worktree_ref=trusted.admission.worktree_fingerprint,
            branch_ref=trusted.admission.branch_fingerprint,
            repository_root=trusted.admission.repository_root,
            host_worktree_path=trusted.admission.host_worktree_path,
        )
    except ValidationError:
        return WorkerDispatchResult.refused(
            WorkerDispatchFailure.CLAIM_REFUSED, "REQUEST_INVALID"
        )
    claimed = claim_worker_assignment(layout, claim_request)
    if claimed.status is not WorkerClaimStatus.CLAIMED or claimed.assignment is None:
        return WorkerDispatchResult.refused(
            WorkerDispatchFailure.CLAIM_REFUSED,
            None if claimed.failure is None else claimed.failure.value,
        )
    assignment = claimed.assignment

    try:
        outcome = spawn_port.spawn_worker(receipt, assignment)
    except Exception:  # noqa: BLE001 — a raising port is a failed spawn, nothing else.
        outcome = WorkerSpawnStatus.FAILED
    if outcome is not WorkerSpawnStatus.SPAWNED:
        settled = settle_worker_assignment(
            layout,
            WorkerSettlementRequest(
                claim_id=assignment.claim_id, receipt_ref=assignment.receipt_ref
            ),
        )
        if settled.status is WorkerSettlementStatus.SETTLED:
            return WorkerDispatchResult.refused(
                WorkerDispatchFailure.WORKER_SPAWN_FAILED
            )
        return WorkerDispatchResult.refused(
            WorkerDispatchFailure.SPAWN_COMPENSATION_FAILED,
            None if settled.failure is None else settled.failure.value,
        )

    return WorkerDispatchResult(
        status=WorkerDispatchStatus.DISPATCHED,
        receipt=receipt,
        assignment=assignment,
    )


# --------------------------------------------------------------------------
# Path one again: the same path, after a compensation closed the books
# --------------------------------------------------------------------------


class WorkerRedispatchStatus(str, Enum):
    """Finite outcomes of one redispatch."""

    DISPATCHED = "DISPATCHED"
    REFUSED = "REFUSED"


class WorkerRedispatchFailure(str, Enum):
    """Finite reasons a redispatch is refused, one name per half.

    Two names, because a redispatch is exactly two acts. `REVOCATION_REFUSED`
    means the books were never reopened and nothing was attempted;
    `DISPATCH_REFUSED` means they were reopened and the ordinary dispatch path
    then refused under its own name. Reading them as one code would erase the
    only distinction that tells an operator whether the old receipt is still
    standing.
    """

    REQUEST_INVALID = "REQUEST_INVALID"
    REVOCATION_REFUSED = "REVOCATION_REFUSED"
    DISPATCH_REFUSED = "DISPATCH_REFUSED"


class WorkerRedispatchRequest(_StrictModel):
    """One redispatch: the whole next dispatch, plus the receipt it supersedes.

    Carrying an entire `WorkerDispatchRequest` rather than restating its
    fields is the point: the second half of a redispatch is not a variant of
    dispatch, it *is* dispatch, and a request shaped this way cannot drift
    away from the one the ordinary path takes.
    """

    schema_version: Literal[1] = 1
    dispatch: WorkerDispatchRequest
    superseded_receipt_ref: OpaqueMetadataId


class WorkerRedispatchResult(_StrictModel):
    """One redispatched worker, or one finite refusal naming which half failed.

    The dispatch half's own result is carried whole rather than summarised,
    so every distinction that path draws — claim refused, spawn failed,
    compensation failed — survives the trip through this one unchanged.
    """

    status: WorkerRedispatchStatus
    superseded_receipt_ref: OpaqueMetadataId | None = None
    revoked_receipt: TicketReceipt | None = None
    dispatch: WorkerDispatchResult | None = None
    failure: WorkerRedispatchFailure | None = None
    upstream_failure: str | None = None

    @model_validator(mode="after")
    def outcome_is_exclusive(self) -> Self:
        if self.status is WorkerRedispatchStatus.DISPATCHED:
            if (
                self.dispatch is None
                or self.dispatch.status is not WorkerDispatchStatus.DISPATCHED
            ):
                raise ValueError("a redispatch must carry the dispatch it completed")
            if self.superseded_receipt_ref is None or self.revoked_receipt is None:
                raise ValueError("a redispatch must name the receipt it superseded")
            if self.failure is not None or self.upstream_failure is not None:
                raise ValueError("a redispatch carries no failure")
        elif self.failure is None:
            raise ValueError("a refusal must carry a reason")
        return self


def redispatch_worker(
    layout: JohnnyRootLayout,
    request: WorkerRedispatchRequest,
    spawn_port: WorkerSpawnPort,
) -> WorkerRedispatchResult:
    """Reopen a compensated ticket's books, then take the ordinary path.

    A failed spawn used to be terminal for a ticket. Not because anything was
    broken — the compensation settled the claim exactly as it should — but
    because closing was the only direction that existed. The receipt kept the
    (project, ticket) key, issuance is keyed there, and so every later
    attempt refused: the same receipt because its claim was spent, a new
    receipt because the key was taken, a new identity because the key does not
    care about identity.

    So the route back is two acts and not one. **End the old receipt**, which
    `revoke_dispatch_receipt` will only do once the ledger shows the claim
    came home, and which frees the key. **Then dispatch**, through
    `dispatch_worker` unchanged — not a redispatch-flavoured copy of it, the
    function itself, so that everything the ordinary path guarantees about
    issuing, claiming, spawning and compensating is inherited rather than
    re-implemented and re-argued.

    **What a mid-way failure leaves.** Revocation first is deliberate. If the
    revocation refuses, nothing moved at all. If it succeeds and the dispatch
    then refuses, the books say old receipt ended, no successor issued — the
    one intermediate state this path may leave, and the readable one: the
    ticket's receipt reads `CLOSED`, its claim reads `SETTLED`, no worker is
    implied anywhere. Calling again resumes it, because ending an already
    ended receipt converges. The reverse order has no such story: a successor
    issued before the old receipt ends cannot be issued at all, since the key
    is still held.
    """

    if type(request) is not WorkerRedispatchRequest:
        return WorkerRedispatchResult(
            status=WorkerRedispatchStatus.REFUSED,
            failure=WorkerRedispatchFailure.REQUEST_INVALID,
        )
    try:
        trusted = WorkerRedispatchRequest.model_validate(request, strict=True)
    except ValidationError:
        return WorkerRedispatchResult(
            status=WorkerRedispatchStatus.REFUSED,
            failure=WorkerRedispatchFailure.REQUEST_INVALID,
        )

    artifact = trusted.dispatch.admission.artifact
    try:
        revocation_request = ReceiptRevocationRequest(
            project_id=artifact.project_id,
            ticket_reference=artifact.ticket_reference,
            receipt_id=trusted.superseded_receipt_ref,
            replacement_receipt_id=trusted.dispatch.admission.receipt_id,
        )
    except ValidationError:
        return WorkerRedispatchResult(
            status=WorkerRedispatchStatus.REFUSED,
            failure=WorkerRedispatchFailure.REQUEST_INVALID,
        )
    revoked = revoke_dispatch_receipt(layout, revocation_request)
    if revoked.status is ReceiptRevocationStatus.REFUSED or revoked.receipt is None:
        return WorkerRedispatchResult(
            status=WorkerRedispatchStatus.REFUSED,
            superseded_receipt_ref=trusted.superseded_receipt_ref,
            failure=WorkerRedispatchFailure.REVOCATION_REFUSED,
            upstream_failure=(
                None if revoked.failure is None else revoked.failure.value
            ),
        )

    dispatched = dispatch_worker(layout, trusted.dispatch, spawn_port)
    if dispatched.status is not WorkerDispatchStatus.DISPATCHED:
        return WorkerRedispatchResult(
            status=WorkerRedispatchStatus.REFUSED,
            superseded_receipt_ref=trusted.superseded_receipt_ref,
            revoked_receipt=revoked.receipt,
            dispatch=dispatched,
            failure=WorkerRedispatchFailure.DISPATCH_REFUSED,
            upstream_failure=(
                None if dispatched.failure is None else dispatched.failure.value
            ),
        )

    return WorkerRedispatchResult(
        status=WorkerRedispatchStatus.DISPATCHED,
        superseded_receipt_ref=trusted.superseded_receipt_ref,
        revoked_receipt=revoked.receipt,
        dispatch=dispatched,
    )


# --------------------------------------------------------------------------
# Path two, first entry: a worker's return lands durably
# --------------------------------------------------------------------------


class WorkerReturnStatus(str, Enum):
    """Finite outcomes of recording one return."""

    RECORDED = "RECORDED"
    REFUSED = "REFUSED"


class WorkerReturnFailure(str, Enum):
    """Finite reasons a return is refused. Each names a different fact.

    Folding any two of these would erase a distinction at the moment it is
    needed: an unreadable queue is not a duplicate return, a duplicate return
    is not an absent claim, and a state this module never produces is not any
    of them.
    """

    REQUEST_INVALID = "REQUEST_INVALID"
    QUEUE_UNAVAILABLE = "QUEUE_UNAVAILABLE"
    ASSIGNMENT_LEDGER_UNAVAILABLE = "ASSIGNMENT_LEDGER_UNAVAILABLE"
    RETURN_CLAIM_ABSENT = "RETURN_CLAIM_ABSENT"
    RETURN_RECEIPT_MISMATCH = "RETURN_RECEIPT_MISMATCH"
    RETURN_LEDGER_INCONSISTENT = "RETURN_LEDGER_INCONSISTENT"
    RETURN_SETTLE_CONFLICT = "RETURN_SETTLE_CONFLICT"
    RETURN_ENQUEUE_FAILED = "RETURN_ENQUEUE_FAILED"
    RETURN_ALREADY_RECORDED = "RETURN_ALREADY_RECORDED"


_SETTLE_FAILURE_NAMES: dict[WorkerSettlementFailure, WorkerReturnFailure] = {
    WorkerSettlementFailure.REQUEST_INVALID: WorkerReturnFailure.REQUEST_INVALID,
    WorkerSettlementFailure.ASSIGNMENT_ABSENT: WorkerReturnFailure.RETURN_CLAIM_ABSENT,
    WorkerSettlementFailure.SETTLEMENT_RECEIPT_MISMATCH: (
        WorkerReturnFailure.RETURN_RECEIPT_MISMATCH
    ),
    WorkerSettlementFailure.ASSIGNMENT_ALREADY_SETTLED: (
        WorkerReturnFailure.RETURN_SETTLE_CONFLICT
    ),
    WorkerSettlementFailure.STORAGE_UNAVAILABLE: (
        WorkerReturnFailure.ASSIGNMENT_LEDGER_UNAVAILABLE
    ),
}


class WorkerReturnRequest(_StrictModel):
    """One return: which claim came back, under which receipt, for which ticket.

    The receipt is carried for the same reason a settlement carries it — a
    claim reference alone would close whatever it happened to point at. The
    ticket reference is carried because the queue item needs it and the
    assignment record deliberately does not hold it.
    """

    schema_version: Literal[1] = 1
    claim_ref: OpaqueMetadataId
    receipt_ref: OpaqueMetadataId
    ticket_ref: OpaqueMetadataId


class WorkerReturnResult(_StrictModel):
    """Exactly one recorded return, or exactly one finite refusal."""

    status: WorkerReturnStatus
    assignment: WorkerAssignment | None = None
    item: WorkItem | None = None
    failure: WorkerReturnFailure | None = None
    upstream_failure: str | None = None

    @model_validator(mode="after")
    def outcome_is_exclusive(self) -> Self:
        if self.status is WorkerReturnStatus.RECORDED:
            if self.assignment is None or self.item is None:
                raise ValueError(
                    "a recorded return must carry its settlement and its item"
                )
            if self.failure is not None or self.upstream_failure is not None:
                raise ValueError("a recorded return carries no failure")
        elif self.failure is None:
            raise ValueError("a refusal must carry a reason")
        return self

    @classmethod
    def refused(
        cls, failure: WorkerReturnFailure, upstream_failure: str | None = None
    ) -> Self:
        return cls(
            status=WorkerReturnStatus.REFUSED,
            failure=failure,
            upstream_failure=upstream_failure,
        )


def record_worker_return(
    layout: JohnnyRootLayout, request: WorkerReturnRequest
) -> WorkerReturnResult:
    """Settle the claim and queue the return — or refuse before touching either.

    Both stores are read before either is written, so a store that cannot be
    read refuses the whole return while the other store is still untouched.
    Settle precedes enqueue because the queue's contract charges the wiring
    layer with "this origin names a settled assignment". The one window left
    — settled, then the enqueue fails — returns its own name and is closed by
    calling again: the decision table below reads the books and finishes the
    interrupted return instead of duplicating or disguising it.
    """

    if type(request) is not WorkerReturnRequest:
        return WorkerReturnResult.refused(WorkerReturnFailure.REQUEST_INVALID)
    try:
        trusted = WorkerReturnRequest.model_validate(request, strict=True)
    except ValidationError:
        return WorkerReturnResult.refused(WorkerReturnFailure.REQUEST_INVALID)

    queue_read = read_work_queue(layout)
    if queue_read.status is not WorkQueueReadStatus.READ or queue_read.items is None:
        return WorkerReturnResult.refused(WorkerReturnFailure.QUEUE_UNAVAILABLE)
    already_queued = any(
        item.origin_ref == trusted.claim_ref for item in queue_read.items
    )

    ledger_read = read_worker_assignments(layout)
    if (
        ledger_read.status is not AssignmentReadStatus.READ
        or ledger_read.assignments is None
    ):
        return WorkerReturnResult.refused(
            WorkerReturnFailure.ASSIGNMENT_LEDGER_UNAVAILABLE
        )
    existing = next(
        (
            item
            for item in ledger_read.assignments
            if item.claim_id == trusted.claim_ref
        ),
        None,
    )

    if existing is None:
        # Queued work whose claim does not exist is the forbidden half-state
        # itself, pre-existing. It is surfaced under its own name, never
        # repaired into either neighbouring refusal.
        return WorkerReturnResult.refused(
            WorkerReturnFailure.RETURN_LEDGER_INCONSISTENT
            if already_queued
            else WorkerReturnFailure.RETURN_CLAIM_ABSENT
        )
    if existing.receipt_ref != trusted.receipt_ref:
        return WorkerReturnResult.refused(WorkerReturnFailure.RETURN_RECEIPT_MISMATCH)

    if existing.lifecycle is AssignmentLifecycle.SETTLED:
        if already_queued:
            return WorkerReturnResult.refused(
                WorkerReturnFailure.RETURN_ALREADY_RECORDED
            )
        # Settled but never queued: the interrupted return. Finish the enqueue
        # rather than refusing a fact the books already accepted.
        settled_assignment = existing
    else:
        if already_queued:
            # Queued before settling is an order this module never writes.
            return WorkerReturnResult.refused(
                WorkerReturnFailure.RETURN_LEDGER_INCONSISTENT
            )
        settled = settle_worker_assignment(
            layout,
            WorkerSettlementRequest(
                claim_id=trusted.claim_ref, receipt_ref=trusted.receipt_ref
            ),
        )
        if (
            settled.status is not WorkerSettlementStatus.SETTLED
            or settled.assignment is None
        ):
            failure = (
                _SETTLE_FAILURE_NAMES[settled.failure]
                if settled.failure is not None
                else WorkerReturnFailure.ASSIGNMENT_LEDGER_UNAVAILABLE
            )
            return WorkerReturnResult.refused(
                failure,
                None if settled.failure is None else settled.failure.value,
            )
        settled_assignment = settled.assignment

    enqueued = enqueue_work(
        layout,
        WorkEnqueueRequest.for_worker_return(trusted.claim_ref, trusted.ticket_ref),
    )
    if enqueued.status is not WorkEnqueueStatus.ENQUEUED or enqueued.item is None:
        return WorkerReturnResult.refused(
            WorkerReturnFailure.RETURN_ENQUEUE_FAILED,
            None if enqueued.failure is None else enqueued.failure.value,
        )

    return WorkerReturnResult(
        status=WorkerReturnStatus.RECORDED,
        assignment=settled_assignment,
        item=enqueued.item,
    )


# --------------------------------------------------------------------------
# Path two, second entry: the consumer pulls, and the gate is the only door
# --------------------------------------------------------------------------


class WorkIntegrationStatus(str, Enum):
    """Finite outcomes of one integration attempt.

    `QUEUE_EMPTY` is a status and not a failure: "there is nothing to do" is
    the answer a consumer at its completion boundary is allowed to receive.
    `COMMIT_TRIGGER_PENDING` names the head this entry does not handle and
    deliberately does not consume.
    """

    INTEGRATED = "INTEGRATED"
    QUEUE_EMPTY = "QUEUE_EMPTY"
    COMMIT_TRIGGER_PENDING = "COMMIT_TRIGGER_PENDING"
    REFUSED = "REFUSED"


class WorkIntegrationFailure(str, Enum):
    """Finite reasons an integration attempt is refused, one per step."""

    REQUEST_INVALID = "REQUEST_INVALID"
    QUEUE_UNAVAILABLE = "QUEUE_UNAVAILABLE"
    TICKET_UNRESOLVED = "TICKET_UNRESOLVED"
    PULL_REFUSED = "PULL_REFUSED"
    PULLED_ITEM_MISMATCH = "PULLED_ITEM_MISMATCH"
    GATE_REFUSED = "GATE_REFUSED"


class WorkIntegrationRequest(_StrictModel):
    """One integration attempt: who is consuming, and into which branch.

    Field bounds mirror `DocumentMutationRequest`, so a request that
    validates here always constructs a gate request.
    """

    schema_version: Literal[1] = 1
    consumer_ref: OpaqueMetadataId
    repository_root: str = Field(min_length=1, max_length=512)
    integration_branch: str = Field(min_length=1, max_length=256)


class WorkIntegrationResult(_StrictModel):
    """One integration, one empty queue, one deferred trigger, or one refusal.

    A refusal after the pull carries the consumed item, because an item that
    was taken and then refused must stay answerable; a refusal before the
    pull carries none, because nothing was taken.
    """

    status: WorkIntegrationStatus
    item: WorkItem | None = None
    integrated_commit: str | None = None
    failure: WorkIntegrationFailure | None = None
    gate_failure: DocumentMutationFailure | None = None
    offending_path: str | None = None
    upstream_failure: str | None = None

    @model_validator(mode="after")
    def outcome_is_exclusive(self) -> Self:
        if self.status is WorkIntegrationStatus.INTEGRATED:
            if self.item is None or self.integrated_commit is None:
                raise ValueError("an integration must carry its item and commit")
            if self.failure is not None or self.gate_failure is not None:
                raise ValueError("an integration carries no failure")
        elif self.status is WorkIntegrationStatus.QUEUE_EMPTY:
            if self.item is not None or self.failure is not None:
                raise ValueError("an empty queue carries no item and no failure")
        elif self.status is WorkIntegrationStatus.COMMIT_TRIGGER_PENDING:
            if self.item is None:
                raise ValueError("a deferred trigger must name the item it defers")
            if self.failure is not None or self.integrated_commit is not None:
                raise ValueError("a deferred trigger is not a failure or a merge")
        else:
            if self.failure is None:
                raise ValueError("a refusal must carry a reason")
            if self.integrated_commit is not None:
                raise ValueError("a refusal integrated nothing")
            if (self.gate_failure is not None) != (
                self.failure is WorkIntegrationFailure.GATE_REFUSED
            ):
                raise ValueError(
                    "the gate's reason travels exactly with the gate's refusal"
                )
        return self

    @classmethod
    def refused(
        cls,
        failure: WorkIntegrationFailure,
        *,
        item: WorkItem | None = None,
        gate_failure: DocumentMutationFailure | None = None,
        offending_path: str | None = None,
        upstream_failure: str | None = None,
    ) -> Self:
        return cls(
            status=WorkIntegrationStatus.REFUSED,
            item=item,
            failure=failure,
            gate_failure=gate_failure,
            offending_path=offending_path,
            upstream_failure=upstream_failure,
        )


def _resolve(
    resolver: TicketResolutionPort, ticket_ref: str
) -> TicketResolution | None:
    """One guarded lookup: a strange answer and no answer are the same answer."""

    try:
        resolution = resolver.resolve_ticket(ticket_ref)
    except Exception:  # noqa: BLE001 — a raising port resolves nothing.
        return None
    if type(resolution) is not TicketResolution:
        return None
    return resolution


def integrate_next_work(
    layout: JohnnyRootLayout,
    request: WorkIntegrationRequest,
    resolver: TicketResolutionPort,
) -> WorkIntegrationResult:
    """Pull the next return and integrate it through the gate — the only door.

    The head is peeked and resolved before anything is taken, so a ticket
    that cannot be resolved consumes nothing. Once pulled, the item's fate is
    the gate's verdict: integrated, or refused by name with the item still on
    the books as taken. This function holds no way to move a commit into the
    integration branch other than `admit_document_mutation` — that absence is
    the property, and the tests pin it as one.
    """

    if type(request) is not WorkIntegrationRequest:
        return WorkIntegrationResult.refused(WorkIntegrationFailure.REQUEST_INVALID)
    try:
        trusted = WorkIntegrationRequest.model_validate(request, strict=True)
    except ValidationError:
        return WorkIntegrationResult.refused(WorkIntegrationFailure.REQUEST_INVALID)

    pending = read_pending_work(layout)
    if pending.status is not WorkQueueReadStatus.READ or pending.items is None:
        return WorkIntegrationResult.refused(WorkIntegrationFailure.QUEUE_UNAVAILABLE)
    if not pending.items:
        return WorkIntegrationResult(status=WorkIntegrationStatus.QUEUE_EMPTY)
    head = pending.items[0]

    if head.source is WorkSource.COMMIT_TRIGGER:
        return WorkIntegrationResult(
            status=WorkIntegrationStatus.COMMIT_TRIGGER_PENDING, item=head
        )

    resolution = _resolve(resolver, head.ticket_ref)
    if resolution is None:
        return WorkIntegrationResult.refused(WorkIntegrationFailure.TICKET_UNRESOLVED)

    pulled = pull_work(layout, WorkPullRequest(consumer_ref=trusted.consumer_ref))
    if pulled.status is WorkPullStatus.EMPTY:
        return WorkIntegrationResult(status=WorkIntegrationStatus.QUEUE_EMPTY)
    if pulled.status is not WorkPullStatus.PULLED or pulled.item is None:
        return WorkIntegrationResult.refused(
            WorkIntegrationFailure.PULL_REFUSED,
            upstream_failure=(
                None if pulled.failure is None else pulled.failure.value
            ),
        )
    if pulled.item.item_id != head.item_id:
        # Another consumer took the head between the peek and the pull. The
        # item now in hand was resolved for nobody; refusing under its own
        # name keeps the consumed item answerable instead of judging it
        # against the wrong ticket's facts.
        return WorkIntegrationResult.refused(
            WorkIntegrationFailure.PULLED_ITEM_MISMATCH, item=pulled.item
        )

    verdict = admit_document_mutation(
        layout,
        DocumentMutationRequest(
            repository_root=trusted.repository_root,
            ticket_path=resolution.ticket_path,
            integration_branch=trusted.integration_branch,
            candidate_ref=resolution.candidate_ref,
        ),
    )
    if verdict.status is not DocumentMutationStatus.INTEGRATED or (
        verdict.integrated_commit is None
    ):
        return WorkIntegrationResult.refused(
            WorkIntegrationFailure.GATE_REFUSED,
            item=pulled.item,
            gate_failure=verdict.failure,
            offending_path=verdict.offending_path,
            upstream_failure=verdict.detail,
        )

    return WorkIntegrationResult(
        status=WorkIntegrationStatus.INTEGRATED,
        item=pulled.item,
        integrated_commit=verdict.integrated_commit,
    )


__all__ = [
    "TicketResolution",
    "TicketResolutionPort",
    "WorkIntegrationFailure",
    "WorkIntegrationRequest",
    "WorkIntegrationResult",
    "WorkIntegrationStatus",
    "WorkerDispatchFailure",
    "WorkerDispatchRequest",
    "WorkerDispatchResult",
    "WorkerDispatchStatus",
    "WorkerRedispatchFailure",
    "WorkerRedispatchRequest",
    "WorkerRedispatchResult",
    "WorkerRedispatchStatus",
    "WorkerReturnFailure",
    "WorkerReturnRequest",
    "WorkerReturnResult",
    "WorkerReturnStatus",
    "WorkerSpawnPort",
    "WorkerSpawnStatus",
    "dispatch_worker",
    "integrate_next_work",
    "record_worker_return",
    "redispatch_worker",
]
