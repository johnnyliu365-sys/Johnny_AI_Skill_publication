"""Receipt-bound FIFO Senior review inbox placed before host wake."""

from __future__ import annotations

from typing import Protocol

from pydantic import ValidationError

from library.workflow_router.review_inbox_contracts import (
    CommittedReviewTicketEvent,
    ReviewBatchClaimRequest,
    ReviewBatchClaimResult,
    ReviewBatchDecisionRequest,
    ReviewBatchDecisionResult,
    ReviewEventResolutionRequest,
    ReviewEventResolutionResult,
    ReviewEventResolutionStatus,
    ReviewInboxAdmissionResult,
    ReviewInboxAdmissionStatus,
    ReviewInspectionRequest,
    ReviewInspectionResult,
    ReviewWakeEffect,
    ReviewWakeSettlementRequest,
    ReviewWakeSettlementResult,
    ReviewWakeSettlementStatus,
    SeniorReviewInboxState,
)
from library.workflow_router.role_wake_contracts import (
    RoleWakeRequest,
    RoleWakeResult,
    RoleWakeStatus,
    RoleWakeTriggerKind,
)

from .windows_senior_review_inbox_store import WindowsSeniorReviewInboxStore


class ReviewClusterBindingResolverPort(Protocol):
    """Resolve one exact cluster binding from committed target-owned references."""

    def resolve(self, request: ReviewEventResolutionRequest) -> ReviewEventResolutionResult: ...


class ReviewWakeSubmissionPort(Protocol):
    """Existing claim-before-effect reviewer wake boundary."""

    def wake(self, request: RoleWakeRequest) -> RoleWakeResult: ...


class SeniorReviewInboxStorePort(Protocol):
    def admit_event(self, event: CommittedReviewTicketEvent) -> ReviewInboxAdmissionResult: ...

    def settle_wake(
        self,
        request: ReviewWakeSettlementRequest,
    ) -> ReviewWakeSettlementResult: ...

    def claim_batch(self, request: ReviewBatchClaimRequest) -> ReviewBatchClaimResult: ...

    def record_inspection(
        self,
        request: ReviewInspectionRequest,
    ) -> ReviewInspectionResult: ...

    def decide_batch(
        self,
        request: ReviewBatchDecisionRequest,
    ) -> ReviewBatchDecisionResult: ...

    def read_state(
        self,
        project_id: str,
        reviewer_ref: str,
    ) -> SeniorReviewInboxState | None: ...

def _resolution_matches_wake(
    request: RoleWakeRequest,
    event: CommittedReviewTicketEvent,
) -> bool:
    receipt = request.chain.receipt
    return all(
        (
            event.project_id == receipt.project_id,
            event.reviewer_ref == request.chain.reviewer_ref,
            event.ticket_ref == receipt.ticket_reference,
            event.receipt_ref == receipt.receipt_id,
            event.implementation_task_ref == request.chain.implementation_task_ref,
            event.handoff_id == request.handoff_id,
            event.event_commit == request.observed_commit,
        )
    )


class SeniorReviewInboxCoordinator(ReviewWakeSubmissionPort):
    """Queue terminal handoffs and wake the existing Senior only for a new batch."""

    def __init__(
        self,
        store: SeniorReviewInboxStorePort,
        resolver: ReviewClusterBindingResolverPort,
        wake_submission: ReviewWakeSubmissionPort,
    ) -> None:
        self._store = store
        self._resolver = resolver
        self._wake_submission = wake_submission

    def wake(self, request: RoleWakeRequest) -> RoleWakeResult:
        if type(request) is not RoleWakeRequest:
            return RoleWakeResult(status=RoleWakeStatus.ATTEMPT_CONFLICT)
        try:
            trusted = RoleWakeRequest.model_validate(request, strict=True)
        except ValidationError:
            return RoleWakeResult(status=RoleWakeStatus.ATTEMPT_CONFLICT)
        if trusted.trigger is not RoleWakeTriggerKind.REVIEW_HANDOFF:
            return self._wake_submission.wake(trusted)
        if trusted.observed_commit is None or trusted.handoff_id is None:
            return RoleWakeResult(status=RoleWakeStatus.ATTEMPT_CONFLICT)
        resolution_request = ReviewEventResolutionRequest(
            project_id=trusted.chain.receipt.project_id,
            reviewer_ref=trusted.chain.reviewer_ref,
            ticket_ref=trusted.chain.receipt.ticket_reference,
            receipt_ref=trusted.chain.receipt.receipt_id,
            implementation_task_ref=trusted.chain.implementation_task_ref,
            handoff_id=trusted.handoff_id,
            event_commit=trusted.observed_commit,
        )
        try:
            resolution = self._resolver.resolve(resolution_request)
            resolution = ReviewEventResolutionResult.model_validate(
                resolution,
                strict=True,
            )
        except (ValidationError, ValueError):
            return RoleWakeResult(status=RoleWakeStatus.ATTEMPT_CONFLICT)
        if (
            resolution.status is not ReviewEventResolutionStatus.RESOLVED
            or resolution.event is None
            or not _resolution_matches_wake(trusted, resolution.event)
        ):
            return RoleWakeResult(status=RoleWakeStatus.ATTEMPT_CONFLICT)
        admission = self._store.admit_event(resolution.event)
        if admission.status in (
            ReviewInboxAdmissionStatus.QUEUED,
            ReviewInboxAdmissionStatus.ACTIVE_BATCH_REVISED,
            ReviewInboxAdmissionStatus.DUPLICATE,
        ):
            return RoleWakeResult(status=RoleWakeStatus.QUEUED_NO_WAKE)
        if admission.status is ReviewInboxAdmissionStatus.STORAGE_UNAVAILABLE:
            return RoleWakeResult(status=RoleWakeStatus.STORAGE_UNAVAILABLE)
        if (
            admission.status is not ReviewInboxAdmissionStatus.WAKE_REQUIRED
            or admission.instruction is None
        ):
            return RoleWakeResult(status=RoleWakeStatus.ATTEMPT_CONFLICT)
        queued_request = trusted.model_copy(
            update={"review_instruction": admission.instruction}
        )
        wake = self._wake_submission.wake(queued_request)
        effect = ReviewWakeEffect.EFFECT_UNCERTAIN
        if wake.status is RoleWakeStatus.HOST_ACCEPTED:
            effect = ReviewWakeEffect.HOST_ACCEPTED
        elif wake.status is RoleWakeStatus.NO_EFFECT:
            effect = ReviewWakeEffect.NO_EFFECT
        settlement = self._store.settle_wake(
            ReviewWakeSettlementRequest(
                project_id=resolution.event.project_id,
                reviewer_ref=resolution.event.reviewer_ref,
                batch_id=admission.instruction.batch_id,
                trigger_commit=admission.instruction.trigger_commit,
                effect=effect,
            )
        )
        if settlement.status is not ReviewWakeSettlementStatus.SETTLED:
            return RoleWakeResult(status=RoleWakeStatus.EFFECT_UNCERTAIN)
        return wake

__all__ = [
    "ReviewClusterBindingResolverPort",
    "ReviewWakeSubmissionPort",
    "SeniorReviewInboxCoordinator",
    "SeniorReviewInboxStorePort",
    "WindowsSeniorReviewInboxStore",
]
