"""Windows durable checkpoint adapter for the Senior review inbox."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
from threading import Lock
from types import TracebackType
from typing import BinaryIO, Literal, Self

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from library.workflow_router.review_inbox_contracts import (
    CommittedReviewTicketEvent,
    ReviewBatchClaimRequest,
    ReviewBatchClaimResult,
    ReviewBatchClaimStatus,
    ReviewBatchDecisionRequest,
    ReviewBatchDecisionResult,
    ReviewBatchDecisionStatus,
    ReviewBatchLifecycle,
    ReviewClusterDecisionIndex,
    ReviewClusterLifecycle,
    ReviewInboxAdmissionResult,
    ReviewInboxAdmissionStatus,
    ReviewerActivity,
    ReviewInspectionRequest,
    ReviewInspectionResult,
    ReviewInspectionStatus,
    ReviewTicketDecisionIndex,
    ReviewTicketInspection,
    ReviewTicketVerdict,
    ReviewWakeEffect,
    ReviewWakeSettlementRequest,
    ReviewWakeSettlementResult,
    ReviewWakeSettlementStatus,
    SeniorReviewInboxState,
)

from .file_lock import ExclusiveWindowsFileLock as _ExclusiveWindowsFileLock
from .senior_review_inbox_state import (
    _admit_event,
    _all_batch_tickets_inspected,
    _instruction,
    _new_state,
    _replace_cluster,
    _reserve_pending_batch,
    _topological_ticket_refs,
    _transitive_dependencies,
)


_SCHEMA_REVISION: Literal["senior-review-inbox-v1"] = "senior-review-inbox-v1"
_CHECKPOINT_NAME = "senior-review-inbox-v1.json"
_LOCK_NAME = "senior-review-inbox-v1.lock"
_TEMP_PREFIX = ".senior-review-inbox-v1-"


class _ReviewInboxCheckpoint(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
    )

    schema_revision: Literal["senior-review-inbox-v1"] = _SCHEMA_REVISION
    inboxes: tuple[SeniorReviewInboxState, ...] = ()

    @model_validator(mode="after")
    def inbox_identities_are_unique(self) -> Self:
        identities = tuple(
            (state.project_id, state.reviewer_ref) for state in self.inboxes
        )
        if len(identities) != len(set(identities)):
            raise ValueError("checkpoint inbox identities must be unique")
        return self


class WindowsSeniorReviewInboxStore:
    """Atomic Johnny-owned checkpoint; target projects receive no runtime files."""

    def __init__(self, metadata_root: Path) -> None:
        if not isinstance(metadata_root, Path) or not metadata_root.is_absolute():
            raise ValueError("review metadata root must be an absolute Path")
        resolved = metadata_root.resolve(strict=True)
        if resolved != metadata_root or not resolved.is_dir():
            raise ValueError("review metadata root must be an existing resolved directory")
        self._root = resolved
        self._checkpoint_path = resolved / _CHECKPOINT_NAME
        self._lock_path = resolved / _LOCK_NAME
        self._local_lock = Lock()
        self.last_admission_status: ReviewInboxAdmissionStatus | None = None

    def _load(self) -> _ReviewInboxCheckpoint:
        if not self._checkpoint_path.exists():
            return _ReviewInboxCheckpoint()
        return _ReviewInboxCheckpoint.model_validate_json(
            self._checkpoint_path.read_text(encoding="utf-8"),
            strict=True,
        )

    def _commit(self, checkpoint: _ReviewInboxCheckpoint) -> None:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=_TEMP_PREFIX,
            suffix=".json",
            dir=self._root,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(checkpoint.model_dump_json())
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self._checkpoint_path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

    @staticmethod
    def _find(
        checkpoint: _ReviewInboxCheckpoint,
        project_id: str,
        reviewer_ref: str,
    ) -> SeniorReviewInboxState | None:
        return next(
            (
                state
                for state in checkpoint.inboxes
                if state.project_id == project_id and state.reviewer_ref == reviewer_ref
            ),
            None,
        )

    @staticmethod
    def _with_state(
        checkpoint: _ReviewInboxCheckpoint,
        state: SeniorReviewInboxState,
    ) -> _ReviewInboxCheckpoint:
        found = False
        inboxes: list[SeniorReviewInboxState] = []
        for current in checkpoint.inboxes:
            if (
                current.project_id == state.project_id
                and current.reviewer_ref == state.reviewer_ref
            ):
                inboxes.append(state)
                found = True
            else:
                inboxes.append(current)
        if not found:
            inboxes.append(state)
        return _ReviewInboxCheckpoint(inboxes=tuple(inboxes))

    def admit_event(self, event: CommittedReviewTicketEvent) -> ReviewInboxAdmissionResult:
        if type(event) is not CommittedReviewTicketEvent:
            return ReviewInboxAdmissionResult(status=ReviewInboxAdmissionStatus.REJECTED)
        try:
            trusted = CommittedReviewTicketEvent.model_validate(event, strict=True)
            with self._local_lock, _ExclusiveWindowsFileLock(self._lock_path):
                checkpoint = self._load()
                state = self._find(checkpoint, trusted.project_id, trusted.reviewer_ref)
                if state is None:
                    state = _new_state(trusted)
                mutation, result = _admit_event(state, trusted)
                if mutation.changed:
                    self._commit(self._with_state(checkpoint, mutation.state))
                self.last_admission_status = result.status
                return result
        except (OSError, ValidationError, ValueError):
            self.last_admission_status = ReviewInboxAdmissionStatus.STORAGE_UNAVAILABLE
            return ReviewInboxAdmissionResult(
                status=ReviewInboxAdmissionStatus.STORAGE_UNAVAILABLE
            )

    def settle_wake(
        self,
        request: ReviewWakeSettlementRequest,
    ) -> ReviewWakeSettlementResult:
        if type(request) is not ReviewWakeSettlementRequest:
            return ReviewWakeSettlementResult(status=ReviewWakeSettlementStatus.REJECTED)
        try:
            trusted = ReviewWakeSettlementRequest.model_validate(request, strict=True)
            with self._local_lock, _ExclusiveWindowsFileLock(self._lock_path):
                checkpoint = self._load()
                state = self._find(checkpoint, trusted.project_id, trusted.reviewer_ref)
                if (
                    state is None
                    or state.activity is not ReviewerActivity.WAKE_PENDING
                    or state.active_batch is None
                    or state.active_batch.batch_id != trusted.batch_id
                    or state.wake_trigger_commit != trusted.trigger_commit
                ):
                    return ReviewWakeSettlementResult(
                        status=ReviewWakeSettlementStatus.REJECTED
                    )
                if trusted.effect is ReviewWakeEffect.HOST_ACCEPTED:
                    updated = state.model_copy(
                        update={
                            "generation": state.generation + 1,
                            "activity": ReviewerActivity.READY,
                        }
                    )
                else:
                    active_ids = {
                        item.cluster_id for item in state.active_batch.clusters
                    }
                    clusters = tuple(
                        cluster.model_copy(
                            update={"lifecycle": ReviewClusterLifecycle.PENDING_REVIEW}
                        )
                        if cluster.cluster_id in active_ids
                        else cluster
                        for cluster in state.clusters
                    )
                    updated = state.model_copy(
                        update={
                            "generation": state.generation + 1,
                            "activity": ReviewerActivity.HALTED,
                            "clusters": clusters,
                            "active_batch": None,
                            "wake_trigger_commit": None,
                        }
                    )
                self._commit(self._with_state(checkpoint, updated))
                return ReviewWakeSettlementResult(
                    status=ReviewWakeSettlementStatus.SETTLED
                )
        except (OSError, ValidationError, ValueError):
            return ReviewWakeSettlementResult(
                status=ReviewWakeSettlementStatus.STORAGE_UNAVAILABLE
            )

    def claim_batch(self, request: ReviewBatchClaimRequest) -> ReviewBatchClaimResult:
        if type(request) is not ReviewBatchClaimRequest:
            return ReviewBatchClaimResult(status=ReviewBatchClaimStatus.REJECTED)
        try:
            trusted = ReviewBatchClaimRequest.model_validate(request, strict=True)
            with self._local_lock, _ExclusiveWindowsFileLock(self._lock_path):
                checkpoint = self._load()
                state = self._find(checkpoint, trusted.project_id, trusted.reviewer_ref)
                if state is None or state.active_batch is None:
                    return ReviewBatchClaimResult(status=ReviewBatchClaimStatus.EMPTY)
                if state.activity is not ReviewerActivity.READY:
                    return ReviewBatchClaimResult(status=ReviewBatchClaimStatus.REJECTED)
                batch = state.active_batch.model_copy(
                    update={"lifecycle": ReviewBatchLifecycle.ACTIVE}
                )
                updated = state.model_copy(
                    update={
                        "generation": state.generation + 1,
                        "activity": ReviewerActivity.ACTIVE_REVIEW,
                        "active_batch": batch,
                    }
                )
                self._commit(self._with_state(checkpoint, updated))
                return ReviewBatchClaimResult(
                    status=ReviewBatchClaimStatus.CLAIMED,
                    batch=batch,
                    instruction=_instruction(updated),
                )
        except (OSError, ValidationError, ValueError):
            return ReviewBatchClaimResult(
                status=ReviewBatchClaimStatus.STORAGE_UNAVAILABLE
            )

    def record_inspection(
        self,
        request: ReviewInspectionRequest,
    ) -> ReviewInspectionResult:
        if type(request) is not ReviewInspectionRequest:
            return ReviewInspectionResult(status=ReviewInspectionStatus.REJECTED)
        try:
            trusted = ReviewInspectionRequest.model_validate(request, strict=True)
            with self._local_lock, _ExclusiveWindowsFileLock(self._lock_path):
                checkpoint = self._load()
                state = self._find(checkpoint, trusted.project_id, trusted.reviewer_ref)
                if (
                    state is None
                    or state.activity is not ReviewerActivity.ACTIVE_REVIEW
                    or state.active_batch is None
                    or state.active_batch.batch_id != trusted.batch_id
                ):
                    return ReviewInspectionResult(status=ReviewInspectionStatus.REJECTED)
                cluster = next(
                    (
                        item
                        for item in state.clusters
                        if item.cluster_id == trusted.cluster_id
                        and item.cluster_revision == trusted.cluster_revision
                    ),
                    None,
                )
                if cluster is None or not any(
                    item.cluster_id == trusted.cluster_id
                    and item.cluster_revision == trusted.cluster_revision
                    for item in state.active_batch.clusters
                ):
                    return ReviewInspectionResult(status=ReviewInspectionStatus.REJECTED)
                ticket = next(
                    (
                        item
                        for item in cluster.tickets
                        if item.event.ticket_ref == trusted.ticket_ref
                    ),
                    None,
                )
                if ticket is None:
                    return ReviewInspectionResult(status=ReviewInspectionStatus.REJECTED)
                if ticket.inspection is not ReviewTicketInspection.PENDING:
                    exact_duplicate = all(
                        (
                            ticket.inspection is trusted.inspection,
                            ticket.inspection_commit == trusted.inspection_commit,
                            ticket.finding_refs == trusted.finding_refs,
                        )
                    )
                    return ReviewInspectionResult(
                        status=(
                            ReviewInspectionStatus.DUPLICATE
                            if exact_duplicate
                            else ReviewInspectionStatus.REJECTED
                        )
                    )
                updated_ticket = ticket.model_copy(
                    update={
                        "inspection": trusted.inspection,
                        "inspection_commit": trusted.inspection_commit,
                        "finding_refs": trusted.finding_refs,
                    }
                )
                updated_cluster = cluster.model_copy(
                    update={
                        "tickets": tuple(
                            updated_ticket
                            if item.event.ticket_ref == trusted.ticket_ref
                            else item
                            for item in cluster.tickets
                        )
                    }
                )
                updated = state.model_copy(
                    update={
                        "generation": state.generation + 1,
                        "clusters": _replace_cluster(state, updated_cluster),
                    }
                )
                result_status = ReviewInspectionStatus.RECORDED
                if _all_batch_tickets_inspected(updated):
                    active_ids = {
                        item.cluster_id for item in updated.active_batch.clusters
                    } if updated.active_batch is not None else set()
                    clusters = tuple(
                        item.model_copy(
                            update={
                                "lifecycle": ReviewClusterLifecycle.EVALUATION_READY
                            }
                        )
                        if item.cluster_id in active_ids
                        else item
                        for item in updated.clusters
                    )
                    assert updated.active_batch is not None
                    batch = updated.active_batch.model_copy(
                        update={"lifecycle": ReviewBatchLifecycle.EVALUATION_READY}
                    )
                    updated = updated.model_copy(
                        update={"clusters": clusters, "active_batch": batch}
                    )
                    result_status = ReviewInspectionStatus.BATCH_EVALUATION_READY
                self._commit(self._with_state(checkpoint, updated))
                return ReviewInspectionResult(status=result_status)
        except (OSError, ValidationError, ValueError):
            return ReviewInspectionResult(
                status=ReviewInspectionStatus.STORAGE_UNAVAILABLE
            )

    def decide_batch(
        self,
        request: ReviewBatchDecisionRequest,
    ) -> ReviewBatchDecisionResult:
        if type(request) is not ReviewBatchDecisionRequest:
            return ReviewBatchDecisionResult(status=ReviewBatchDecisionStatus.REJECTED)
        try:
            trusted = ReviewBatchDecisionRequest.model_validate(request, strict=True)
            with self._local_lock, _ExclusiveWindowsFileLock(self._lock_path):
                checkpoint = self._load()
                state = self._find(checkpoint, trusted.project_id, trusted.reviewer_ref)
                if (
                    state is None
                    or state.activity is not ReviewerActivity.ACTIVE_REVIEW
                    or state.active_batch is None
                    or state.active_batch.batch_id != trusted.batch_id
                    or state.active_batch.lifecycle
                    is not ReviewBatchLifecycle.EVALUATION_READY
                ):
                    return ReviewBatchDecisionResult(
                        status=ReviewBatchDecisionStatus.REJECTED
                    )
                active_refs = {
                    (item.cluster_id, item.cluster_revision)
                    for item in state.active_batch.clusters
                }
                active_clusters = tuple(
                    cluster
                    for cluster in state.clusters
                    if (cluster.cluster_id, cluster.cluster_revision) in active_refs
                )
                expected = {
                    (cluster.cluster_id, cluster.cluster_revision, ticket.event.ticket_ref)
                    for cluster in active_clusters
                    for ticket in cluster.tickets
                }
                received = {
                    (
                        decision.cluster_id,
                        decision.cluster_revision,
                        decision.ticket_ref,
                    )
                    for decision in trusted.decisions
                }
                if expected != received:
                    return ReviewBatchDecisionResult(
                        status=ReviewBatchDecisionStatus.REJECTED
                    )
                decisions = {
                    (decision.cluster_id, decision.ticket_ref): decision.verdict
                    for decision in trusted.decisions
                }
                for cluster in active_clusters:
                    by_ticket = {
                        ticket.event.ticket_ref: ticket for ticket in cluster.tickets
                    }
                    for ticket_ref, ticket in by_ticket.items():
                        verdict = decisions[(cluster.cluster_id, ticket_ref)]
                        dependencies = _transitive_dependencies(cluster, ticket_ref)
                        dependency_verdicts = {
                            decisions[(cluster.cluster_id, dependency)]
                            for dependency in dependencies
                        }
                        if (
                            verdict is ReviewTicketVerdict.APPROVED
                            and (
                                ticket.inspection
                                is not ReviewTicketInspection.INSPECTED_CLEAN
                                or any(
                                    item is not ReviewTicketVerdict.APPROVED
                                    for item in dependency_verdicts
                                )
                            )
                        ):
                            return ReviewBatchDecisionResult(
                                status=ReviewBatchDecisionStatus.REJECTED
                            )
                        if (
                            verdict is ReviewTicketVerdict.BLOCKED_BY_DEPENDENCY
                            and (
                                not dependencies
                                or all(
                                    item is ReviewTicketVerdict.APPROVED
                                    for item in dependency_verdicts
                                )
                            )
                        ):
                            return ReviewBatchDecisionResult(
                                status=ReviewBatchDecisionStatus.REJECTED
                            )
                indexes = tuple(
                    ReviewClusterDecisionIndex(
                        cluster_id=cluster.cluster_id,
                        cluster_revision=cluster.cluster_revision,
                        cluster_commit=cluster.cluster_commit,
                        decision_commit=trusted.decision_commit,
                        tickets=tuple(
                            ReviewTicketDecisionIndex(
                                ticket_ref=ticket_ref,
                                verdict=decisions[(cluster.cluster_id, ticket_ref)],
                            )
                            for ticket_ref in _topological_ticket_refs(cluster)
                        ),
                    )
                    for cluster in active_clusters
                )
                active_ids = {cluster.cluster_id for cluster in active_clusters}
                remaining = tuple(
                    cluster
                    for cluster in state.clusters
                    if cluster.cluster_id not in active_ids
                )
                settled = state.model_copy(
                    update={
                        "generation": state.generation + 1,
                        "activity": ReviewerActivity.SLEEPING,
                        "clusters": remaining,
                        "decision_index": (*state.decision_index, *indexes),
                        "active_batch": None,
                        "wake_trigger_commit": None,
                    }
                )
                next_batch = _reserve_pending_batch(
                    settled,
                    trusted.decision_commit,
                    wake_pending=False,
                )
                updated = settled if next_batch is None else next_batch
                self._commit(self._with_state(checkpoint, updated))
                if next_batch is not None:
                    return ReviewBatchDecisionResult(
                        status=ReviewBatchDecisionStatus.NEXT_BATCH_READY,
                        next_instruction=_instruction(next_batch),
                    )
                return ReviewBatchDecisionResult(
                    status=ReviewBatchDecisionStatus.DECIDED
                )
        except (OSError, ValidationError, ValueError):
            return ReviewBatchDecisionResult(
                status=ReviewBatchDecisionStatus.STORAGE_UNAVAILABLE
            )

    def read_state(
        self,
        project_id: str,
        reviewer_ref: str,
    ) -> SeniorReviewInboxState | None:
        try:
            with self._local_lock, _ExclusiveWindowsFileLock(self._lock_path):
                return self._find(self._load(), project_id, reviewer_ref)
        except (OSError, ValidationError, ValueError):
            return None

__all__ = ["WindowsSeniorReviewInboxStore"]
