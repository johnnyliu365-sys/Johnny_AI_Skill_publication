"""Strong metadata-only contracts for the receipt-bound Senior review inbox."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import (
    EvidenceDigest,
    OpaqueMetadataId,
    ProjectId,
    ReviewedCommitReference,
    RevisionDigest,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
        revalidate_instances="always",
    )


ReviewClusterId: TypeAlias = OpaqueMetadataId
ReviewBatchId: TypeAlias = OpaqueMetadataId
ReviewTicketRef: TypeAlias = OpaqueMetadataId
ReviewReceiptRef: TypeAlias = OpaqueMetadataId
ReviewTaskRef: TypeAlias = OpaqueMetadataId
ReviewHandoffId: TypeAlias = OpaqueMetadataId
ReviewRoleRef: TypeAlias = OpaqueMetadataId
ReviewArtifactRef: TypeAlias = OpaqueMetadataId
ReviewFindingRef: TypeAlias = OpaqueMetadataId
SectionAnchor: TypeAlias = Annotated[
    str,
    Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"),
]


class ReviewSourceKind(str, Enum):
    TICKET = "TICKET"
    ACCEPTANCE_CLOSURE = "ACCEPTANCE_CLOSURE"
    IMPLEMENTATION_DIFF = "IMPLEMENTATION_DIFF"
    VERIFICATION_EVIDENCE = "VERIFICATION_EVIDENCE"
    HANDOFF = "HANDOFF"


class ReviewTicketInspection(str, Enum):
    PENDING = "PENDING"
    INSPECTED_CLEAN = "INSPECTED_CLEAN"
    INSPECTED_FINDINGS = "INSPECTED_FINDINGS"


class ReviewTicketVerdict(str, Enum):
    APPROVED = "APPROVED"
    MODIFY_AND_REOPEN = "MODIFY_AND_REOPEN"
    BLOCKED_BY_DEPENDENCY = "BLOCKED_BY_DEPENDENCY"


class ReviewClusterLifecycle(str, Enum):
    WAITING_DEPENDENCIES = "WAITING_DEPENDENCIES"
    PENDING_REVIEW = "PENDING_REVIEW"
    ACTIVE_REVIEW = "ACTIVE_REVIEW"
    EVALUATION_READY = "EVALUATION_READY"
    DECIDED = "DECIDED"


class ReviewBatchLifecycle(str, Enum):
    RESERVED = "RESERVED"
    ACTIVE = "ACTIVE"
    EVALUATION_READY = "EVALUATION_READY"


class ReviewerActivity(str, Enum):
    SLEEPING = "SLEEPING"
    WAKE_PENDING = "WAKE_PENDING"
    READY = "READY"
    ACTIVE_REVIEW = "ACTIVE_REVIEW"
    HALTED = "HALTED"


class ReviewInboxAdmissionStatus(str, Enum):
    QUEUED = "QUEUED"
    WAKE_REQUIRED = "WAKE_REQUIRED"
    ACTIVE_BATCH_REVISED = "ACTIVE_BATCH_REVISED"
    DUPLICATE = "DUPLICATE"
    REJECTED = "REJECTED"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class ReviewEventResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


class ReviewWakeEffect(str, Enum):
    HOST_ACCEPTED = "HOST_ACCEPTED"
    NO_EFFECT = "NO_EFFECT"
    EFFECT_UNCERTAIN = "EFFECT_UNCERTAIN"


class ReviewWakeSettlementStatus(str, Enum):
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class ReviewBatchClaimStatus(str, Enum):
    CLAIMED = "CLAIMED"
    EMPTY = "EMPTY"
    REJECTED = "REJECTED"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class ReviewInspectionStatus(str, Enum):
    RECORDED = "RECORDED"
    BATCH_EVALUATION_READY = "BATCH_EVALUATION_READY"
    DUPLICATE = "DUPLICATE"
    REJECTED = "REJECTED"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class ReviewBatchDecisionStatus(str, Enum):
    DECIDED = "DECIDED"
    NEXT_BATCH_READY = "NEXT_BATCH_READY"
    REJECTED = "REJECTED"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class ReviewSourceSection(_StrictModel):
    """One exact committed source span; never raw source text or a filesystem path."""

    source_kind: ReviewSourceKind
    artifact_ref: ReviewArtifactRef
    source_commit: ReviewedCommitReference
    section_anchor: SectionAnchor
    content_digest: EvidenceDigest


class ReviewDependencyNode(_StrictModel):
    ticket_ref: ReviewTicketRef
    depends_on: tuple[ReviewTicketRef, ...]

    @model_validator(mode="after")
    def dependency_edges_are_unique(self) -> Self:
        if self.ticket_ref in self.depends_on:
            raise ValueError("a review ticket cannot depend on itself")
        if len(self.depends_on) != len(set(self.depends_on)):
            raise ValueError("dependency edges must be unique")
        return self


def _dependency_graph_is_acyclic(nodes: tuple[ReviewDependencyNode, ...]) -> bool:
    graph = {node.ticket_ref: node.depends_on for node in nodes}
    complete: set[str] = set()
    active: set[str] = set()

    def visit(ticket_ref: str) -> bool:
        if ticket_ref in complete:
            return True
        if ticket_ref in active:
            return False
        active.add(ticket_ref)
        for dependency in graph[ticket_ref]:
            if not visit(dependency):
                return False
        active.remove(ticket_ref)
        complete.add(ticket_ref)
        return True

    return all(visit(ticket_ref) for ticket_ref in graph)


class CommittedReviewTicketEvent(_StrictModel):
    """One terminal ticket event plus its committed review-cluster binding."""

    project_id: ProjectId
    reviewer_ref: ReviewRoleRef
    cluster_id: ReviewClusterId
    cluster_revision: RevisionDigest
    previous_cluster_revision: RevisionDigest | None
    cluster_commit: ReviewedCommitReference
    ticket_ref: ReviewTicketRef
    receipt_ref: ReviewReceiptRef
    implementation_task_ref: ReviewTaskRef
    handoff_id: ReviewHandoffId
    event_commit: ReviewedCommitReference
    dependency_graph: tuple[ReviewDependencyNode, ...] = Field(min_length=1)
    source_sections: tuple[ReviewSourceSection, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def event_is_a_complete_metadata_only_review_node(self) -> Self:
        graph_refs = tuple(node.ticket_ref for node in self.dependency_graph)
        if len(graph_refs) != len(set(graph_refs)):
            raise ValueError("cluster ticket references must be unique")
        if self.ticket_ref not in graph_refs:
            raise ValueError("event ticket must belong to its review cluster")
        graph_ref_set = set(graph_refs)
        if any(
            dependency not in graph_ref_set
            for node in self.dependency_graph
            for dependency in node.depends_on
        ):
            raise ValueError("every dependency must be contained in the cluster")
        if not _dependency_graph_is_acyclic(self.dependency_graph):
            raise ValueError("review-cluster dependency graph must be acyclic")
        if self.previous_cluster_revision == self.cluster_revision:
            raise ValueError("a cluster revision cannot supersede itself")
        kinds = tuple(section.source_kind for section in self.source_sections)
        if len(kinds) != len(set(kinds)) or set(kinds) != set(ReviewSourceKind):
            raise ValueError("review instructions require exactly one span per source kind")
        locations = tuple(
            (
                section.artifact_ref,
                section.source_commit,
                section.section_anchor,
            )
            for section in self.source_sections
        )
        if len(locations) != len(set(locations)):
            raise ValueError("review source spans must be unique")
        return self


class ReviewEventResolutionRequest(_StrictModel):
    project_id: ProjectId
    reviewer_ref: ReviewRoleRef
    ticket_ref: ReviewTicketRef
    receipt_ref: ReviewReceiptRef
    implementation_task_ref: ReviewTaskRef
    handoff_id: ReviewHandoffId
    event_commit: ReviewedCommitReference


class ReviewEventResolutionResult(_StrictModel):
    status: ReviewEventResolutionStatus
    event: CommittedReviewTicketEvent | None = None

    @model_validator(mode="after")
    def exact_resolution_shape(self) -> Self:
        if (self.status is ReviewEventResolutionStatus.RESOLVED) != (self.event is not None):
            raise ValueError("resolved review events require exactly one committed event")
        return self


class ReviewTicketRecord(_StrictModel):
    event: CommittedReviewTicketEvent
    inspection: ReviewTicketInspection = ReviewTicketInspection.PENDING
    inspection_commit: ReviewedCommitReference | None = None
    finding_refs: tuple[ReviewFindingRef, ...] = ()
    verdict: ReviewTicketVerdict | None = None
    decision_commit: ReviewedCommitReference | None = None

    @model_validator(mode="after")
    def ticket_state_is_exact(self) -> Self:
        if len(self.finding_refs) != len(set(self.finding_refs)):
            raise ValueError("review findings must be unique")
        if self.inspection is ReviewTicketInspection.PENDING:
            if self.inspection_commit is not None or self.finding_refs:
                raise ValueError("pending tickets cannot contain inspection evidence")
        elif self.inspection is ReviewTicketInspection.INSPECTED_CLEAN:
            if self.inspection_commit is None or self.finding_refs:
                raise ValueError("clean inspection requires only a commit")
        elif self.inspection_commit is None or not self.finding_refs:
            raise ValueError("finding inspection requires a commit and findings")
        if (self.verdict is None) != (self.decision_commit is None):
            raise ValueError("ticket verdict and decision commit must appear together")
        if self.verdict is ReviewTicketVerdict.APPROVED and self.inspection is not ReviewTicketInspection.INSPECTED_CLEAN:
            raise ValueError("only a clean inspected ticket may be approved")
        return self


class ReviewClusterRecord(_StrictModel):
    cluster_id: ReviewClusterId
    cluster_revision: RevisionDigest
    previous_cluster_revision: RevisionDigest | None
    cluster_commit: ReviewedCommitReference
    dependency_graph: tuple[ReviewDependencyNode, ...]
    tickets: tuple[ReviewTicketRecord, ...]
    lifecycle: ReviewClusterLifecycle
    queue_sequence: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def cluster_state_is_exact(self) -> Self:
        graph_refs = tuple(node.ticket_ref for node in self.dependency_graph)
        ticket_refs = tuple(ticket.event.ticket_ref for ticket in self.tickets)
        if len(ticket_refs) != len(set(ticket_refs)) or not set(ticket_refs).issubset(graph_refs):
            raise ValueError("cluster ticket records must be unique graph members")
        complete = set(ticket_refs) == set(graph_refs)
        waiting = self.lifecycle is ReviewClusterLifecycle.WAITING_DEPENDENCIES
        if waiting == complete:
            raise ValueError("only incomplete clusters wait for dependencies")
        queued = self.lifecycle is not ReviewClusterLifecycle.WAITING_DEPENDENCIES
        if queued != (self.queue_sequence is not None):
            raise ValueError("only ready clusters have a FIFO sequence")
        return self


class ReviewBatchClusterRef(_StrictModel):
    cluster_id: ReviewClusterId
    cluster_revision: RevisionDigest


class ReviewBatchRecord(_StrictModel):
    batch_id: ReviewBatchId
    clusters: tuple[ReviewBatchClusterRef, ...] = Field(min_length=1)
    lifecycle: ReviewBatchLifecycle

    @model_validator(mode="after")
    def batch_clusters_are_unique(self) -> Self:
        ids = tuple(item.cluster_id for item in self.clusters)
        if len(ids) != len(set(ids)):
            raise ValueError("review batch clusters must be unique")
        return self


class ReviewTicketReadInstruction(_StrictModel):
    ticket_ref: ReviewTicketRef
    receipt_ref: ReviewReceiptRef
    event_commit: ReviewedCommitReference
    source_sections: tuple[ReviewSourceSection, ...]


class ReviewClusterReadInstruction(_StrictModel):
    cluster_id: ReviewClusterId
    cluster_revision: RevisionDigest
    cluster_commit: ReviewedCommitReference
    dependency_graph: tuple[ReviewDependencyNode, ...]
    tickets: tuple[ReviewTicketReadInstruction, ...]


class ReviewWakeInstruction(_StrictModel):
    """Identifiers-only read plan sent to the existing Senior task."""

    batch_id: ReviewBatchId
    trigger_commit: ReviewedCommitReference
    clusters: tuple[ReviewClusterReadInstruction, ...] = Field(min_length=1)

    def render_identifiers_only_lines(self) -> tuple[str, ...]:
        lines: list[str] = [
            "review_batch_id=" + self.batch_id,
            "review_trigger_commit=" + self.trigger_commit,
        ]
        for cluster in self.clusters:
            lines.append(
                "review_cluster="
                + "|".join(
                    (
                        cluster.cluster_id,
                        cluster.cluster_revision,
                        cluster.cluster_commit,
                    )
                )
            )
            for node in cluster.dependency_graph:
                lines.append(
                    "review_dependency="
                    + cluster.cluster_id
                    + "|"
                    + node.ticket_ref
                    + "|"
                    + ",".join(node.depends_on)
                )
            for ticket in cluster.tickets:
                for section in ticket.source_sections:
                    lines.append(
                        "review_read="
                        + "|".join(
                            (
                                cluster.cluster_id,
                                ticket.ticket_ref,
                                ticket.receipt_ref,
                                ticket.event_commit,
                                section.source_kind.value,
                                section.artifact_ref,
                                section.source_commit,
                                section.section_anchor,
                                section.content_digest,
                            )
                        )
                    )
        return tuple(lines)


class ReviewTicketDecisionIndex(_StrictModel):
    ticket_ref: ReviewTicketRef
    verdict: ReviewTicketVerdict


class ReviewClusterDecisionIndex(_StrictModel):
    """Compact trace retained after bulky per-ticket read instructions are released."""

    cluster_id: ReviewClusterId
    cluster_revision: RevisionDigest
    cluster_commit: ReviewedCommitReference
    decision_commit: ReviewedCommitReference
    tickets: tuple[ReviewTicketDecisionIndex, ...] = Field(min_length=1)


class SeniorReviewInboxState(_StrictModel):
    project_id: ProjectId
    reviewer_ref: ReviewRoleRef
    generation: int = Field(ge=0)
    next_sequence: int = Field(ge=0)
    activity: ReviewerActivity
    clusters: tuple[ReviewClusterRecord, ...]
    decision_index: tuple[ReviewClusterDecisionIndex, ...] = ()
    active_batch: ReviewBatchRecord | None = None
    wake_trigger_commit: ReviewedCommitReference | None = None

    @model_validator(mode="after")
    def inbox_shape_is_exact(self) -> Self:
        ids = tuple(cluster.cluster_id for cluster in self.clusters)
        if len(ids) != len(set(ids)):
            raise ValueError("inbox cluster IDs must be unique")
        decisions = tuple(
            (item.cluster_id, item.cluster_revision) for item in self.decision_index
        )
        if len(decisions) != len(set(decisions)):
            raise ValueError("settled review indexes must be unique")
        has_batch = self.active_batch is not None
        if self.activity in (
            ReviewerActivity.WAKE_PENDING,
            ReviewerActivity.READY,
            ReviewerActivity.ACTIVE_REVIEW,
        ):
            if not has_batch or self.wake_trigger_commit is None:
                raise ValueError("active reviewer states require a committed batch trigger")
        elif has_batch or self.wake_trigger_commit is not None:
            raise ValueError("sleeping or halted inbox cannot retain an active batch")
        if self.active_batch is not None:
            by_id = {cluster.cluster_id: cluster for cluster in self.clusters}
            for item in self.active_batch.clusters:
                cluster = by_id.get(item.cluster_id)
                if cluster is None or cluster.cluster_revision != item.cluster_revision:
                    raise ValueError("batch cluster revision must match inbox state")
        return self


class ReviewInboxAdmissionResult(_StrictModel):
    status: ReviewInboxAdmissionStatus
    instruction: ReviewWakeInstruction | None = None

    @model_validator(mode="after")
    def wake_requires_instruction(self) -> Self:
        if (self.status is ReviewInboxAdmissionStatus.WAKE_REQUIRED) != (
            self.instruction is not None
        ):
            raise ValueError("only wake-required admission returns an instruction")
        return self


class ReviewWakeSettlementRequest(_StrictModel):
    project_id: ProjectId
    reviewer_ref: ReviewRoleRef
    batch_id: ReviewBatchId
    trigger_commit: ReviewedCommitReference
    effect: ReviewWakeEffect


class ReviewWakeSettlementResult(_StrictModel):
    status: ReviewWakeSettlementStatus


class ReviewBatchClaimRequest(_StrictModel):
    project_id: ProjectId
    reviewer_ref: ReviewRoleRef


class ReviewBatchClaimResult(_StrictModel):
    status: ReviewBatchClaimStatus
    batch: ReviewBatchRecord | None = None
    instruction: ReviewWakeInstruction | None = None

    @model_validator(mode="after")
    def claimed_batch_is_exact(self) -> Self:
        claimed = self.status is ReviewBatchClaimStatus.CLAIMED
        if claimed != (self.batch is not None and self.instruction is not None):
            raise ValueError("claimed review requires a batch and exact read instruction")
        return self


class ReviewInspectionRequest(_StrictModel):
    project_id: ProjectId
    reviewer_ref: ReviewRoleRef
    batch_id: ReviewBatchId
    cluster_id: ReviewClusterId
    cluster_revision: RevisionDigest
    ticket_ref: ReviewTicketRef
    inspection: ReviewTicketInspection
    inspection_commit: ReviewedCommitReference
    finding_refs: tuple[ReviewFindingRef, ...]

    @model_validator(mode="after")
    def inspection_is_terminal_observation(self) -> Self:
        if self.inspection is ReviewTicketInspection.PENDING:
            raise ValueError("a recorded inspection cannot remain pending")
        if len(self.finding_refs) != len(set(self.finding_refs)):
            raise ValueError("finding references must be unique")
        has_findings = self.inspection is ReviewTicketInspection.INSPECTED_FINDINGS
        if has_findings != bool(self.finding_refs):
            raise ValueError("finding status and references must agree")
        return self


class ReviewInspectionResult(_StrictModel):
    status: ReviewInspectionStatus


class ReviewTicketDecision(_StrictModel):
    cluster_id: ReviewClusterId
    cluster_revision: RevisionDigest
    ticket_ref: ReviewTicketRef
    verdict: ReviewTicketVerdict


class ReviewBatchDecisionRequest(_StrictModel):
    project_id: ProjectId
    reviewer_ref: ReviewRoleRef
    batch_id: ReviewBatchId
    decision_commit: ReviewedCommitReference
    decisions: tuple[ReviewTicketDecision, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def ticket_decisions_are_unique(self) -> Self:
        keys = tuple(
            (decision.cluster_id, decision.ticket_ref) for decision in self.decisions
        )
        if len(keys) != len(set(keys)):
            raise ValueError("each batch ticket requires one decision")
        return self


class ReviewBatchDecisionResult(_StrictModel):
    status: ReviewBatchDecisionStatus
    next_instruction: ReviewWakeInstruction | None = None

    @model_validator(mode="after")
    def next_batch_requires_instruction(self) -> Self:
        if (self.status is ReviewBatchDecisionStatus.NEXT_BATCH_READY) != (
            self.next_instruction is not None
        ):
            raise ValueError("only a ready next batch returns read instructions")
        return self


__all__ = [
    "CommittedReviewTicketEvent",
    "ReviewBatchClaimRequest",
    "ReviewBatchClaimResult",
    "ReviewBatchClaimStatus",
    "ReviewBatchClusterRef",
    "ReviewBatchDecisionRequest",
    "ReviewBatchDecisionResult",
    "ReviewBatchDecisionStatus",
    "ReviewBatchId",
    "ReviewBatchLifecycle",
    "ReviewBatchRecord",
    "ReviewClusterId",
    "ReviewClusterDecisionIndex",
    "ReviewClusterLifecycle",
    "ReviewClusterReadInstruction",
    "ReviewClusterRecord",
    "ReviewDependencyNode",
    "ReviewEventResolutionRequest",
    "ReviewEventResolutionResult",
    "ReviewEventResolutionStatus",
    "ReviewInboxAdmissionResult",
    "ReviewInboxAdmissionStatus",
    "ReviewerActivity",
    "ReviewInspectionRequest",
    "ReviewInspectionResult",
    "ReviewInspectionStatus",
    "ReviewSourceKind",
    "ReviewSourceSection",
    "ReviewTicketDecision",
    "ReviewTicketDecisionIndex",
    "ReviewTicketInspection",
    "ReviewTicketReadInstruction",
    "ReviewTicketRecord",
    "ReviewTicketVerdict",
    "ReviewWakeEffect",
    "ReviewWakeInstruction",
    "ReviewWakeSettlementRequest",
    "ReviewWakeSettlementResult",
    "ReviewWakeSettlementStatus",
    "SeniorReviewInboxState",
]
