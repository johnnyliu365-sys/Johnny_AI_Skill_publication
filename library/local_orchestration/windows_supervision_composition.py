"""Windows composition root for receipt-bound supervision, without Router binding."""

from __future__ import annotations

from pathlib import Path

import hashlib

from library.workflow_router.review_inbox_contracts import (
    ReviewClusterReadInstruction,
    ReviewTicketReadInstruction,
    ReviewWakeInstruction,
)
from library.workflow_router.role_wake_contracts import (
    RoleWakeRequest,
    RoleWakeResult,
    RoleWakeTriggerKind,
)

from .git_handoff_event_adapter import GitCliReadbackPort
from .one_shot_deadline import (
    MonotonicOneShotDeadlineFactory,
    SystemMonotonicClock,
)
from .receipt_bound_supervision import ReceiptBoundSupervisionController
from .senior_review_inbox import (
    ReviewWakeSubmissionPort,
    SeniorReviewInboxCoordinator,
)
from .windows_native_git_ref import WindowsNativeGitRefNotificationFactory


def build_windows_receipt_bound_supervision(
    repository_root: Path,
    wake_coordinator: SeniorReviewInboxCoordinator,
) -> ReceiptBoundSupervisionController:
    """Bind production local ports while leaving Router and host wake ports injected."""

    clock = SystemMonotonicClock()
    return ReceiptBoundSupervisionController(
        GitCliReadbackPort(repository_root),
        WindowsNativeGitRefNotificationFactory(repository_root),
        MonotonicOneShotDeadlineFactory(clock),
        wake_coordinator,
        clock,
    )


class SingleHandoffReviewSubmission:
    """Fill the review instruction the batching layer normally owns.

    `RoleWakeCoordinator` refuses a `REVIEW_HANDOFF` wake whose
    `review_instruction` is `None`: a reviewer woken with nothing to read
    cannot act. In the canonical composition the Senior review inbox builds
    that instruction per batch. The unbatched composition removed that layer
    without reassigning the responsibility, so every handoff-driven wake was
    refused as `ATTEMPT_CONFLICT` before the durable store was even consulted
    (E10 / CR-E7-01) while deadline wakes, which carry a different trigger,
    kept flowing.

    Without batching, the single validated handoff is its own batch, so the
    instruction is derived one-to-one from identifiers the wake request's
    chain already binds. Nothing here mints authority: the coordinator still
    claims against the durable receipt exactly as before.
    """

    def __init__(self, inner: ReviewWakeSubmissionPort) -> None:
        self._inner = inner

    def wake(self, request: RoleWakeRequest) -> RoleWakeResult:
        if (
            type(request) is not RoleWakeRequest
            or request.trigger is not RoleWakeTriggerKind.REVIEW_HANDOFF
            or request.review_instruction is not None
            or request.observed_commit is None
            or request.handoff_id is None
        ):
            return self._inner.wake(request)
        receipt = request.chain.receipt
        revision_digest = hashlib.sha256(
            (request.chain.chain_digest + "|" + request.handoff_id).encode("utf-8")
        ).hexdigest()
        instruction = ReviewWakeInstruction(
            batch_id="single-" + request.handoff_id,
            trigger_commit=request.observed_commit,
            clusters=(
                ReviewClusterReadInstruction(
                    cluster_id="cluster-" + request.handoff_id,
                    cluster_revision="rev-" + revision_digest[:16],
                    cluster_commit=request.observed_commit,
                    dependency_graph=(),
                    tickets=(
                        ReviewTicketReadInstruction(
                            ticket_ref=receipt.ticket_reference,
                            receipt_ref=receipt.receipt_id,
                            event_commit=request.observed_commit,
                            source_sections=(),
                        ),
                    ),
                ),
            ),
        )
        return self._inner.wake(
            request.model_copy(update={"review_instruction": instruction})
        )


def build_windows_supervision_without_review_batching(
    repository_root: Path,
    wake_submission: ReviewWakeSubmissionPort,
) -> ReceiptBoundSupervisionController:
    """Compose supervision with a bare wake submission and NO FIFO batching.

    The canonical builder above requires the Senior review inbox coordinator,
    which owns FIFO batching and the "wake once per new batch" rule. This
    variant deliberately omits that layer and is admitted only where no
    committed review-cluster resolver exists yet, such as the 0.4.x event
    runner. It wakes once per validated handoff instead of once per batch, so
    a reviewer can receive more wakes than the batching policy would send.
    Callers must not present it as the batched supervision path.

    The submission is wrapped in `SingleHandoffReviewSubmission`, because the
    review instruction the inbox coordinator normally builds must still exist
    for the wake to be admitted at all.
    """

    clock = SystemMonotonicClock()
    return ReceiptBoundSupervisionController(
        GitCliReadbackPort(repository_root),
        WindowsNativeGitRefNotificationFactory(repository_root),
        MonotonicOneShotDeadlineFactory(clock),
        SingleHandoffReviewSubmission(wake_submission),
        clock,
    )


__all__ = [
    "build_windows_receipt_bound_supervision",
    "build_windows_supervision_without_review_batching",
]
