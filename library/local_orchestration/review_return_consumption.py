"""Turn a recorded verdict into exactly one Router event, and never a second.

W2 made a verdict durable and unforgeable. This makes it actionable, and
stops precisely there: `RouterEngine.decide` is a pure function over router
state and a project profile, neither of which this layer owns. Emitting an
event is not deciding a workflow, and pretending otherwise would move
workflow authority into the orchestration layer.

**Ordering is the whole design.** The consumed marker is written *before* the
event is handed back. A crash in between loses one emission — the verdict is
still on file, visible, and re-emitting is then a deliberate act. Driving one
workflow transition twice is the failure this ordering refuses; losing an
emission that a human can see and replay is the one it accepts.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from library.workflow_router.contracts import RouterEvent, RouterEventKind
from library.workflow_router.review_inbox_contracts import ReviewTicketVerdict

from .file_lock import ExclusiveWindowsFileLock
from .johnny_root_layout import JohnnyRootLayout
from .review_return import ReviewReturnRecord, read_returns, returns_lock_path

_CONSUMED_FILE_NAME = "review-returns-consumed.jsonl"

_DECISION_EVENTS: dict[ReviewTicketVerdict, RouterEventKind] = {
    ReviewTicketVerdict.APPROVED: RouterEventKind.APPROVAL_GRANTED,
    ReviewTicketVerdict.MODIFY_AND_REOPEN: RouterEventKind.APPROVAL_DENIED,
}


class ConsumptionStatus(str, Enum):
    """Finite outcomes of one consumption attempt."""

    EMITTED = "EMITTED"
    NOTHING_PENDING = "NOTHING_PENDING"
    REFUSED = "REFUSED"


class ConsumptionFailure(str, Enum):
    """Finite reasons a pending return cannot be consumed."""

    VERDICT_NOT_A_DECISION = "VERDICT_NOT_A_DECISION"
    MARKER_UNWRITABLE = "MARKER_UNWRITABLE"


class ConsumedReturnMarker(BaseModel):
    """One durable record that a verdict has already driven the Router."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: int = Field(default=1, ge=1, le=1)
    project_id: str
    receipt_id: str
    handoff_id: str
    reviewer_ref: str
    event_id: str
    event_kind: RouterEventKind
    consumed_at_utc: str

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (
            self.project_id,
            self.receipt_id,
            self.handoff_id,
            self.reviewer_ref,
        )


def consumed_path(layout: JohnnyRootLayout) -> Path:
    return layout.queue_root / _CONSUMED_FILE_NAME


def read_consumed(layout: JohnnyRootLayout) -> tuple[ConsumedReturnMarker, ...]:
    """Every verdict already consumed; unreadable lines are skipped, not guessed."""

    path = consumed_path(layout)
    if not path.is_file():
        return ()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()
    markers: list[ConsumedReturnMarker] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            markers.append(ConsumedReturnMarker.model_validate_json(line))
        except (ValidationError, ValueError):
            continue
    return tuple(markers)


def event_id_for(record: ReviewReturnRecord) -> str:
    """Deterministic, so one verdict can never appear under two event ids."""

    return "review-return-" + "-".join(record.key)


def pending_returns(layout: JohnnyRootLayout) -> tuple[ReviewReturnRecord, ...]:
    """Recorded verdicts that have not driven the Router yet, in file order."""

    consumed = {marker.key for marker in read_consumed(layout)}
    return tuple(
        record for record in read_returns(layout) if record.key not in consumed
    )


def _mark_consumed(
    layout: JohnnyRootLayout, record: ReviewReturnRecord, event: RouterEvent
) -> bool:
    marker = ConsumedReturnMarker(
        project_id=record.project_id,
        receipt_id=record.receipt_id,
        handoff_id=record.handoff_id,
        reviewer_ref=record.reviewer_ref,
        event_id=event.event_id,
        event_kind=event.kind,
        consumed_at_utc=datetime.now(timezone.utc).isoformat(),
    )
    path = consumed_path(layout)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(marker.model_dump_json() + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        return False
    return True


def consume_next_return(
    layout: JohnnyRootLayout,
) -> tuple[ConsumptionStatus, RouterEvent | None, ConsumptionFailure | None]:
    """Emit the oldest pending verdict as one Router event, exactly once.

    Exactly-once must hold across processes, not just within one (W5): the
    pending read and the consumed-marker append are one critical section
    under the same OS-visible lock the submit path takes.
    """

    try:
        returns_lock_path(layout).parent.mkdir(parents=True, exist_ok=True)
        lock = ExclusiveWindowsFileLock(returns_lock_path(layout))
    except OSError:
        return ConsumptionStatus.REFUSED, None, ConsumptionFailure.MARKER_UNWRITABLE
    with lock:
        return _consume_locked(layout)


def _consume_locked(
    layout: JohnnyRootLayout,
) -> tuple[ConsumptionStatus, RouterEvent | None, ConsumptionFailure | None]:
    pending = pending_returns(layout)
    if not pending:
        return ConsumptionStatus.NOTHING_PENDING, None, None

    record = pending[0]
    kind = _DECISION_EVENTS.get(record.verdict)
    if kind is None:
        # Not a decision the Router can act on. Inventing a transition for it
        # would be this layer deciding workflow policy, so it stays pending
        # and unconsumed until the dependency resolves.
        return (
            ConsumptionStatus.REFUSED,
            None,
            ConsumptionFailure.VERDICT_NOT_A_DECISION,
        )

    event = RouterEvent(event_id=event_id_for(record), kind=kind)
    if not _mark_consumed(layout, record, event):
        return ConsumptionStatus.REFUSED, None, ConsumptionFailure.MARKER_UNWRITABLE
    return ConsumptionStatus.EMITTED, event, None


__all__ = [
    "ConsumedReturnMarker",
    "ConsumptionFailure",
    "ConsumptionStatus",
    "consume_next_return",
    "consumed_path",
    "event_id_for",
    "pending_returns",
    "read_consumed",
]
