"""Exact-ref registration and authoritative committed-handoff readback."""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Protocol

from pydantic import ValidationError

from library.workflow_router.git_handoff_contracts import (
    GitAncestryResult,
    GitAncestryStatus,
    GitBlobReadResult,
    GitBlobReadStatus,
    GitEventAdapterDecision,
    GitEventAdapterDecisionKind,
    GitEventAdapterFailure,
    GitEventRegistrationLifecycle,
    GitEventRegistrationState,
    GitNativeFailureSignal,
    GitNativeRegistrationRequest,
    GitNativeRegistrationResult,
    GitNativeRegistrationStatus,
    GitObservationMode,
    GitPathChangeResult,
    GitPathChangeStatus,
    GitRefRegistrationRequest,
    GitRefSignal,
    GitRefSnapshotResult,
    GitRefSnapshotStatus,
    SubscriptionId,
    SupervisionFault,
    SupervisionFaultKind,
)
from library.workflow_router.role_supervision_contracts import (
    HandoffAdmissionContext,
    HandoffLeaf,
    HandoffValidationStatus,
    validate_handoff_leaf,
)


class GitReadbackPort(Protocol):
    """Exact Git queries allowed after one native ref hint."""

    def read_ref(self, exact_git_ref: str) -> GitRefSnapshotResult: ...

    def path_changed(
        self,
        prior_commit: str,
        observed_commit: str,
        exact_path: str,
    ) -> GitPathChangeResult: ...

    def read_blob(self, commit_id: str, exact_path: str) -> GitBlobReadResult: ...

    def is_ancestor(self, ancestor: str, descendant: str) -> GitAncestryResult: ...


class NativeGitRefNotificationPort(Protocol):
    """Host-native exact-ref signal registration; no recurring callbacks."""

    def register(self, request: GitNativeRegistrationRequest) -> GitNativeRegistrationResult: ...

    def cancel(self, subscription_id: SubscriptionId) -> bool: ...


class NativeGitRefSignalSink(Protocol):
    """Thread-safe destination for native exact-ref hints and capability loss."""

    def on_signal(self, signal: GitRefSignal) -> None: ...

    def on_failure(self, signal: GitNativeFailureSignal) -> None: ...


class NativeGitRefNotificationFactory(Protocol):
    def create(self, sink: NativeGitRefSignalSink) -> NativeGitRefNotificationPort: ...


class GitCliReadbackPort:
    """Bounded exact Git CLI readback with no worktree or repository scan."""

    def __init__(self, repository_root: Path) -> None:
        if not isinstance(repository_root, Path):
            raise TypeError("repository root must be a Path")
        if not repository_root.is_absolute():
            raise ValueError("repository root must be absolute")
        resolved = repository_root.resolve(strict=True)
        if not resolved.is_dir():
            raise ValueError("repository root must be an existing directory")
        probe = self._run_at(resolved, ("rev-parse", "--show-toplevel"))
        if probe.returncode != 0:
            raise ValueError("repository root is not a readable Git worktree")
        observed_root = Path(probe.stdout.strip()).resolve(strict=True)
        if observed_root != resolved:
            raise ValueError("repository root must equal the Git worktree top level")
        self._repository_root = resolved

    @staticmethod
    def _run_at(root: Path, arguments: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ("git", "-C", str(root), *arguments),
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )

    def _run(self, arguments: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        return self._run_at(self._repository_root, arguments)

    def read_ref(self, exact_git_ref: str) -> GitRefSnapshotResult:
        try:
            completed = self._run(("rev-parse", "--verify", "--quiet", f"{exact_git_ref}^{{commit}}"))
        except (OSError, subprocess.SubprocessError):
            return GitRefSnapshotResult(status=GitRefSnapshotStatus.UNAVAILABLE)
        if completed.returncode == 1:
            return GitRefSnapshotResult(status=GitRefSnapshotStatus.NOT_FOUND)
        if completed.returncode != 0:
            return GitRefSnapshotResult(status=GitRefSnapshotStatus.UNAVAILABLE)
        commit = completed.stdout.strip()
        try:
            return GitRefSnapshotResult(
                status=GitRefSnapshotStatus.FOUND,
                exact_git_ref=exact_git_ref,
                commit_id=commit,
            )
        except ValidationError:
            return GitRefSnapshotResult(status=GitRefSnapshotStatus.UNAVAILABLE)

    def path_changed(
        self,
        prior_commit: str,
        observed_commit: str,
        exact_path: str,
    ) -> GitPathChangeResult:
        try:
            completed = self._run(
                ("diff", "--quiet", prior_commit, observed_commit, "--", exact_path)
            )
        except (OSError, subprocess.SubprocessError):
            return GitPathChangeResult(
                status=GitPathChangeStatus.UNAVAILABLE,
                changed=None,
            )
        if completed.returncode == 0:
            return GitPathChangeResult(
                status=GitPathChangeStatus.UNCHANGED,
                changed=False,
            )
        if completed.returncode == 1:
            return GitPathChangeResult(
                status=GitPathChangeStatus.CHANGED,
                changed=True,
            )
        return GitPathChangeResult(
            status=GitPathChangeStatus.UNAVAILABLE,
            changed=None,
        )

    def read_blob(self, commit_id: str, exact_path: str) -> GitBlobReadResult:
        try:
            completed = self._run(("show", f"{commit_id}:{exact_path}"))
        except (OSError, subprocess.SubprocessError):
            return GitBlobReadResult(status=GitBlobReadStatus.UNAVAILABLE)
        if completed.returncode != 0:
            return GitBlobReadResult(status=GitBlobReadStatus.NOT_FOUND)
        return GitBlobReadResult(
            status=GitBlobReadStatus.FOUND,
            payload=completed.stdout,
        )

    def is_ancestor(self, ancestor: str, descendant: str) -> GitAncestryResult:
        try:
            completed = self._run(("merge-base", "--is-ancestor", ancestor, descendant))
        except (OSError, subprocess.SubprocessError):
            return GitAncestryResult(
                status=GitAncestryStatus.UNAVAILABLE,
                is_ancestor=None,
            )
        if completed.returncode == 0:
            return GitAncestryResult(
                status=GitAncestryStatus.IS_ANCESTOR,
                is_ancestor=True,
            )
        if completed.returncode == 1:
            return GitAncestryResult(
                status=GitAncestryStatus.NOT_ANCESTOR,
                is_ancestor=False,
            )
        return GitAncestryResult(
            status=GitAncestryStatus.UNAVAILABLE,
            is_ancestor=None,
        )


def _registration_state(
    request: GitRefRegistrationRequest,
    *,
    lifecycle: GitEventRegistrationLifecycle,
    last_observed_commit: str,
    consumed_handoff_ids: tuple[str, ...],
    fault_emitted: bool,
) -> GitEventRegistrationState:
    return GitEventRegistrationState(
        event_source_ref=request.event_source_ref,
        subscription_id=request.subscription_id,
        project_id=request.project_id,
        ticket_ref=request.ticket_ref,
        router_receipt_ref=request.router_receipt_ref,
        implementation_task_ref=request.implementation_task_ref,
        worktree_ref=request.worktree_ref,
        branch_ref=request.branch_ref,
        baseline_commit=request.baseline_commit,
        correlation_id=request.correlation_id,
        exact_git_ref=request.exact_git_ref,
        reserved_handoff_ref=request.reserved_handoff_ref,
        mode=GitObservationMode.NATIVE_REF_EVENT,
        lifecycle=lifecycle,
        last_observed_commit=last_observed_commit,
        consumed_handoff_ids=consumed_handoff_ids,
        fault_emitted=fault_emitted,
    )


def _replace_state(
    state: GitEventRegistrationState,
    *,
    lifecycle: GitEventRegistrationLifecycle,
    last_observed_commit: str,
    consumed_handoff_ids: tuple[str, ...],
    fault_emitted: bool,
) -> GitEventRegistrationState:
    return GitEventRegistrationState(
        event_source_ref=state.event_source_ref,
        subscription_id=state.subscription_id,
        project_id=state.project_id,
        ticket_ref=state.ticket_ref,
        router_receipt_ref=state.router_receipt_ref,
        implementation_task_ref=state.implementation_task_ref,
        worktree_ref=state.worktree_ref,
        branch_ref=state.branch_ref,
        baseline_commit=state.baseline_commit,
        correlation_id=state.correlation_id,
        exact_git_ref=state.exact_git_ref,
        reserved_handoff_ref=state.reserved_handoff_ref,
        mode=state.mode,
        lifecycle=lifecycle,
        last_observed_commit=last_observed_commit,
        consumed_handoff_ids=consumed_handoff_ids,
        fault_emitted=fault_emitted,
    )


def _request_matches_context(
    request: GitRefRegistrationRequest,
    context: HandoffAdmissionContext,
) -> bool:
    return all(
        (
            request.project_id == context.project_id,
            request.ticket_ref == context.ticket_ref,
            request.router_receipt_ref == context.router_receipt_ref,
            request.implementation_task_ref == context.source_task_ref,
            request.worktree_ref == context.worktree_ref,
            request.branch_ref == context.branch_ref,
            request.baseline_commit == context.baseline_commit,
            request.correlation_id == context.correlation_id,
        )
    )


def _derived_context(
    expected: HandoffAdmissionContext,
    *,
    observed_handoff_commit: str,
    result_descends_from_baseline: bool,
    handoff_descends_from_result: bool,
    consumed_handoff_ids: tuple[str, ...],
) -> HandoffAdmissionContext:
    return HandoffAdmissionContext(
        project_id=expected.project_id,
        spec_ref=expected.spec_ref,
        spec_revision=expected.spec_revision,
        ticket_ref=expected.ticket_ref,
        ticket_revision=expected.ticket_revision,
        router_receipt_ref=expected.router_receipt_ref,
        source_role_ref=expected.source_role_ref,
        source_task_ref=expected.source_task_ref,
        target_role_ref=expected.target_role_ref,
        target_task_ref=expected.target_task_ref,
        worktree_ref=expected.worktree_ref,
        branch_ref=expected.branch_ref,
        baseline_commit=expected.baseline_commit,
        correlation_id=expected.correlation_id,
        observed_handoff_commit=observed_handoff_commit,
        result_descends_from_baseline=result_descends_from_baseline,
        handoff_descends_from_result=handoff_descends_from_result,
        reserved_path_changed=True,
        consumed_handoff_ids=consumed_handoff_ids,
    )


class ReceiptBoundGitEventAdapter:
    """Register once, re-read exact Git state, and deduplicate by commit/handoff."""

    def __init__(
        self,
        readback_port: GitReadbackPort,
        native_port: NativeGitRefNotificationPort,
    ) -> None:
        self._readback_port = readback_port
        self._native_port = native_port

    def register(
        self,
        request: GitRefRegistrationRequest,
        context: HandoffAdmissionContext,
    ) -> GitEventAdapterDecision:
        if type(request) is not GitRefRegistrationRequest or type(context) is not HandoffAdmissionContext:
            return GitEventAdapterDecision(
                decision=GitEventAdapterDecisionKind.REGISTRATION_FAILED,
                failure=GitEventAdapterFailure.INVALID_REQUEST,
            )
        try:
            trusted_request = GitRefRegistrationRequest.model_validate(request, strict=True)
            trusted_context = HandoffAdmissionContext.model_validate(context, strict=True)
        except ValidationError:
            return GitEventAdapterDecision(
                decision=GitEventAdapterDecisionKind.REGISTRATION_FAILED,
                failure=GitEventAdapterFailure.INVALID_REQUEST,
            )
        if not _request_matches_context(trusted_request, trusted_context):
            return GitEventAdapterDecision(
                decision=GitEventAdapterDecisionKind.REGISTRATION_FAILED,
                failure=GitEventAdapterFailure.INVALID_REQUEST,
            )
        pre = self._read_ref(trusted_request.exact_git_ref)
        if pre.status is not GitRefSnapshotStatus.FOUND or pre.commit_id is None:
            return GitEventAdapterDecision(
                decision=GitEventAdapterDecisionKind.REGISTRATION_FAILED,
                failure=GitEventAdapterFailure.REF_UNAVAILABLE,
            )
        native_request = GitNativeRegistrationRequest(
            event_source_ref=trusted_request.event_source_ref,
            subscription_id=trusted_request.subscription_id,
            exact_git_ref=trusted_request.exact_git_ref,
        )
        try:
            native = self._native_port.register(native_request)
            native = GitNativeRegistrationResult.model_validate(native, strict=True)
        except (Exception, ValidationError):
            return GitEventAdapterDecision(
                decision=GitEventAdapterDecisionKind.REGISTRATION_FAILED,
                failure=GitEventAdapterFailure.NATIVE_REGISTRATION_UNAVAILABLE,
            )
        if (
            native.status is not GitNativeRegistrationStatus.REGISTERED
            or native.event_source_ref != trusted_request.event_source_ref
            or native.subscription_id != trusted_request.subscription_id
        ):
            return GitEventAdapterDecision(
                decision=GitEventAdapterDecisionKind.REGISTRATION_FAILED,
                failure=GitEventAdapterFailure.NATIVE_REGISTRATION_UNAVAILABLE,
            )
        post = self._read_ref(trusted_request.exact_git_ref)
        if post.status is not GitRefSnapshotStatus.FOUND or post.commit_id is None:
            self._cancel(trusted_request.subscription_id)
            return GitEventAdapterDecision(
                decision=GitEventAdapterDecisionKind.REGISTRATION_FAILED,
                failure=GitEventAdapterFailure.READBACK_UNAVAILABLE,
            )
        state = _registration_state(
            trusted_request,
            lifecycle=GitEventRegistrationLifecycle.ACTIVE,
            last_observed_commit=trusted_request.baseline_commit,
            consumed_handoff_ids=trusted_context.consumed_handoff_ids,
            fault_emitted=False,
        )
        if post.commit_id == trusted_request.baseline_commit:
            return GitEventAdapterDecision(
                decision=GitEventAdapterDecisionKind.REGISTERED,
                registration=state,
            )
        return self._evaluate_change(state, post.commit_id, trusted_context)

    def observe_signal(
        self,
        state: GitEventRegistrationState,
        signal: GitRefSignal,
        context: HandoffAdmissionContext,
    ) -> GitEventAdapterDecision:
        if type(state) is not GitEventRegistrationState or type(signal) is not GitRefSignal:
            raise TypeError("Git signal observation requires exact strong types")
        try:
            current = GitEventRegistrationState.model_validate(state, strict=True)
            observed_signal = GitRefSignal.model_validate(signal, strict=True)
            trusted_context = HandoffAdmissionContext.model_validate(context, strict=True)
        except ValidationError as error:
            raise TypeError("Git signal observation received an invalid contract") from error
        if current.lifecycle is not GitEventRegistrationLifecycle.ACTIVE:
            return GitEventAdapterDecision(
                decision=GitEventAdapterDecisionKind.SILENT,
                registration=current,
            )
        if (
            observed_signal.event_source_ref != current.event_source_ref
            or observed_signal.subscription_id != current.subscription_id
        ):
            return GitEventAdapterDecision(
                decision=GitEventAdapterDecisionKind.SILENT,
                registration=current,
            )
        snapshot = self._read_ref(current.exact_git_ref)
        if snapshot.status is not GitRefSnapshotStatus.FOUND or snapshot.commit_id is None:
            closed = _replace_state(
                current,
                lifecycle=GitEventRegistrationLifecycle.CLOSED,
                last_observed_commit=current.last_observed_commit,
                consumed_handoff_ids=current.consumed_handoff_ids,
                fault_emitted=False,
            )
            self._cancel(current.subscription_id)
            return GitEventAdapterDecision(
                decision=GitEventAdapterDecisionKind.READBACK_FAILED,
                registration=closed,
            )
        if snapshot.commit_id == current.last_observed_commit:
            return GitEventAdapterDecision(
                decision=GitEventAdapterDecisionKind.SILENT,
                registration=current,
            )
        return self._evaluate_change(current, snapshot.commit_id, trusted_context)

    def close(self, state: GitEventRegistrationState) -> GitEventRegistrationState:
        """Close one exact active registration; repeated closure is idempotent."""

        if type(state) is not GitEventRegistrationState:
            raise TypeError("Git registration closure requires exact strong state")
        try:
            current = GitEventRegistrationState.model_validate(state, strict=True)
        except ValidationError as error:
            raise TypeError("Git registration closure received invalid state") from error
        if current.lifecycle is not GitEventRegistrationLifecycle.ACTIVE:
            return current
        self._cancel(current.subscription_id)
        return _replace_state(
            current,
            lifecycle=GitEventRegistrationLifecycle.CLOSED,
            last_observed_commit=current.last_observed_commit,
            consumed_handoff_ids=current.consumed_handoff_ids,
            fault_emitted=False,
        )

    def _read_ref(self, exact_git_ref: str) -> GitRefSnapshotResult:
        try:
            result = self._readback_port.read_ref(exact_git_ref)
            return GitRefSnapshotResult.model_validate(result, strict=True)
        except (Exception, ValidationError):
            return GitRefSnapshotResult(status=GitRefSnapshotStatus.UNAVAILABLE)

    def _cancel(self, subscription_id: SubscriptionId) -> None:
        try:
            self._native_port.cancel(subscription_id)
        except Exception:
            return

    def _readback_failed(
        self,
        state: GitEventRegistrationState,
    ) -> GitEventAdapterDecision:
        closed = _replace_state(
            state,
            lifecycle=GitEventRegistrationLifecycle.CLOSED,
            last_observed_commit=state.last_observed_commit,
            consumed_handoff_ids=state.consumed_handoff_ids,
            fault_emitted=False,
        )
        self._cancel(state.subscription_id)
        return GitEventAdapterDecision(
            decision=GitEventAdapterDecisionKind.READBACK_FAILED,
            registration=closed,
        )

    def _fault(
        self,
        state: GitEventRegistrationState,
        observed_commit: str,
        kind: SupervisionFaultKind,
    ) -> GitEventAdapterDecision:
        halted = _replace_state(
            state,
            lifecycle=GitEventRegistrationLifecycle.HALTED,
            last_observed_commit=observed_commit,
            consumed_handoff_ids=state.consumed_handoff_ids,
            fault_emitted=True,
        )
        self._cancel(state.subscription_id)
        decision = (
            GitEventAdapterDecisionKind.INVALID_HANDOFF_FAULT
            if kind is SupervisionFaultKind.INVALID_HANDOFF
            else GitEventAdapterDecisionKind.STALE_BINDING_FAULT
        )
        return GitEventAdapterDecision(
            decision=decision,
            registration=halted,
            fault=SupervisionFault(
                kind=kind,
                event_source_ref=state.event_source_ref,
                subscription_id=state.subscription_id,
                ticket_ref=state.ticket_ref,
                router_receipt_ref=state.router_receipt_ref,
                observed_commit=observed_commit,
            ),
        )

    def _evaluate_change(
        self,
        state: GitEventRegistrationState,
        observed_commit: str,
        expected: HandoffAdmissionContext,
    ) -> GitEventAdapterDecision:
        try:
            branch_ancestry = self._readback_port.is_ancestor(
                state.last_observed_commit,
                observed_commit,
            )
            branch_ancestry = GitAncestryResult.model_validate(branch_ancestry, strict=True)
        except (Exception, ValidationError):
            return self._readback_failed(state)
        if branch_ancestry.status is GitAncestryStatus.UNAVAILABLE:
            return self._readback_failed(state)
        if branch_ancestry.status is GitAncestryStatus.NOT_ANCESTOR:
            return self._fault(state, observed_commit, SupervisionFaultKind.STALE_BINDING)
        try:
            path_result = self._readback_port.path_changed(
                state.last_observed_commit,
                observed_commit,
                state.reserved_handoff_ref,
            )
            path_result = GitPathChangeResult.model_validate(path_result, strict=True)
        except (Exception, ValidationError):
            return self._readback_failed(state)
        if path_result.status is GitPathChangeStatus.UNAVAILABLE:
            return self._readback_failed(state)
        advanced = _replace_state(
            state,
            lifecycle=GitEventRegistrationLifecycle.ACTIVE,
            last_observed_commit=observed_commit,
            consumed_handoff_ids=state.consumed_handoff_ids,
            fault_emitted=False,
        )
        if path_result.status is GitPathChangeStatus.UNCHANGED:
            return GitEventAdapterDecision(
                decision=GitEventAdapterDecisionKind.SOURCE_ADVANCED,
                registration=advanced,
            )
        try:
            blob = self._readback_port.read_blob(observed_commit, state.reserved_handoff_ref)
            blob = GitBlobReadResult.model_validate(blob, strict=True)
        except (Exception, ValidationError):
            return self._readback_failed(state)
        if blob.status is not GitBlobReadStatus.FOUND or blob.payload is None:
            return self._fault(state, observed_commit, SupervisionFaultKind.INVALID_HANDOFF)
        try:
            leaf = HandoffLeaf.model_validate_json(blob.payload, strict=True)
        except ValidationError:
            return self._fault(state, observed_commit, SupervisionFaultKind.INVALID_HANDOFF)
        if leaf.handoff_id in state.consumed_handoff_ids:
            return GitEventAdapterDecision(
                decision=GitEventAdapterDecisionKind.SILENT,
                registration=advanced,
            )
        try:
            result_ancestry = self._readback_port.is_ancestor(
                state.baseline_commit,
                leaf.result_commit,
            )
            handoff_ancestry = self._readback_port.is_ancestor(
                leaf.result_commit,
                observed_commit,
            )
            result_ancestry = GitAncestryResult.model_validate(result_ancestry, strict=True)
            handoff_ancestry = GitAncestryResult.model_validate(handoff_ancestry, strict=True)
        except (Exception, ValidationError):
            return self._readback_failed(state)
        if (
            result_ancestry.status is GitAncestryStatus.UNAVAILABLE
            or handoff_ancestry.status is GitAncestryStatus.UNAVAILABLE
        ):
            return self._readback_failed(state)
        context = _derived_context(
            expected,
            observed_handoff_commit=observed_commit,
            result_descends_from_baseline=result_ancestry.status is GitAncestryStatus.IS_ANCESTOR,
            handoff_descends_from_result=handoff_ancestry.status is GitAncestryStatus.IS_ANCESTOR,
            consumed_handoff_ids=state.consumed_handoff_ids,
        )
        validation = validate_handoff_leaf(leaf, context)
        if validation.status is not HandoffValidationStatus.ACCEPTED:
            return self._fault(state, observed_commit, SupervisionFaultKind.INVALID_HANDOFF)
        accepted = _replace_state(
            state,
            lifecycle=GitEventRegistrationLifecycle.ACTIVE,
            last_observed_commit=observed_commit,
            consumed_handoff_ids=(*state.consumed_handoff_ids, leaf.handoff_id),
            fault_emitted=False,
        )
        return GitEventAdapterDecision(
            decision=GitEventAdapterDecisionKind.TERMINAL_HANDOFF_ACCEPTED,
            registration=accepted,
            handoff=leaf,
        )


__all__ = [
    "GitCliReadbackPort",
    "GitReadbackPort",
    "NativeGitRefNotificationPort",
    "NativeGitRefNotificationFactory",
    "NativeGitRefSignalSink",
    "ReceiptBoundGitEventAdapter",
]
