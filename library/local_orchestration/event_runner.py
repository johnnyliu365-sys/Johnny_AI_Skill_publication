"""Per-project event runner: sleep on exact Git refs, wake one named reviewer.

The runner never polls. It arms the native exact-ref watch through the
receipt-bound supervision controller and then blocks on a stop sentinel; every
wake decision happens on the watcher's own signal callback. When no wake
capability is proven, the resolved channel is the candidate inbox and the
runner truthfully records a completion candidate instead of claiming a wake.

The same signal callback also feeds the work queue's second source: a commit
on a watched ref becomes one `COMMIT_TRIGGER` item. That wire lives in
`commit_trigger_intake`, is composed here and nowhere else, and cannot delay
or fail a wake -- see that module for why the ordering is what it is.

Both of those rely on the same native exact-ref watch, and that watch exists
only on Windows (ticket 21). Every state this runner writes therefore also
names the ref-watch capability this process actually has, probed fresh each
run rather than assumed: on a platform or environment without it, this
runner still starts, the wake-channel resolution above is untouched, and the
state says plainly that commit triggers are unavailable here -- instead of
letting a reader infer that from an empty queue, which is exactly as true
when a watch is armed and simply has nothing to report yet.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from library.workflow_router.supervision_runtime_contracts import (
    SupervisionPreparationRequest,
    SupervisionPreparationStatus,
    SupervisionStartRequest,
    SupervisionStartStatus,
)

from .command_role_wake_port import CommandRoleWakePort
from .commit_trigger_intake import build_supervision_with_commit_trigger_intake
from .johnny_root_layout import JohnnyRootLayout
from .receipt_bound_supervision import ReceiptBoundSupervisionController
from .runner_receipt_seeding import (
    ReceiptVerificationStatus,
    verify_receipt_claimable,
)
from .wake_scoped_boundary import WakeScopedDispatchBoundary
from .role_wake_composition import (
    DurableRoleWakeAttemptStore,
    RoleWakeCoordinator,
    RoleWakePort,
)
from .wake_candidate_inbox import WakeCandidateInboxPort
from .wake_capability import (
    WakeCapabilityStatus,
    WakeChannelKind,
    probe_wake_capability,
)
from .windows_native_git_ref import probe_ref_watch_capability

_SUBSCRIPTIONS_FILE_NAME = "runner-subscriptions.json"
_STOP_SENTINEL_NAME = "runner.stop"
_STATE_FILE_NAME = "runner-state.json"
_STOP_POLL_SECONDS = 0.5


class RunnerSubscriptionSpec(BaseModel):
    """One committed subscription: which exact ref, bound to which receipt."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
    )

    schema_version: int = Field(default=1, ge=1, le=1)
    repository_root: str = Field(min_length=1, max_length=512)
    preparation: SupervisionPreparationRequest
    start: SupervisionStartRequest

    @model_validator(mode="after")
    def bindings_agree(self) -> Self:
        registration = self.preparation.registration_request
        if registration.project_id != self.preparation.handoff_context.project_id:
            raise ValueError("subscription bindings must name one project")
        if self.start.subscription_id != registration.subscription_id:
            raise ValueError("the start request must name the prepared subscription")
        return self


class RunnerSubscriptionFile(BaseModel):
    """Every subscription this runner arms for one project."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: int = Field(default=1, ge=1, le=1)
    subscriptions: tuple[RunnerSubscriptionSpec, ...] = Field(min_length=1)


def subscriptions_path(layout: JohnnyRootLayout) -> Path:
    return layout.queue_root / _SUBSCRIPTIONS_FILE_NAME


def stop_sentinel_path(layout: JohnnyRootLayout) -> Path:
    return layout.queue_root / _STOP_SENTINEL_NAME


def runner_state_path(layout: JohnnyRootLayout) -> Path:
    return layout.queue_root / _STATE_FILE_NAME


@dataclass(frozen=True, slots=True)
class ResolvedWakeChannel:
    """The channel this runner will actually use, plus its honest kind."""

    kind: WakeChannelKind
    port: RoleWakePort


def resolve_wake_channel(layout: JohnnyRootLayout) -> ResolvedWakeChannel:
    """Probe first; claim the command channel only when the probe proves it."""

    probe = probe_wake_capability(layout)
    if probe.status is WakeCapabilityStatus.PROVEN and probe.config is not None:
        return ResolvedWakeChannel(
            kind=WakeChannelKind.HOST_COMMAND,
            port=CommandRoleWakePort(layout, probe.config),
        )
    return ResolvedWakeChannel(
        kind=WakeChannelKind.CANDIDATE_INBOX,
        port=WakeCandidateInboxPort(layout),
    )


def _write_state(layout: JohnnyRootLayout, payload: dict[str, object]) -> None:
    path = runner_state_path(layout)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def run_event_runner(layout: JohnnyRootLayout) -> int:
    """Arm every committed subscription, then sleep until a stop is requested."""

    # Probed once per run, not re-derived from anything this loop later does:
    # whether commit triggers can happen here is a fact about this process
    # and this platform, unrelated to whether any particular subscription
    # goes on to succeed. Every state below carries it, gate failures
    # included, so a reader never has to infer it from an empty queue.
    ref_watch = probe_ref_watch_capability()

    def _write(payload: dict[str, object]) -> None:
        _write_state(
            layout,
            {
                **payload,
                "commit_trigger_capability": ref_watch.status.value,
                "commit_trigger_failure": (
                    ref_watch.failure.value if ref_watch.failure is not None else None
                ),
            },
        )

    subscriptions_file = subscriptions_path(layout)
    if not subscriptions_file.is_file():
        _write({"status": "BLOCKED", "code": "NO_SUBSCRIPTIONS"})
        return 2
    try:
        parsed = RunnerSubscriptionFile.model_validate_json(
            subscriptions_file.read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        _write({"status": "BLOCKED", "code": "SUBSCRIPTIONS_INVALID"})
        return 2

    channel = resolve_wake_channel(layout)
    metadata_root = layout.queue_root / "metadata"
    metadata_root.mkdir(parents=True, exist_ok=True)
    # The runner holds only the wake-scoped surface: read, claim, settle.
    # No issuance-capable object exists anywhere in this composition.
    boundary = WakeScopedDispatchBoundary(metadata_root)
    wake_coordinator = RoleWakeCoordinator(
        DurableRoleWakeAttemptStore(boundary), channel.port
    )

    stop_path = stop_sentinel_path(layout)
    if stop_path.exists():
        stop_path.unlink()

    armed: list[str] = []
    controllers: list[ReceiptBoundSupervisionController] = []
    for specification in parsed.subscriptions:
        # A wake claim is admitted only for a receipt that already exists in
        # the durable checkpoint. The runner verifies that and never creates
        # it: the subscription file is caller data, so minting the receipt
        # here would let a fabricated one satisfy its own wake claim.
        verification, verification_failure = verify_receipt_claimable(
            boundary, specification.preparation.receipt
        )
        if verification is not ReceiptVerificationStatus.CLAIMABLE:
            _write(
                {
                    "status": "BLOCKED",
                    "code": "RECEIPT_NOT_DISPATCHED",
                    "failure": (
                        verification_failure.value
                        if verification_failure
                        else None
                    ),
                },
            )
            return 2
        # No committed review-cluster resolver exists in 0.4.x, so this runner
        # uses the explicitly named unbatched variant rather than presenting
        # itself as the batched supervision path.
        #
        # The commit-trigger intake joins the same native signal callback the
        # wake path already uses (P7). The runner supplies only the two facts
        # it already holds -- where work is written down, and which exact
        # registration this subscription is -- and owns nothing about how a
        # signal becomes a queued item.
        controller = build_supervision_with_commit_trigger_intake(
            Path(specification.repository_root),
            wake_coordinator,
            layout,
            specification.preparation.registration_request,
        )
        prepared = controller.prepare(specification.preparation)
        if prepared.status is not SupervisionPreparationStatus.PREPARED:
            _write(
                {
                    "status": "BLOCKED",
                    "code": "SUBSCRIPTION_REJECTED",
                    "stage": "PREPARE",
                    "failure": prepared.failure.value if prepared.failure else None,
                },
            )
            return 2
        started = controller.start(specification.start)
        if started.status is not SupervisionStartStatus.ACTIVE:
            _write(
                {
                    "status": "BLOCKED",
                    "code": "SUBSCRIPTION_REJECTED",
                    "stage": "START",
                    "failure": started.failure.value if started.failure else None,
                },
            )
            return 2
        controllers.append(controller)
        armed.append(specification.preparation.registration_request.subscription_id)

    _write(
        {
            "status": "RUNNING",
            "pid": os.getpid(),
            "wake_channel": channel.kind.value,
            "armed_subscriptions": armed,
        },
    )

    try:
        while not stop_path.exists():
            # The native watcher thread owns every event; this loop only
            # observes the owner's stop request and never inspects Git.
            time.sleep(_STOP_POLL_SECONDS)
    finally:
        _write(
            {
                "status": "STOPPED",
                "wake_channel": channel.kind.value,
                "armed_subscriptions": armed,
            },
        )
        if stop_path.exists():
            stop_path.unlink()
    return 0


__all__ = [
    "ResolvedWakeChannel",
    "RunnerSubscriptionFile",
    "RunnerSubscriptionSpec",
    "resolve_wake_channel",
    "run_event_runner",
    "runner_state_path",
    "stop_sentinel_path",
    "subscriptions_path",
]
