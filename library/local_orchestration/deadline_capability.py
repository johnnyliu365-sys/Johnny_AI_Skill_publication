"""Probe the host's one-shot monotonic deadline, never assume it.

`MonotonicDeadlineCapabilityProof` carries `state=PROVEN`, and supervision
admits a dispatch on the strength of that field. A builder that accepted the
proof from its caller would let a subscription assert its own capability, the
same defect the E8 review closed for receipt issuance. This module therefore
schedules a real one-shot timer against a monotonic clock and reports PROVEN
only when that timer actually fired late enough to have been honoured.
"""

from __future__ import annotations

import hashlib
import threading
import time
from enum import Enum

from library.workflow_router.live_dispatch_contracts import TicketReceipt
from library.workflow_router.role_wake_contracts import (
    DeadlineCapabilityState,
    MonotonicDeadlineCapabilityProof,
)

_PROBE_SECONDS = 0.05
_PROBE_TOLERANCE = 0.8
_PROBE_TIMEOUT = 5.0


class DeadlineProbeStatus(str, Enum):
    """Finite outcomes of one deadline-capability probe."""

    PROVEN = "PROVEN"
    UNAVAILABLE = "UNAVAILABLE"


def _capability_revision() -> str:
    """Identify the probed implementation, not the caller's claim."""

    digest = hashlib.sha256(
        b"johnny-monotonic-one-shot-threading-timer-v1"
    ).hexdigest()
    return f"rev-{digest[:32]}"


def _one_shot_fires() -> bool:
    fired = threading.Event()
    started = time.monotonic()
    timer = threading.Timer(_PROBE_SECONDS, fired.set)
    timer.daemon = True
    timer.start()
    try:
        if not fired.wait(_PROBE_TIMEOUT):
            return False
    finally:
        timer.cancel()
    # A timer that "fires" before its own deadline is not a deadline.
    return (time.monotonic() - started) >= _PROBE_SECONDS * _PROBE_TOLERANCE


def probe_deadline_capability(
    receipt: TicketReceipt, implementation_task_ref: str
) -> tuple[DeadlineProbeStatus, MonotonicDeadlineCapabilityProof | None]:
    """Run a real one-shot timer and report only what it proved."""

    try:
        proven = _one_shot_fires()
    except (RuntimeError, OSError):
        proven = False
    if not proven:
        return DeadlineProbeStatus.UNAVAILABLE, None
    return (
        DeadlineProbeStatus.PROVEN,
        MonotonicDeadlineCapabilityProof(
            project_id=receipt.project_id,
            ticket_ref=receipt.ticket_reference,
            router_receipt_ref=receipt.receipt_id,
            implementation_task_ref=implementation_task_ref,
            capability_revision=_capability_revision(),
            state=DeadlineCapabilityState.PROVEN,
            one_shot_supported=True,
            recurring_callback_required=False,
            evidence_refs=("evidence-monotonic-one-shot-probe",),
        ),
    )


__all__ = [
    "DeadlineProbeStatus",
    "probe_deadline_capability",
]
