"""Deterministic local replay of typed timeline events and immutable audit."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from typing import TypeAlias


@dataclass(frozen=True, slots=True)
class TimelineEventId:
    """A caller-provided opaque identifier for one local timeline event."""

    value: str

    def __post_init__(self) -> None:
        _require_safe_identifier(
            value=self.value,
            name="timeline event identifier",
            maximum_length=128,
        )


@dataclass(frozen=True, slots=True)
class UnknownEventCode:
    """A safe event code preserved when the timeline does not recognize it."""

    value: str

    def __post_init__(self) -> None:
        _require_safe_identifier(
            value=self.value,
            name="unknown event code",
            maximum_length=64,
        )


@dataclass(frozen=True, slots=True)
class TimelineAuditSequence:
    """A one-based immutable sequence number for local audit entries."""

    value: int

    def __post_init__(self) -> None:
        if not isinstance(self.value, int) or isinstance(self.value, bool):
            raise TypeError("timeline audit sequence must be an integer")
        if self.value < 1:
            raise ValueError("timeline audit sequence must be positive")


@dataclass(frozen=True, slots=True)
class TimelineOutputHash:
    """A SHA-256 fingerprint of a replay's canonical configuration and audit."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TypeError("timeline output hash must be a string")
        if len(self.value) != 64:
            raise ValueError("timeline output hash must have 64 hexadecimal characters")
        allowed_characters = "0123456789abcdef"
        if any(character not in allowed_characters for character in self.value):
            raise ValueError("timeline output hash must use lowercase hexadecimal")


class TimelineState(str, Enum):
    """The complete generic state space supported by this local replay core."""

    NOT_STARTED = "not_started"
    ACTIVE = "active"
    FINISHED = "finished"


class TimelineEventKind(str, Enum):
    """Recognized generic events with no project-specific dispatch meaning."""

    START = "start"
    ADVANCE = "advance"
    FINISH = "finish"


class TimelineAuditOutcome(str, Enum):
    """The three possible outcomes for a replayed event."""

    APPLIED = "applied"
    UNRESOLVED = "unresolved"
    CONFLICT = "conflict"


class TimelineAuditReason(str, Enum):
    """Finite reasons used only when an event cannot be applied."""

    UNKNOWN_EVENT = "unknown_event"
    INVALID_TRANSITION = "invalid_transition"
    DUPLICATE_EVENT_ID = "duplicate_event_id"


@dataclass(frozen=True, slots=True)
class KnownTimelineEvent:
    """A recognized event that may transition the generic timeline state."""

    event_id: TimelineEventId
    kind: TimelineEventKind

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, TimelineEventId):
            raise TypeError("event_id must be a TimelineEventId")
        if not isinstance(self.kind, TimelineEventKind):
            raise TypeError("kind must be a TimelineEventKind")


@dataclass(frozen=True, slots=True)
class UnknownTimelineEvent:
    """An unsupported event preserved without fabricating a state transition."""

    event_id: TimelineEventId
    code: UnknownEventCode

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, TimelineEventId):
            raise TypeError("event_id must be a TimelineEventId")
        if not isinstance(self.code, UnknownEventCode):
            raise TypeError("code must be an UnknownEventCode")


TimelineInputEvent: TypeAlias = KnownTimelineEvent | UnknownTimelineEvent
TimelineEventDescriptor: TypeAlias = TimelineEventKind | UnknownEventCode


@dataclass(frozen=True, slots=True)
class TimelineConfiguration:
    """Explicit replay settings with no implicit environment or clock inputs."""

    initial_state: TimelineState

    def __post_init__(self) -> None:
        if not isinstance(self.initial_state, TimelineState):
            raise TypeError("initial_state must be a TimelineState")


@dataclass(frozen=True, slots=True)
class TimelineAuditEntry:
    """A canonical audit fact for one input event and its replay outcome."""

    sequence: TimelineAuditSequence
    event_id: TimelineEventId
    event_descriptor: TimelineEventDescriptor
    state_before: TimelineState
    state_after: TimelineState
    outcome: TimelineAuditOutcome
    reason: TimelineAuditReason | None

    def __post_init__(self) -> None:
        if not isinstance(self.sequence, TimelineAuditSequence):
            raise TypeError("sequence must be a TimelineAuditSequence")
        if not isinstance(self.event_id, TimelineEventId):
            raise TypeError("event_id must be a TimelineEventId")
        if not isinstance(self.event_descriptor, (TimelineEventKind, UnknownEventCode)):
            raise TypeError(
                "event_descriptor must be a TimelineEventKind or UnknownEventCode"
            )
        if not isinstance(self.state_before, TimelineState):
            raise TypeError("state_before must be a TimelineState")
        if not isinstance(self.state_after, TimelineState):
            raise TypeError("state_after must be a TimelineState")
        if not isinstance(self.outcome, TimelineAuditOutcome):
            raise TypeError("outcome must be a TimelineAuditOutcome")
        if self.reason is not None and not isinstance(
            self.reason, TimelineAuditReason
        ):
            raise TypeError("reason must be a TimelineAuditReason or None")
        if self.outcome is TimelineAuditOutcome.APPLIED and self.reason is not None:
            raise ValueError("applied audit entries must not have a rejection reason")
        if self.outcome is not TimelineAuditOutcome.APPLIED and self.reason is None:
            raise ValueError("unresolved or conflict entries must have a reason")


@dataclass(frozen=True, slots=True)
class TimelineReplaySummary:
    """A typed count summary of an immutable replay audit."""

    final_state: TimelineState
    applied_count: int
    unresolved_count: int
    conflict_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.final_state, TimelineState):
            raise TypeError("final_state must be a TimelineState")
        _require_non_negative_count(self.applied_count, "applied_count")
        _require_non_negative_count(self.unresolved_count, "unresolved_count")
        _require_non_negative_count(self.conflict_count, "conflict_count")


@dataclass(frozen=True, slots=True)
class TimelineReplay:
    """The deterministic output of replaying one complete event sequence."""

    configuration: TimelineConfiguration
    final_state: TimelineState
    audit_entries: tuple[TimelineAuditEntry, ...]
    summary: TimelineReplaySummary
    output_hash: TimelineOutputHash

    def __post_init__(self) -> None:
        if not isinstance(self.configuration, TimelineConfiguration):
            raise TypeError("configuration must be a TimelineConfiguration")
        if not isinstance(self.final_state, TimelineState):
            raise TypeError("final_state must be a TimelineState")
        if not isinstance(self.audit_entries, tuple):
            raise TypeError("audit_entries must be a tuple")
        if not isinstance(self.summary, TimelineReplaySummary):
            raise TypeError("summary must be a TimelineReplaySummary")
        if not isinstance(self.output_hash, TimelineOutputHash):
            raise TypeError("output_hash must be a TimelineOutputHash")
        _require_contiguous_audit_entries(self.audit_entries)
        expected_summary = _summary_for(
            final_state=self.final_state,
            audit_entries=self.audit_entries,
        )
        if self.summary != expected_summary:
            raise ValueError("summary must match the final state and audit entries")
        expected_hash = _hash_for(
            configuration=self.configuration,
            final_state=self.final_state,
            audit_entries=self.audit_entries,
        )
        if self.output_hash != expected_hash:
            raise ValueError("output_hash must match the canonical replay output")


def replay_timeline(
    configuration: TimelineConfiguration,
    events: tuple[TimelineInputEvent, ...],
) -> TimelineReplay:
    """Replay typed inputs once in order without a clock, I/O or mutable state."""
    if not isinstance(configuration, TimelineConfiguration):
        raise TypeError("configuration must be a TimelineConfiguration")
    if not isinstance(events, tuple):
        raise TypeError("events must be a tuple")
    current_state = configuration.initial_state
    audit_entry_buffer: list[TimelineAuditEntry] = []
    seen_event_ids: set[TimelineEventId] = set()
    event: TimelineInputEvent
    for event in events:
        if not isinstance(event, (KnownTimelineEvent, UnknownTimelineEvent)):
            raise TypeError(
                "events must contain KnownTimelineEvent or UnknownTimelineEvent values"
            )
        entry, current_state = _replay_one_event(
            event=event,
            state=current_state,
            sequence=TimelineAuditSequence(value=len(audit_entry_buffer) + 1),
            seen_event_ids=seen_event_ids,
        )
        audit_entry_buffer.append(entry)
        seen_event_ids.add(event.event_id)
    audit_entries = tuple(audit_entry_buffer)
    summary = _summary_for(final_state=current_state, audit_entries=audit_entries)
    output_hash = _hash_for(
        configuration=configuration,
        final_state=current_state,
        audit_entries=audit_entries,
    )
    return TimelineReplay(
        configuration=configuration,
        final_state=current_state,
        audit_entries=audit_entries,
        summary=summary,
        output_hash=output_hash,
    )


def _replay_one_event(
    event: TimelineInputEvent,
    state: TimelineState,
    sequence: TimelineAuditSequence,
    seen_event_ids: set[TimelineEventId],
) -> tuple[TimelineAuditEntry, TimelineState]:
    if event.event_id in seen_event_ids:
        return (
            _audit_entry(
                sequence=sequence,
                event=event,
                state_before=state,
                state_after=state,
                outcome=TimelineAuditOutcome.CONFLICT,
                reason=TimelineAuditReason.DUPLICATE_EVENT_ID,
            ),
            state,
        )
    if isinstance(event, UnknownTimelineEvent):
        return (
            _audit_entry(
                sequence=sequence,
                event=event,
                state_before=state,
                state_after=state,
                outcome=TimelineAuditOutcome.UNRESOLVED,
                reason=TimelineAuditReason.UNKNOWN_EVENT,
            ),
            state,
        )
    next_state = _next_state(state=state, event_kind=event.kind)
    if next_state is None:
        return (
            _audit_entry(
                sequence=sequence,
                event=event,
                state_before=state,
                state_after=state,
                outcome=TimelineAuditOutcome.CONFLICT,
                reason=TimelineAuditReason.INVALID_TRANSITION,
            ),
            state,
        )
    return (
        _audit_entry(
            sequence=sequence,
            event=event,
            state_before=state,
            state_after=next_state,
            outcome=TimelineAuditOutcome.APPLIED,
            reason=None,
        ),
        next_state,
    )


def _next_state(
    state: TimelineState, event_kind: TimelineEventKind
) -> TimelineState | None:
    if state is TimelineState.NOT_STARTED and event_kind is TimelineEventKind.START:
        return TimelineState.ACTIVE
    if state is TimelineState.ACTIVE and event_kind is TimelineEventKind.ADVANCE:
        return TimelineState.ACTIVE
    if state is TimelineState.ACTIVE and event_kind is TimelineEventKind.FINISH:
        return TimelineState.FINISHED
    return None


def _audit_entry(
    sequence: TimelineAuditSequence,
    event: TimelineInputEvent,
    state_before: TimelineState,
    state_after: TimelineState,
    outcome: TimelineAuditOutcome,
    reason: TimelineAuditReason | None,
) -> TimelineAuditEntry:
    return TimelineAuditEntry(
        sequence=sequence,
        event_id=event.event_id,
        event_descriptor=_event_descriptor(event),
        state_before=state_before,
        state_after=state_after,
        outcome=outcome,
        reason=reason,
    )


def _event_descriptor(event: TimelineInputEvent) -> TimelineEventDescriptor:
    if isinstance(event, KnownTimelineEvent):
        return event.kind
    return event.code


def _summary_for(
    final_state: TimelineState,
    audit_entries: tuple[TimelineAuditEntry, ...],
) -> TimelineReplaySummary:
    applied_count = 0
    unresolved_count = 0
    conflict_count = 0
    entry: TimelineAuditEntry
    for entry in audit_entries:
        if entry.outcome is TimelineAuditOutcome.APPLIED:
            applied_count += 1
        elif entry.outcome is TimelineAuditOutcome.UNRESOLVED:
            unresolved_count += 1
        else:
            conflict_count += 1
    return TimelineReplaySummary(
        final_state=final_state,
        applied_count=applied_count,
        unresolved_count=unresolved_count,
        conflict_count=conflict_count,
    )


def _hash_for(
    configuration: TimelineConfiguration,
    final_state: TimelineState,
    audit_entries: tuple[TimelineAuditEntry, ...],
) -> TimelineOutputHash:
    canonical_rows = (
        f"configuration={configuration.initial_state.value}",
        f"final_state={final_state.value}",
    ) + tuple(_canonical_audit_row(entry) for entry in audit_entries)
    canonical_output = "\n".join(canonical_rows)
    return TimelineOutputHash(value=sha256(canonical_output.encode("utf-8")).hexdigest())


def _canonical_audit_row(entry: TimelineAuditEntry) -> str:
    reason_value = "none" if entry.reason is None else entry.reason.value
    descriptor_value = _descriptor_value(entry.event_descriptor)
    return "|".join(
        (
            str(entry.sequence.value),
            entry.event_id.value,
            descriptor_value,
            entry.state_before.value,
            entry.state_after.value,
            entry.outcome.value,
            reason_value,
        )
    )


def _descriptor_value(descriptor: TimelineEventDescriptor) -> str:
    if isinstance(descriptor, TimelineEventKind):
        return descriptor.value
    return descriptor.value


def _require_non_negative_count(value: int, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must not be negative")


def _require_safe_identifier(value: str, name: str, maximum_length: int) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value or len(value) > maximum_length:
        raise ValueError(f"{name} must contain 1 to {maximum_length} characters")
    safe_characters = "abcdefghijklmnopqrstuvwxyz0123456789-_"
    if any(character not in safe_characters for character in value):
        raise ValueError(
            f"{name} must use lowercase letters, digits, hyphen or underscore only"
        )


def _require_contiguous_audit_entries(
    audit_entries: tuple[TimelineAuditEntry, ...],
) -> None:
    expected_sequence = 1
    entry: TimelineAuditEntry
    for entry in audit_entries:
        if not isinstance(entry, TimelineAuditEntry):
            raise TypeError("audit_entries must contain TimelineAuditEntry values")
        if entry.sequence.value != expected_sequence:
            raise ValueError("audit sequence must be contiguous and start at one")
        expected_sequence += 1
