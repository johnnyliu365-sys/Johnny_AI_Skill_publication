"""Runner, wake-inbox and wake-capability commands of the live CLI.

Every command prints exactly one typed JSON line. Nothing here starts a
supervision effect implicitly: `runner start` is the only command that spawns
the detached runner, and it reports the resolved wake channel truthfully so a
candidate-inbox degradation can never be mistaken for automatic wake.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from library.workflow_router.contracts import ProjectId
from library.workflow_router.live_dispatch_contracts import (
    ReceiptReadStatus,
    TicketReceiptReadRequest,
)

from .event_runner import resolve_wake_channel, subscriptions_path
from .johnny_root_layout import JohnnyRootLayout
from .project_runner_registry import RunnerStarted, RunnerStopped
from .runner_lifecycle_port import (
    RealRunnerLifecyclePort,
    read_runner_state,
    runner_pid_path,
)
from .subscription_builder import (
    SubscriptionBuildFailure,
    SubscriptionBuildStatus,
    SubscriptionInputs,
    build_subscription,
)
from .wake_candidate_inbox import read_candidates
from .wake_capability import WakeCapabilityStatus, probe_wake_capability
from .wake_scoped_boundary import WakeScopedDispatchBoundary

_PLACEHOLDER_PROJECT: ProjectId = "prj_0000000000000000"


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True))


def _runner_start(layout: JohnnyRootLayout) -> int:
    if not subscriptions_path(layout).is_file():
        _emit({"status": "BLOCKED", "code": "NO_SUBSCRIPTIONS"})
        return 2
    channel = resolve_wake_channel(layout)
    result = RealRunnerLifecyclePort(layout).start(_PLACEHOLDER_PROJECT)
    if not isinstance(result, RunnerStarted):
        state = read_runner_state(layout)
        _emit(
            {
                "status": "BLOCKED",
                "code": "RUNNER_START_UNAVAILABLE",
                "runner_state": state,
                "wake_channel": channel.kind.value,
            }
        )
        return 2
    _emit(
        {
            "status": "RUNNING",
            "runner_ref": result.runner_ref,
            "wake_channel": channel.kind.value,
            "automatic_wake": channel.kind.value == "HOST_COMMAND",
        }
    )
    return 0


def _runner_stop(layout: JohnnyRootLayout) -> int:
    result = RealRunnerLifecyclePort(layout).stop(_PLACEHOLDER_PROJECT, "runner")
    if not isinstance(result, RunnerStopped):
        _emit({"status": "BLOCKED", "code": "RUNNER_STOP_UNAVAILABLE"})
        return 2
    _emit({"status": "STOPPED"})
    return 0


def _runner_status(layout: JohnnyRootLayout) -> int:
    state = read_runner_state(layout)
    running = (
        state is not None
        and state.get("status") == "RUNNING"
        and runner_pid_path(layout).is_file()
    )
    _emit(
        {
            "status": "RUNNING" if running else "NOT_RUNNING",
            "runner_state": state,
        }
    )
    return 0 if running else 3


def _load_inputs_document(inputs_path: Path) -> object | None:
    """Read and JSON-decode the inputs file, or None on any I/O/parse failure."""

    try:
        raw = inputs_path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        parsed: object = json.loads(raw)
    except ValueError:
        return None
    return parsed


def _runner_subscribe(layout: JohnnyRootLayout, arguments: tuple[str, ...]) -> int:
    if not arguments:
        _emit({"status": "REFUSED", "failure": "INPUTS_FILE_UNREADABLE", "section": "file"})
        return 2
    document = _load_inputs_document(Path(arguments[0]))
    if not isinstance(document, dict):
        _emit({"status": "REFUSED", "failure": "INPUTS_FILE_INVALID", "section": "file"})
        return 2

    try:
        locator = TicketReceiptReadRequest.model_validate_json(
            json.dumps(document.get("receipt_locator"))
        )
    except ValidationError:
        _emit(
            {
                "status": "REFUSED",
                "failure": "INPUTS_FILE_INVALID",
                "section": "receipt_locator",
            }
        )
        return 2

    try:
        subscription_inputs = SubscriptionInputs.model_validate_json(
            json.dumps(document.get("inputs"))
        )
    except ValidationError:
        _emit(
            {
                "status": "REFUSED",
                "failure": "INPUTS_FILE_INVALID",
                "section": "inputs",
            }
        )
        return 2

    metadata_root = layout.queue_root / "metadata"
    metadata_root.mkdir(parents=True, exist_ok=True)
    boundary = WakeScopedDispatchBoundary(metadata_root)
    read_result = boundary.read_receipt(locator)
    if read_result.status is not ReceiptReadStatus.FOUND or read_result.receipt is None:
        _emit(
            {
                "status": "REFUSED",
                "failure": SubscriptionBuildFailure.RECEIPT_NOT_DISPATCHED.value,
            }
        )
        return 2

    status, failure = build_subscription(
        layout, read_result.receipt, subscription_inputs
    )
    if status is not SubscriptionBuildStatus.WRITTEN:
        _emit(
            {
                "status": "REFUSED",
                "failure": failure.value if failure is not None else "UNKNOWN",
            }
        )
        return 2
    _emit({"status": "WRITTEN"})
    return 0


def run_runner_command(
    command: str, arguments: tuple[str, ...], johnny_root: Path
) -> int:
    """Dispatch one runner-family command against the resolved Johnny root."""

    layout = JohnnyRootLayout(base=johnny_root)
    if command == "wake-capability":
        probe = probe_wake_capability(layout)
        _emit(
            {
                "status": probe.status.value,
                "channel": probe.channel.value,
                "failure": probe.failure.value if probe.failure else None,
                "automatic_wake": probe.status is WakeCapabilityStatus.PROVEN,
            }
        )
        return 0 if probe.status is WakeCapabilityStatus.PROVEN else 3
    if command == "wake-inbox":
        try:
            candidates = read_candidates(layout)
        except (OSError, ValueError):
            _emit({"status": "BLOCKED", "code": "INBOX_UNREADABLE"})
            return 2
        _emit(
            {
                "status": "OK",
                "candidate_count": len(candidates),
                "candidates": [
                    {
                        "attempt_id": record.attempt_id,
                        "reviewer_task_id": record.reviewer_task_id,
                        "payload_digest": record.payload_digest,
                        "payload_path": record.payload_path,
                    }
                    for record in candidates
                ],
            }
        )
        return 0
    subcommand = arguments[0] if arguments else "status"
    if subcommand == "start":
        return _runner_start(layout)
    if subcommand == "stop":
        return _runner_stop(layout)
    if subcommand == "status":
        return _runner_status(layout)
    if subcommand == "subscribe":
        return _runner_subscribe(layout, arguments[1:])
    _emit({"status": "CAPABILITY_UNAVAILABLE", "code": "UNKNOWN_SUBCOMMAND"})
    return 2


__all__ = ["run_runner_command"]
