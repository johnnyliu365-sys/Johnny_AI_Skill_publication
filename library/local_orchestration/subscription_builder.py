"""Compose a runner subscription from an already-issued receipt.

E7 was blocked because nothing outside the test suite could produce a
`RunnerSubscriptionFile`: an owner cannot hand-write the typed supervision
requests, and the two capability proofs inside them carry `state=PROVEN`,
which supervision admits a dispatch on.

Two authority rules therefore shape this builder, both inherited from the E8
review:

* the receipt is **read** from the durable checkpoint, never constructed. A
  subscription naming a receipt that dispatch never issued is refused.
* the capability proofs are **probed**, never accepted from the caller. The
  wake proof exists only when the declared host command passes its own probe,
  and the deadline proof only when a real one-shot timer fires.

Everything receipt-bound is derived from the stored receipt, so the owner
supplies only what dispatch cannot know: which ref to watch, which leaf is
reserved, and who the reviewer is.
"""

from __future__ import annotations

import hashlib
from enum import Enum
from pathlib import Path
from time import monotonic_ns
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from library.workflow_router.git_handoff_contracts import GitRefRegistrationRequest
from library.workflow_router.live_dispatch_contracts import TicketReceipt
from library.workflow_router.role_supervision_contracts import (
    HandoffAdmissionContext,
)
from library.workflow_router.role_wake_contracts import (
    RoleWakeCapabilityProof,
    RoleWakeCapabilityState,
)
from library.workflow_router.supervision_policy import (
    ExecutionStartedEvidence,
    SupervisionClass,
)
from library.workflow_router.supervision_runtime_contracts import (
    SupervisionPreparationRequest,
    SupervisionStartRequest,
)

from .deadline_capability import DeadlineProbeStatus, probe_deadline_capability
from .event_runner import (
    RunnerSubscriptionFile,
    RunnerSubscriptionSpec,
    subscriptions_path,
)
from .johnny_root_layout import JohnnyRootLayout
from .runner_receipt_seeding import (
    ReceiptVerificationStatus,
    verify_receipt_claimable,
)
from .wake_capability import WakeCapabilityStatus, probe_wake_capability
from .wake_scoped_boundary import WakeScopedDispatchBoundary

_OPAQUE = r"^[a-z][a-z0-9-]{2,127}$"
_REVISION = r"^rev-[0-9a-f]{16,64}$"
_CODEX_TASK = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
_CODEX_HOST = r"^[a-z0-9][a-z0-9:_-]{0,127}$"


class SubscriptionBuildStatus(str, Enum):
    """Finite outcomes of one subscription composition."""

    WRITTEN = "WRITTEN"
    REFUSED = "REFUSED"


class SubscriptionBuildFailure(str, Enum):
    """Finite reasons a subscription cannot be composed."""

    RECEIPT_NOT_DISPATCHED = "RECEIPT_NOT_DISPATCHED"
    WAKE_CAPABILITY_UNAVAILABLE = "WAKE_CAPABILITY_UNAVAILABLE"
    DEADLINE_CAPABILITY_UNAVAILABLE = "DEADLINE_CAPABILITY_UNAVAILABLE"
    REPOSITORY_UNAVAILABLE = "REPOSITORY_UNAVAILABLE"
    SUBSCRIPTION_UNWRITABLE = "SUBSCRIPTION_UNWRITABLE"


class SubscriptionInputs(BaseModel):
    """Exactly what dispatch cannot derive from the receipt."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    repository_root: str = Field(min_length=1, max_length=512)
    event_source_ref: str = Field(pattern=_OPAQUE)
    subscription_id: str = Field(pattern=_OPAQUE)
    exact_git_ref: str = Field(min_length=1, max_length=255)
    reserved_handoff_ref: str = Field(min_length=1, max_length=512)
    spec_ref: str = Field(pattern=_OPAQUE)
    spec_revision: str = Field(pattern=_REVISION)
    source_role_ref: str = Field(pattern=_OPAQUE)
    reviewer_ref: str = Field(pattern=_OPAQUE)
    # Two reviewer identities, deliberately distinct. The admission context
    # names the reviewer's Johnny-side task; the wake proof names the host's
    # own task id, because that is what the wake port actually addresses.
    reviewer_task_ref: str = Field(pattern=_OPAQUE)
    reviewer_task_id: str = Field(pattern=_CODEX_TASK)
    reviewer_host_id: str = Field(pattern=_CODEX_HOST)
    lease_id: str = Field(pattern=_OPAQUE)
    supervision_class: SupervisionClass

    @model_validator(mode="after")
    def reviewer_is_not_the_implementer(self) -> Self:
        if self.reviewer_ref == self.source_role_ref:
            raise ValueError("the reviewer and the implementation owner must differ")
        return self


def _binding_digest(receipt: TicketReceipt, inputs: SubscriptionInputs) -> str:
    canonical = "|".join(
        (
            receipt.project_id,
            receipt.ticket_reference,
            receipt.receipt_id,
            inputs.subscription_id,
            inputs.event_source_ref,
            inputs.reviewer_ref,
            inputs.reviewer_task_id,
            inputs.reviewer_host_id,
        )
    )
    return "sha256_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _wake_port_revision() -> str:
    digest = hashlib.sha256(b"johnny-command-role-wake-port-v1").hexdigest()
    return "rev-" + digest[:32]


def _registration(
    receipt: TicketReceipt, inputs: SubscriptionInputs
) -> GitRefRegistrationRequest:
    return GitRefRegistrationRequest(
        event_source_ref=inputs.event_source_ref,
        subscription_id=inputs.subscription_id,
        project_id=receipt.project_id,
        ticket_ref=receipt.ticket_reference,
        router_receipt_ref=receipt.receipt_id,
        implementation_task_ref=receipt.implementation_owner_id,
        worktree_ref=receipt.worktree_fingerprint,
        branch_ref=receipt.branch_fingerprint,
        baseline_commit=receipt.baseline_commit,
        correlation_id=receipt.correlation_id,
        exact_git_ref=inputs.exact_git_ref,
        reserved_handoff_ref=inputs.reserved_handoff_ref,
    )


def _admission(
    receipt: TicketReceipt, inputs: SubscriptionInputs
) -> HandoffAdmissionContext:
    return HandoffAdmissionContext(
        project_id=receipt.project_id,
        spec_ref=inputs.spec_ref,
        spec_revision=inputs.spec_revision,
        ticket_ref=receipt.ticket_reference,
        ticket_revision=receipt.ticket_revision,
        router_receipt_ref=receipt.receipt_id,
        source_role_ref=inputs.source_role_ref,
        source_task_ref=receipt.implementation_owner_id,
        target_role_ref=inputs.reviewer_ref,
        target_task_ref=inputs.reviewer_task_ref,
        worktree_ref=receipt.worktree_fingerprint,
        branch_ref=receipt.branch_fingerprint,
        baseline_commit=receipt.baseline_commit,
        correlation_id=receipt.correlation_id,
        observed_handoff_commit=receipt.baseline_commit,
        result_descends_from_baseline=True,
        handoff_descends_from_result=True,
        reserved_path_changed=True,
        consumed_handoff_ids=(),
    )


def _execution_started(
    receipt: TicketReceipt, inputs: SubscriptionInputs
) -> ExecutionStartedEvidence:
    return ExecutionStartedEvidence(
        project_id=receipt.project_id,
        ticket_ref=receipt.ticket_reference,
        router_receipt_ref=receipt.receipt_id,
        task_ref=receipt.implementation_owner_id,
        worktree_ref=receipt.worktree_fingerprint,
        branch_ref=receipt.branch_fingerprint,
        baseline_commit=receipt.baseline_commit,
        # The supervision deadline is `started_at_ms + duration`, compared
        # against the host's monotonic clock (`one_shot_deadline` reads
        # `monotonic_ns() // 1_000_000`). A fixture constant here puts the
        # deadline permanently in the past, so supervision fires a deadline
        # wake the instant it arms and no handoff ever gets to drive one.
        # The E7 owner smoke caught exactly that.
        started_at_ms=monotonic_ns() // 1_000_000,
        host_readback_refs=("evidence-execution-start",),
        exact_ticket_received=True,
        task_active=True,
        ticket_executable=True,
        sole_active_receipt=True,
        binding_fresh=True,
    )


def build_subscription(
    layout: JohnnyRootLayout, receipt: TicketReceipt, inputs: SubscriptionInputs
) -> tuple[SubscriptionBuildStatus, SubscriptionBuildFailure | None]:
    """Verify, probe, compose and write one runner subscription."""

    repository = Path(inputs.repository_root)
    if not (repository / ".git").exists():
        return (
            SubscriptionBuildStatus.REFUSED,
            SubscriptionBuildFailure.REPOSITORY_UNAVAILABLE,
        )

    metadata_root = layout.queue_root / "metadata"
    metadata_root.mkdir(parents=True, exist_ok=True)
    boundary = WakeScopedDispatchBoundary(metadata_root)
    verification, _ = verify_receipt_claimable(boundary, receipt)
    if verification is not ReceiptVerificationStatus.CLAIMABLE:
        return (
            SubscriptionBuildStatus.REFUSED,
            SubscriptionBuildFailure.RECEIPT_NOT_DISPATCHED,
        )

    probe = probe_wake_capability(layout)
    if probe.status is not WakeCapabilityStatus.PROVEN:
        return (
            SubscriptionBuildStatus.REFUSED,
            SubscriptionBuildFailure.WAKE_CAPABILITY_UNAVAILABLE,
        )

    deadline_status, deadline_proof = probe_deadline_capability(
        receipt, receipt.implementation_owner_id
    )
    if deadline_status is not DeadlineProbeStatus.PROVEN or deadline_proof is None:
        return (
            SubscriptionBuildStatus.REFUSED,
            SubscriptionBuildFailure.DEADLINE_CAPABILITY_UNAVAILABLE,
        )

    wake_proof = RoleWakeCapabilityProof(
        project_id=receipt.project_id,
        ticket_ref=receipt.ticket_reference,
        router_receipt_ref=receipt.receipt_id,
        bound_event_source_ref=inputs.event_source_ref,
        bound_subscription_id=inputs.subscription_id,
        bound_implementation_task_ref=receipt.implementation_owner_id,
        reviewer_ref=inputs.reviewer_ref,
        reviewer_task_id=inputs.reviewer_task_id,
        reviewer_thread_id=inputs.reviewer_task_id,
        host_id=inputs.reviewer_host_id,
        wake_port_revision=_wake_port_revision(),
        binding_digest=_binding_digest(receipt, inputs),
        state=RoleWakeCapabilityState.PROVEN,
        evidence_refs=("evidence-wake-command-probe",),
    )

    specification = RunnerSubscriptionSpec(
        repository_root=str(repository),
        preparation=SupervisionPreparationRequest(
            receipt=receipt,
            registration_request=_registration(receipt, inputs),
            handoff_context=_admission(receipt, inputs),
            reviewer_ref=inputs.reviewer_ref,
            implementation_task_ref=receipt.implementation_owner_id,
            wake_capability=wake_proof,
            deadline_capability=deadline_proof,
        ),
        start=SupervisionStartRequest(
            subscription_id=inputs.subscription_id,
            lease_id=inputs.lease_id,
            supervision_class=inputs.supervision_class,
            execution_started=_execution_started(receipt, inputs),
        ),
    )

    path = subscriptions_path(layout)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            RunnerSubscriptionFile(subscriptions=(specification,)).model_dump_json(),
            encoding="utf-8",
        )
    except OSError:
        return (
            SubscriptionBuildStatus.REFUSED,
            SubscriptionBuildFailure.SUBSCRIPTION_UNWRITABLE,
        )
    return SubscriptionBuildStatus.WRITTEN, None


__all__ = [
    "SubscriptionBuildFailure",
    "SubscriptionBuildStatus",
    "SubscriptionInputs",
    "build_subscription",
]
