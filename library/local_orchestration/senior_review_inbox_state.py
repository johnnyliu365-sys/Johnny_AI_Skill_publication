"""Pure finite-state transitions for the Senior review inbox."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json

from library.workflow_router.review_inbox_contracts import (
    CommittedReviewTicketEvent,
    ReviewBatchClusterRef,
    ReviewBatchLifecycle,
    ReviewBatchRecord,
    ReviewClusterLifecycle,
    ReviewClusterReadInstruction,
    ReviewClusterRecord,
    ReviewInboxAdmissionResult,
    ReviewInboxAdmissionStatus,
    ReviewerActivity,
    ReviewTicketInspection,
    ReviewTicketReadInstruction,
    ReviewTicketRecord,
    ReviewWakeInstruction,
    SeniorReviewInboxState,
)


@dataclass(frozen=True, slots=True)
class _Mutation:
    state: SeniorReviewInboxState
    changed: bool


def _new_state(event: CommittedReviewTicketEvent) -> SeniorReviewInboxState:
    return SeniorReviewInboxState(
        project_id=event.project_id,
        reviewer_ref=event.reviewer_ref,
        generation=0,
        next_sequence=0,
        activity=ReviewerActivity.SLEEPING,
        clusters=(),
    )


def _topological_ticket_refs(cluster: ReviewClusterRecord) -> tuple[str, ...]:
    nodes = {node.ticket_ref: node.depends_on for node in cluster.dependency_graph}
    ordered: list[str] = []
    remaining = list(nodes)
    while remaining:
        ready = [
            ticket_ref
            for ticket_ref in remaining
            if all(dependency in ordered for dependency in nodes[ticket_ref])
        ]
        if not ready:
            raise ValueError("validated review graph unexpectedly contains a cycle")
        for ticket_ref in ready:
            ordered.append(ticket_ref)
            remaining.remove(ticket_ref)
    return tuple(ordered)


def _instruction(
    state: SeniorReviewInboxState,
) -> ReviewWakeInstruction:
    batch = state.active_batch
    trigger = state.wake_trigger_commit
    if batch is None or trigger is None:
        raise ValueError("review instruction requires a reserved batch")
    by_cluster = {cluster.cluster_id: cluster for cluster in state.clusters}
    cluster_instructions: list[ReviewClusterReadInstruction] = []
    for cluster_ref in batch.clusters:
        cluster = by_cluster[cluster_ref.cluster_id]
        by_ticket = {ticket.event.ticket_ref: ticket for ticket in cluster.tickets}
        tickets = tuple(
            ReviewTicketReadInstruction(
                ticket_ref=ticket_ref,
                receipt_ref=by_ticket[ticket_ref].event.receipt_ref,
                event_commit=by_ticket[ticket_ref].event.event_commit,
                source_sections=by_ticket[ticket_ref].event.source_sections,
            )
            for ticket_ref in _topological_ticket_refs(cluster)
        )
        cluster_instructions.append(
            ReviewClusterReadInstruction(
                cluster_id=cluster.cluster_id,
                cluster_revision=cluster.cluster_revision,
                cluster_commit=cluster.cluster_commit,
                dependency_graph=cluster.dependency_graph,
                tickets=tickets,
            )
        )
    return ReviewWakeInstruction(
        batch_id=batch.batch_id,
        trigger_commit=trigger,
        clusters=tuple(cluster_instructions),
    )


def _batch_id(
    state: SeniorReviewInboxState,
    refs: tuple[ReviewBatchClusterRef, ...],
    trigger_commit: str,
) -> str:
    material = json.dumps(
        {
            "generation": state.generation,
            "project_id": state.project_id,
            "reviewer_ref": state.reviewer_ref,
            "trigger_commit": trigger_commit,
            "clusters": [item.model_dump(mode="json") for item in refs],
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "batch-" + sha256(material).hexdigest()[:32]


def _reserve_pending_batch(
    state: SeniorReviewInboxState,
    trigger_commit: str,
    *,
    wake_pending: bool,
) -> SeniorReviewInboxState | None:
    pending = sorted(
        (
            cluster
            for cluster in state.clusters
            if cluster.lifecycle is ReviewClusterLifecycle.PENDING_REVIEW
        ),
        key=lambda cluster: cluster.queue_sequence
        if cluster.queue_sequence is not None
        else -1,
    )
    if not pending:
        return None
    refs = tuple(
        ReviewBatchClusterRef(
            cluster_id=cluster.cluster_id,
            cluster_revision=cluster.cluster_revision,
        )
        for cluster in pending
    )
    batch = ReviewBatchRecord(
        batch_id=_batch_id(state, refs, trigger_commit),
        clusters=refs,
        lifecycle=ReviewBatchLifecycle.RESERVED,
    )
    active_ids = {cluster.cluster_id for cluster in pending}
    clusters = tuple(
        cluster.model_copy(
            update={"lifecycle": ReviewClusterLifecycle.ACTIVE_REVIEW}
        )
        if cluster.cluster_id in active_ids
        else cluster
        for cluster in state.clusters
    )
    return state.model_copy(
        update={
            "generation": state.generation + 1,
            "activity": (
                ReviewerActivity.WAKE_PENDING
                if wake_pending
                else ReviewerActivity.READY
            ),
            "clusters": clusters,
            "active_batch": batch,
            "wake_trigger_commit": trigger_commit,
        }
    )


def _absorb_pending_into_unclaimed_batch(
    state: SeniorReviewInboxState,
) -> SeniorReviewInboxState:
    batch = state.active_batch
    if (
        batch is None
        or batch.lifecycle is not ReviewBatchLifecycle.RESERVED
        or state.activity
        not in (ReviewerActivity.WAKE_PENDING, ReviewerActivity.READY)
    ):
        return state
    pending = sorted(
        (
            cluster
            for cluster in state.clusters
            if cluster.lifecycle is ReviewClusterLifecycle.PENDING_REVIEW
        ),
        key=lambda cluster: cluster.queue_sequence
        if cluster.queue_sequence is not None
        else -1,
    )
    if not pending:
        return state
    existing_ids = {item.cluster_id for item in batch.clusters}
    additions = tuple(
        ReviewBatchClusterRef(
            cluster_id=cluster.cluster_id,
            cluster_revision=cluster.cluster_revision,
        )
        for cluster in pending
        if cluster.cluster_id not in existing_ids
    )
    if not additions:
        return state
    addition_ids = {item.cluster_id for item in additions}
    clusters = tuple(
        cluster.model_copy(
            update={"lifecycle": ReviewClusterLifecycle.ACTIVE_REVIEW}
        )
        if cluster.cluster_id in addition_ids
        else cluster
        for cluster in state.clusters
    )
    return state.model_copy(
        update={
            "generation": state.generation + 1,
            "clusters": clusters,
            "active_batch": batch.model_copy(
                update={"clusters": (*batch.clusters, *additions)}
            ),
        }
    )


def _record_for_event(event: CommittedReviewTicketEvent) -> ReviewTicketRecord:
    return ReviewTicketRecord(event=event)


def _replace_cluster(
    state: SeniorReviewInboxState,
    replacement: ReviewClusterRecord,
) -> tuple[ReviewClusterRecord, ...]:
    return tuple(
        replacement if cluster.cluster_id == replacement.cluster_id else cluster
        for cluster in state.clusters
    )


def _admit_event(
    state: SeniorReviewInboxState,
    event: CommittedReviewTicketEvent,
) -> tuple[_Mutation, ReviewInboxAdmissionResult]:
    if state.project_id != event.project_id or state.reviewer_ref != event.reviewer_ref:
        return _Mutation(state, False), ReviewInboxAdmissionResult(
            status=ReviewInboxAdmissionStatus.REJECTED
        )
    current = next(
        (cluster for cluster in state.clusters if cluster.cluster_id == event.cluster_id),
        None,
    )
    active_revised = False
    next_sequence = state.next_sequence
    if current is None:
        prior = next(
            (
                decision
                for decision in reversed(state.decision_index)
                if decision.cluster_id == event.cluster_id
            ),
            None,
        )
        graph_refs = {node.ticket_ref for node in event.dependency_graph}
        if prior is None:
            if event.previous_cluster_revision is not None:
                return _Mutation(state, False), ReviewInboxAdmissionResult(
                    status=ReviewInboxAdmissionStatus.REJECTED
                )
        elif (
            event.previous_cluster_revision != prior.cluster_revision
            or event.cluster_commit == prior.cluster_commit
            or not {ticket.ticket_ref for ticket in prior.tickets}.issubset(graph_refs)
        ):
            return _Mutation(state, False), ReviewInboxAdmissionResult(
                status=ReviewInboxAdmissionStatus.REJECTED
            )
        complete = len(event.dependency_graph) == 1
        sequence = next_sequence if complete else None
        if complete:
            next_sequence += 1
        replacement = ReviewClusterRecord(
            cluster_id=event.cluster_id,
            cluster_revision=event.cluster_revision,
            previous_cluster_revision=event.previous_cluster_revision,
            cluster_commit=event.cluster_commit,
            dependency_graph=event.dependency_graph,
            tickets=(_record_for_event(event),),
            lifecycle=(
                ReviewClusterLifecycle.PENDING_REVIEW
                if complete
                else ReviewClusterLifecycle.WAITING_DEPENDENCIES
            ),
            queue_sequence=sequence,
        )
        clusters = (*state.clusters, replacement)
    elif event.cluster_revision == current.cluster_revision:
        if (
            event.previous_cluster_revision != current.previous_cluster_revision
            or event.cluster_commit != current.cluster_commit
            or event.dependency_graph != current.dependency_graph
        ):
            return _Mutation(state, False), ReviewInboxAdmissionResult(
                status=ReviewInboxAdmissionStatus.REJECTED
            )
        existing = next(
            (
                ticket
                for ticket in current.tickets
                if ticket.event.ticket_ref == event.ticket_ref
            ),
            None,
        )
        if existing is not None:
            status = (
                ReviewInboxAdmissionStatus.DUPLICATE
                if existing.event == event
                else ReviewInboxAdmissionStatus.REJECTED
            )
            return _Mutation(state, False), ReviewInboxAdmissionResult(status=status)
        tickets = (*current.tickets, _record_for_event(event))
        complete = len(tickets) == len(current.dependency_graph)
        sequence = current.queue_sequence
        lifecycle = current.lifecycle
        if complete and lifecycle is ReviewClusterLifecycle.WAITING_DEPENDENCIES:
            sequence = next_sequence
            next_sequence += 1
            lifecycle = ReviewClusterLifecycle.PENDING_REVIEW
        replacement = current.model_copy(
            update={
                "tickets": tickets,
                "lifecycle": lifecycle,
                "queue_sequence": sequence,
            }
        )
        clusters = _replace_cluster(state, replacement)
    else:
        if event.previous_cluster_revision != current.cluster_revision:
            return _Mutation(state, False), ReviewInboxAdmissionResult(
                status=ReviewInboxAdmissionStatus.REJECTED
            )
        old_refs = {node.ticket_ref for node in current.dependency_graph}
        new_refs = {node.ticket_ref for node in event.dependency_graph}
        if not old_refs.issubset(new_refs) or event.cluster_commit == current.cluster_commit:
            return _Mutation(state, False), ReviewInboxAdmissionResult(
                status=ReviewInboxAdmissionStatus.REJECTED
            )
        retained = {
            ticket.event.ticket_ref: ticket for ticket in current.tickets
        }
        retained[event.ticket_ref] = _record_for_event(event)
        tickets = tuple(
            ReviewTicketRecord(event=retained[node.ticket_ref].event)
            for node in event.dependency_graph
            if node.ticket_ref in retained
        )
        complete = len(tickets) == len(new_refs)
        in_active_batch = (
            state.active_batch is not None
            and any(
                item.cluster_id == current.cluster_id
                for item in state.active_batch.clusters
            )
        )
        if in_active_batch and not complete:
            return _Mutation(state, False), ReviewInboxAdmissionResult(
                status=ReviewInboxAdmissionStatus.REJECTED
            )
        active_revised = in_active_batch
        if in_active_batch:
            lifecycle = ReviewClusterLifecycle.ACTIVE_REVIEW
            sequence = current.queue_sequence
        elif complete:
            lifecycle = ReviewClusterLifecycle.PENDING_REVIEW
            sequence = current.queue_sequence
            if sequence is None or current.lifecycle is ReviewClusterLifecycle.DECIDED:
                sequence = next_sequence
                next_sequence += 1
        else:
            lifecycle = ReviewClusterLifecycle.WAITING_DEPENDENCIES
            sequence = None
        replacement = ReviewClusterRecord(
            cluster_id=current.cluster_id,
            cluster_revision=event.cluster_revision,
            previous_cluster_revision=event.previous_cluster_revision,
            cluster_commit=event.cluster_commit,
            dependency_graph=event.dependency_graph,
            tickets=tickets,
            lifecycle=lifecycle,
            queue_sequence=sequence,
        )
        clusters = _replace_cluster(state, replacement)

    updated_batch = state.active_batch
    if active_revised and updated_batch is not None:
        refs = tuple(
            item.model_copy(update={"cluster_revision": event.cluster_revision})
            if item.cluster_id == event.cluster_id
            else item
            for item in updated_batch.clusters
        )
        updated_batch = updated_batch.model_copy(
            update={
                "clusters": refs,
                "lifecycle": ReviewBatchLifecycle.ACTIVE,
            }
        )
    updated = state.model_copy(
        update={
            "generation": state.generation + 1,
            "next_sequence": next_sequence,
            "clusters": clusters,
            "active_batch": updated_batch,
        }
    )
    if active_revised:
        return _Mutation(updated, True), ReviewInboxAdmissionResult(
            status=ReviewInboxAdmissionStatus.ACTIVE_BATCH_REVISED
        )
    if updated.activity in (ReviewerActivity.WAKE_PENDING, ReviewerActivity.READY):
        absorbed = _absorb_pending_into_unclaimed_batch(updated)
        return _Mutation(absorbed, True), ReviewInboxAdmissionResult(
            status=ReviewInboxAdmissionStatus.QUEUED
        )
    if updated.activity is ReviewerActivity.SLEEPING:
        reserved = _reserve_pending_batch(updated, event.event_commit, wake_pending=True)
        if reserved is not None:
            return _Mutation(reserved, True), ReviewInboxAdmissionResult(
                status=ReviewInboxAdmissionStatus.WAKE_REQUIRED,
                instruction=_instruction(reserved),
            )
    return _Mutation(updated, True), ReviewInboxAdmissionResult(
        status=ReviewInboxAdmissionStatus.QUEUED
    )


def _all_batch_tickets_inspected(state: SeniorReviewInboxState) -> bool:
    batch = state.active_batch
    if batch is None:
        return False
    active_ids = {item.cluster_id for item in batch.clusters}
    return all(
        ticket.inspection is not ReviewTicketInspection.PENDING
        for cluster in state.clusters
        if cluster.cluster_id in active_ids
        for ticket in cluster.tickets
    )


def _transitive_dependencies(
    cluster: ReviewClusterRecord,
    ticket_ref: str,
) -> set[str]:
    graph = {node.ticket_ref: node.depends_on for node in cluster.dependency_graph}
    found: set[str] = set()
    pending = list(graph[ticket_ref])
    while pending:
        dependency = pending.pop()
        if dependency in found:
            continue
        found.add(dependency)
        pending.extend(graph[dependency])
    return found
