"""Event-driven receipt-bound supervision composition, intentionally not Router-bound."""

from __future__ import annotations

from hashlib import sha256
from threading import Lock

from pydantic import ValidationError

from library.workflow_router.deadline_contracts import (
    DeadlineArmRequest,
    DeadlineArmStatus,
    DeadlineFailureSignal,
    DeadlineSignal,
    cancel_request_for,
)
from library.workflow_router.git_handoff_contracts import (
    GitEventAdapterDecision,
    GitEventAdapterDecisionKind,
    GitEventRegistrationLifecycle,
    GitEventRegistrationState,
    GitNativeFailureSignal,
    GitRefSignal,
    SubscriptionId,
    SupervisionFaultKind,
)
from library.workflow_router.role_wake_contracts import (
    RoleWakeChainPreflightRequest,
    RoleWakeChainProof,
    RoleWakeChainStatus,
    RoleWakeRequest,
    RoleWakeResult,
    RoleWakeStatus,
    RoleWakeTriggerKind,
    preflight_role_wake_chain,
    wake_request_from_git_decision,
)
from library.workflow_router.supervision_policy import (
    LeaseEvent,
    LeaseEventKind,
    LeaseLifecycle,
    SupervisionClass,
    SupervisionDecision,
    SupervisionDecisionKind,
    SupervisionLease,
    close_supervision_lease,
    reduce_supervision_lease,
    start_supervision_lease,
)
from library.workflow_router.supervision_runtime_contracts import (
    ContinuationAcceptedEvidence,
    ContinuationResult,
    ContinuationStatus,
    ReviewerDiagnosisRequest,
    ReviewerDiagnosisResult,
    ReviewerDiagnosisRoute,
    SupervisionPreparationRequest,
    SupervisionPreparationResult,
    SupervisionPreparationStatus,
    SupervisionRuntimeFailure,
    SupervisionRuntimeLifecycle,
    SupervisionRuntimeState,
    SupervisionStartRequest,
    SupervisionStartResult,
    SupervisionStartStatus,
)

from .git_handoff_event_adapter import (
    GitReadbackPort,
    NativeGitRefNotificationFactory,
    NativeGitRefNotificationPort,
    NativeGitRefSignalSink,
    ReceiptBoundGitEventAdapter,
)
from .one_shot_deadline import (
    DeadlineSignalSink,
    MonotonicClockPort,
    OneShotDeadlineFactory,
    OneShotDeadlinePort,
)
from .senior_review_inbox import ReviewWakeSubmissionPort


_PendingNativeSignal = GitRefSignal | GitNativeFailureSignal


def _attempt_id(prefix: str, *values: str) -> str:
    material = "\x00".join((prefix, *values)).encode("utf-8")
    return "wake-" + sha256(material).hexdigest()[:32]


def _replace_runtime(
    state: SupervisionRuntimeState,
    *,
    registration: GitEventRegistrationState | None = None,
    chain: RoleWakeChainProof | None = None,
    lease: SupervisionLease | None = None,
    lifecycle: SupervisionRuntimeLifecycle | None = None,
    git_decision: GitEventAdapterDecision | None = None,
    supervision_decision: SupervisionDecision | None = None,
    wake_result: RoleWakeResult | None = None,
    failure: SupervisionRuntimeFailure | None = None,
) -> SupervisionRuntimeState:
    return SupervisionRuntimeState(
        registration=state.registration if registration is None else registration,
        handoff_context=state.handoff_context,
        chain=chain if chain is not None else state.chain,
        lease=state.lease if lease is None else lease,
        model_override=state.model_override,
        lifecycle=lifecycle if lifecycle is not None else state.lifecycle,
        last_git_decision=(
            git_decision if git_decision is not None else state.last_git_decision
        ),
        last_supervision_decision=(
            supervision_decision
            if supervision_decision is not None
            else state.last_supervision_decision
        ),
        last_wake_result=(
            state.last_wake_result if wake_result is None else wake_result
        ),
        failure=failure,
    )


class ReceiptBoundSupervisionController(NativeGitRefSignalSink, DeadlineSignalSink):
    """Compose Git events, one-shot deadlines and exactly-once reviewer wake."""

    def __init__(
        self,
        readback_port: GitReadbackPort,
        native_factory: NativeGitRefNotificationFactory,
        deadline_factory: OneShotDeadlineFactory,
        wake_coordinator: ReviewWakeSubmissionPort,
        clock: MonotonicClockPort,
    ) -> None:
        self._lock = Lock()
        self._states: dict[SubscriptionId, SupervisionRuntimeState] = {}
        self._pending: dict[SubscriptionId, list[_PendingNativeSignal]] = {}
        self._wake_coordinator = wake_coordinator
        self._clock = clock
        self._native_port: NativeGitRefNotificationPort = native_factory.create(self)
        self._git_adapter = ReceiptBoundGitEventAdapter(readback_port, self._native_port)
        self._deadline_port: OneShotDeadlinePort = deadline_factory.create(self)

    def prepare(
        self,
        request: SupervisionPreparationRequest,
    ) -> SupervisionPreparationResult:
        if type(request) is not SupervisionPreparationRequest:
            return SupervisionPreparationResult(
                status=SupervisionPreparationStatus.REJECTED,
                failure=SupervisionRuntimeFailure.REGISTRATION_REJECTED,
            )
        try:
            trusted = SupervisionPreparationRequest.model_validate(request, strict=True)
        except ValidationError:
            return SupervisionPreparationResult(
                status=SupervisionPreparationStatus.REJECTED,
                failure=SupervisionRuntimeFailure.REGISTRATION_REJECTED,
            )
        subscription_id = trusted.registration_request.subscription_id
        with self._lock:
            if subscription_id in self._states:
                return SupervisionPreparationResult(
                    status=SupervisionPreparationStatus.REJECTED,
                    failure=SupervisionRuntimeFailure.REGISTRATION_REJECTED,
                )
        decision = self._git_adapter.register(
            trusted.registration_request,
            trusted.handoff_context,
        )
        registration = decision.registration
        if registration is None or registration.lifecycle is not GitEventRegistrationLifecycle.ACTIVE:
            return SupervisionPreparationResult(
                status=SupervisionPreparationStatus.CAPABILITY_UNAVAILABLE,
                failure=SupervisionRuntimeFailure.REGISTRATION_REJECTED,
            )
        preflight = preflight_role_wake_chain(
            RoleWakeChainPreflightRequest(
                receipt=trusted.receipt,
                registration=registration,
                reviewer_ref=trusted.reviewer_ref,
                implementation_task_ref=trusted.implementation_task_ref,
                wake_capability=trusted.wake_capability,
                deadline_capability=trusted.deadline_capability,
            )
        )
        if preflight.status is not RoleWakeChainStatus.PROVEN or preflight.proof is None:
            self._git_adapter.close(registration)
            return SupervisionPreparationResult(
                status=SupervisionPreparationStatus.CAPABILITY_UNAVAILABLE,
                failure=SupervisionRuntimeFailure.ROLE_WAKE_CHAIN_UNAVAILABLE,
            )
        state = SupervisionRuntimeState(
            registration=registration,
            handoff_context=trusted.handoff_context,
            chain=preflight.proof,
            lease=None,
            lifecycle=SupervisionRuntimeLifecycle.PREPARED,
            last_git_decision=decision,
        )
        with self._lock:
            if subscription_id in self._states:
                self._git_adapter.close(registration)
                return SupervisionPreparationResult(
                    status=SupervisionPreparationStatus.REJECTED,
                    failure=SupervisionRuntimeFailure.REGISTRATION_REJECTED,
                )
            self._states[subscription_id] = state
            pending = tuple(self._pending.pop(subscription_id, ()))
            for signal in pending:
                if isinstance(signal, GitRefSignal):
                    self._on_signal_locked(signal)
                else:
                    self._on_native_failure_locked(signal)
            current = self._states.get(subscription_id)
        if current is None or current.lifecycle is not SupervisionRuntimeLifecycle.PREPARED:
            return SupervisionPreparationResult(
                status=SupervisionPreparationStatus.CAPABILITY_UNAVAILABLE,
                failure=(
                    current.failure
                    if current is not None and current.failure is not None
                    else SupervisionRuntimeFailure.NATIVE_NOTIFICATION_UNAVAILABLE
                ),
            )
        return SupervisionPreparationResult(
            status=SupervisionPreparationStatus.PREPARED,
            state=current,
        )

    def start(self, request: SupervisionStartRequest) -> SupervisionStartResult:
        if type(request) is not SupervisionStartRequest:
            return SupervisionStartResult(
                status=SupervisionStartStatus.REJECTED,
                failure=SupervisionRuntimeFailure.EXECUTION_START_REJECTED,
            )
        try:
            trusted = SupervisionStartRequest.model_validate(request, strict=True)
        except ValidationError:
            return SupervisionStartResult(
                status=SupervisionStartStatus.REJECTED,
                failure=SupervisionRuntimeFailure.EXECUTION_START_REJECTED,
            )
        with self._lock:
            state = self._states.get(trusted.subscription_id)
            if state is None or state.lifecycle is not SupervisionRuntimeLifecycle.PREPARED:
                return SupervisionStartResult(
                    status=SupervisionStartStatus.REJECTED,
                    failure=SupervisionRuntimeFailure.EXECUTION_START_REJECTED,
                )
            evidence = trusted.execution_started
            receipt = state.chain.receipt
            if not all(
                (
                    evidence.project_id == receipt.project_id,
                    evidence.ticket_ref == receipt.ticket_reference,
                    evidence.router_receipt_ref == receipt.receipt_id,
                    evidence.task_ref == state.chain.implementation_task_ref,
                    evidence.worktree_ref == receipt.worktree_fingerprint,
                    evidence.branch_ref == receipt.branch_fingerprint,
                    evidence.baseline_commit == receipt.baseline_commit,
                )
            ):
                return SupervisionStartResult(
                    status=SupervisionStartStatus.REJECTED,
                    failure=SupervisionRuntimeFailure.EXECUTION_START_REJECTED,
                )
            started = start_supervision_lease(
                trusted.lease_id,
                trusted.supervision_class,
                evidence,
            )
            if started.lease is None:
                return SupervisionStartResult(
                    status=SupervisionStartStatus.REJECTED,
                    failure=SupervisionRuntimeFailure.EXECUTION_START_REJECTED,
                )
            armed = self._deadline_port.arm(
                DeadlineArmRequest(
                    lease=started.lease,
                    capability=state.chain.deadline_capability,
                )
            )
            if armed.status not in (DeadlineArmStatus.ARMED, DeadlineArmStatus.REPLACED):
                closed_registration = self._git_adapter.close(state.registration)
                closed = close_supervision_lease(started.lease)
                halted = _replace_runtime(
                    state,
                    registration=closed_registration,
                    lease=closed.lease,
                    lifecycle=SupervisionRuntimeLifecycle.HALTED,
                    supervision_decision=closed,
                    failure=SupervisionRuntimeFailure.DEADLINE_UNAVAILABLE,
                )
                self._states[trusted.subscription_id] = halted
                return SupervisionStartResult(
                    status=SupervisionStartStatus.CAPABILITY_UNAVAILABLE,
                    failure=SupervisionRuntimeFailure.DEADLINE_UNAVAILABLE,
                )
            active = _replace_runtime(
                state,
                lease=started.lease,
                lifecycle=SupervisionRuntimeLifecycle.ACTIVE,
                supervision_decision=started,
            )
            self._states[trusted.subscription_id] = active
            return SupervisionStartResult(
                status=SupervisionStartStatus.ACTIVE,
                state=active,
            )

    def read_state(self, subscription_id: SubscriptionId) -> SupervisionRuntimeState | None:
        with self._lock:
            return self._states.get(subscription_id)

    def diagnose(
        self,
        request: ReviewerDiagnosisRequest,
    ) -> ReviewerDiagnosisResult:
        """Route one exact read-only Senior diagnosis without performing task effects."""

        if type(request) is not ReviewerDiagnosisRequest:
            return ReviewerDiagnosisResult(route=ReviewerDiagnosisRoute.REJECTED)
        try:
            trusted = ReviewerDiagnosisRequest.model_validate(request, strict=True)
        except ValidationError:
            return ReviewerDiagnosisResult(route=ReviewerDiagnosisRoute.REJECTED)
        with self._lock:
            state = self._states.get(trusted.subscription_id)
            if (
                state is None
                or state.lifecycle is not SupervisionRuntimeLifecycle.REVIEW_PENDING
                or state.lease is None
                or not self._diagnosis_matches(state, trusted)
                or trusted.observed_at_ms < state.lease.origin_ms
            ):
                return ReviewerDiagnosisResult(route=ReviewerDiagnosisRoute.REJECTED)
            if (
                not trusted.task_stopped_incomplete
                or not trusted.approved_closure_unchanged
            ):
                return ReviewerDiagnosisResult(
                    route=ReviewerDiagnosisRoute.NO_ACTION,
                    state=state,
                )
            lease = state.lease
            if lease.supervision_class is SupervisionClass.LUNA_XHIGH_DEFAULT:
                return ReviewerDiagnosisResult(
                    route=ReviewerDiagnosisRoute.TICKET_REPAIR_REQUIRED,
                    state=state,
                )
            if lease.continue_count == 0:
                return ReviewerDiagnosisResult(
                    route=ReviewerDiagnosisRoute.CONTINUE_IMPLEMENTATION_REQUIRED,
                    state=state,
                )
            decision = reduce_supervision_lease(
                lease,
                LeaseEvent(
                    kind=LeaseEventKind.DIAGNOSIS_STOPPED_INCOMPLETE,
                    occurred_at_ms=trusted.observed_at_ms,
                ),
                state.model_override,
            )
            if (
                decision.decision
                is not SupervisionDecisionKind.MODEL_CAPABILITY_INSUFFICIENT
                or decision.lease is None
            ):
                return ReviewerDiagnosisResult(route=ReviewerDiagnosisRoute.REJECTED)
            closed_registration = self._git_adapter.close(state.registration)
            halted = _replace_runtime(
                state,
                registration=closed_registration,
                lease=decision.lease,
                lifecycle=SupervisionRuntimeLifecycle.HALTED,
                supervision_decision=decision,
                failure=SupervisionRuntimeFailure.MODEL_CAPABILITY_INSUFFICIENT,
            )
            self._states[trusted.subscription_id] = halted
            return ReviewerDiagnosisResult(
                route=ReviewerDiagnosisRoute.MODEL_CAPABILITY_INSUFFICIENT,
                state=halted,
            )

    def confirm_continuation(
        self,
        evidence: ContinuationAcceptedEvidence,
    ) -> ContinuationResult:
        """Resume Terra only after exact host readback proves the one continue effect."""

        if type(evidence) is not ContinuationAcceptedEvidence:
            return ContinuationResult(
                status=ContinuationStatus.REJECTED,
                failure=SupervisionRuntimeFailure.STALE_RUNTIME_EVENT,
            )
        try:
            trusted = ContinuationAcceptedEvidence.model_validate(evidence, strict=True)
        except ValidationError:
            return ContinuationResult(
                status=ContinuationStatus.REJECTED,
                failure=SupervisionRuntimeFailure.STALE_RUNTIME_EVENT,
            )
        with self._lock:
            state = self._states.get(trusted.subscription_id)
            if (
                state is None
                or state.lifecycle is not SupervisionRuntimeLifecycle.REVIEW_PENDING
                or state.lease is None
                or state.lease.supervision_class is not SupervisionClass.TERRA_OR_HIGHER
                or state.lease.lifecycle is not LeaseLifecycle.DIAGNOSIS_PENDING
                or state.lease.continue_count != 0
                or not self._continuation_matches(state, trusted)
                or trusted.accepted_at_ms < state.lease.origin_ms
            ):
                return ContinuationResult(
                    status=ContinuationStatus.REJECTED,
                    failure=SupervisionRuntimeFailure.STALE_RUNTIME_EVENT,
                )
            decision = reduce_supervision_lease(
                state.lease,
                LeaseEvent(
                    kind=LeaseEventKind.DIAGNOSIS_STOPPED_INCOMPLETE,
                    occurred_at_ms=trusted.accepted_at_ms,
                ),
                state.model_override,
            )
            if (
                decision.decision is not SupervisionDecisionKind.CONTINUE_IMPLEMENTATION
                or decision.lease is None
            ):
                return ContinuationResult(
                    status=ContinuationStatus.REJECTED,
                    failure=SupervisionRuntimeFailure.STALE_RUNTIME_EVENT,
                )
            armed = self._deadline_port.arm(
                DeadlineArmRequest(
                    lease=decision.lease,
                    capability=state.chain.deadline_capability,
                )
            )
            if armed.status not in (DeadlineArmStatus.ARMED, DeadlineArmStatus.REPLACED):
                wake = self._wake_capability_fault_locked(
                    state,
                    SupervisionRuntimeFailure.DEADLINE_UNAVAILABLE,
                )
                self._halt_capability_locked(
                    state,
                    SupervisionRuntimeFailure.DEADLINE_UNAVAILABLE,
                    wake_result=wake,
                )
                return ContinuationResult(
                    status=ContinuationStatus.CAPABILITY_UNAVAILABLE,
                    failure=SupervisionRuntimeFailure.DEADLINE_UNAVAILABLE,
                )
            active = _replace_runtime(
                state,
                lease=decision.lease,
                lifecycle=SupervisionRuntimeLifecycle.ACTIVE,
                supervision_decision=decision,
            )
            self._states[trusted.subscription_id] = active
            return ContinuationResult(
                status=ContinuationStatus.RESUMED,
                state=active,
            )

    @staticmethod
    def _diagnosis_matches(
        state: SupervisionRuntimeState,
        request: ReviewerDiagnosisRequest,
    ) -> bool:
        lease = state.lease
        return lease is not None and all(
            (
                request.project_id == lease.project_id,
                request.ticket_ref == lease.ticket_ref,
                request.router_receipt_ref == lease.router_receipt_ref,
                request.task_ref == lease.task_ref,
                request.worktree_ref == lease.worktree_ref,
                request.branch_ref == lease.branch_ref,
            )
        )

    @staticmethod
    def _continuation_matches(
        state: SupervisionRuntimeState,
        evidence: ContinuationAcceptedEvidence,
    ) -> bool:
        lease = state.lease
        return lease is not None and all(
            (
                evidence.project_id == lease.project_id,
                evidence.ticket_ref == lease.ticket_ref,
                evidence.router_receipt_ref == lease.router_receipt_ref,
                evidence.task_ref == lease.task_ref,
                evidence.worktree_ref == lease.worktree_ref,
                evidence.branch_ref == lease.branch_ref,
            )
        )

    def on_signal(self, signal: GitRefSignal) -> None:
        with self._lock:
            if signal.subscription_id not in self._states:
                self._pending.setdefault(signal.subscription_id, []).append(signal)
                return
            self._on_signal_locked(signal)

    def on_failure(self, signal: GitNativeFailureSignal) -> None:
        with self._lock:
            if signal.subscription_id not in self._states:
                self._pending.setdefault(signal.subscription_id, []).append(signal)
                return
            self._on_native_failure_locked(signal)

    def on_deadline(self, signal: DeadlineSignal) -> None:
        with self._lock:
            state = next(
                (
                    candidate
                    for candidate in self._states.values()
                    if candidate.lease is not None
                    and candidate.lease.lease_id == signal.lease_id
                    and candidate.lease.project_id == signal.project_id
                    and candidate.lease.ticket_ref == signal.ticket_ref
                    and candidate.lease.router_receipt_ref == signal.router_receipt_ref
                    and candidate.lease.task_ref == signal.task_ref
                ),
                None,
            )
            if state is None or state.lease is None:
                return
            lease = state.lease
            if (
                state.lifecycle is not SupervisionRuntimeLifecycle.ACTIVE
                or signal.lease_id != lease.lease_id
                or signal.project_id != lease.project_id
                or signal.ticket_ref != lease.ticket_ref
                or signal.router_receipt_ref != lease.router_receipt_ref
                or signal.task_ref != lease.task_ref
            ):
                return
            decision = reduce_supervision_lease(
                lease,
                LeaseEvent(
                    kind=LeaseEventKind.DEADLINE_FIRED,
                    occurred_at_ms=signal.fired_at_ms,
                ),
                state.model_override,
            )
            if decision.decision is SupervisionDecisionKind.EVENT_REJECTED:
                return
            wake_request = RoleWakeRequest(
                attempt_id=_attempt_id(
                    "deadline",
                    state.chain.chain_digest,
                    lease.lease_id,
                    str(lease.deadline_ms),
                ),
                chain=state.chain,
                trigger=RoleWakeTriggerKind.SUPERVISION_DEADLINE,
                observed_commit=None,
                handoff_id=None,
                lease_id=lease.lease_id,
                fault_kind=None,
            )
            wake = self._wake_coordinator.wake(wake_request)
            lifecycle = (
                SupervisionRuntimeLifecycle.REVIEW_PENDING
                if wake.status is RoleWakeStatus.HOST_ACCEPTED
                else SupervisionRuntimeLifecycle.HALTED
            )
            self._states[state.registration.subscription_id] = _replace_runtime(
                state,
                lease=decision.lease,
                lifecycle=lifecycle,
                supervision_decision=decision,
                wake_result=wake,
                failure=(
                    None
                    if lifecycle is SupervisionRuntimeLifecycle.REVIEW_PENDING
                    else SupervisionRuntimeFailure.ROLE_WAKE_UNAVAILABLE
                ),
            )

    def on_deadline_failure(self, signal: DeadlineFailureSignal) -> None:
        with self._lock:
            state = next(
                (
                    candidate
                    for candidate in self._states.values()
                    if candidate.lease is not None and candidate.lease.lease_id == signal.lease_id
                ),
                None,
            )
            if state is not None:
                wake = self._wake_capability_fault_locked(
                    state,
                    SupervisionRuntimeFailure.DEADLINE_UNAVAILABLE,
                )
                self._halt_capability_locked(
                    state,
                    SupervisionRuntimeFailure.DEADLINE_UNAVAILABLE,
                    wake_result=wake,
                )

    def _refresh_chain(
        self,
        state: SupervisionRuntimeState,
        decision: GitEventAdapterDecision,
    ) -> RoleWakeChainProof | None:
        if decision.registration is None:
            return None
        prior = state.chain
        result = preflight_role_wake_chain(
            RoleWakeChainPreflightRequest(
                receipt=prior.receipt,
                registration=decision.registration,
                reviewer_ref=prior.reviewer_ref,
                implementation_task_ref=prior.implementation_task_ref,
                wake_capability=prior.wake_capability,
                deadline_capability=prior.deadline_capability,
            )
        )
        return result.proof if result.status is RoleWakeChainStatus.PROVEN else None

    def _on_signal_locked(self, signal: GitRefSignal) -> None:
        state = self._states.get(signal.subscription_id)
        if state is None or state.lifecycle in (
            SupervisionRuntimeLifecycle.CLOSED,
            SupervisionRuntimeLifecycle.HALTED,
        ):
            return
        decision = self._git_adapter.observe_signal(
            state.registration,
            signal,
            state.handoff_context,
        )
        if decision.decision in (
            GitEventAdapterDecisionKind.SILENT,
            GitEventAdapterDecisionKind.SOURCE_ADVANCED,
        ):
            if decision.registration is None:
                return
            chain = self._refresh_chain(state, decision)
            if chain is None:
                self._halt_capability_locked(
                    state,
                    SupervisionRuntimeFailure.ROLE_WAKE_CHAIN_UNAVAILABLE,
                )
                return
            supervision_decision = state.last_supervision_decision
            next_lease = state.lease
            if (
                decision.decision is GitEventAdapterDecisionKind.SOURCE_ADVANCED
                and state.lease is not None
                and state.lease.lifecycle is LeaseLifecycle.ACTIVE
            ):
                supervision_decision = reduce_supervision_lease(
                    state.lease,
                    LeaseEvent(
                        kind=LeaseEventKind.EXACT_REF_ADVANCED,
                        occurred_at_ms=self._clock.now_ms(),
                    ),
                    state.model_override,
                )
                next_lease = supervision_decision.lease
                if (
                    supervision_decision.decision
                    is SupervisionDecisionKind.SILENT_ACTIVITY_RECORDED
                    and next_lease is not None
                    and next_lease != state.lease
                ):
                    armed = self._deadline_port.arm(
                        DeadlineArmRequest(
                            lease=next_lease,
                            capability=chain.deadline_capability,
                        )
                    )
                    if armed.status not in (
                        DeadlineArmStatus.ARMED,
                        DeadlineArmStatus.REPLACED,
                    ):
                        self._halt_capability_locked(
                            state,
                            SupervisionRuntimeFailure.DEADLINE_UNAVAILABLE,
                        )
                        return
            self._states[signal.subscription_id] = _replace_runtime(
                state,
                registration=decision.registration,
                chain=chain,
                lease=next_lease,
                git_decision=decision,
                supervision_decision=supervision_decision,
            )
            return
        if decision.decision is GitEventAdapterDecisionKind.TERMINAL_HANDOFF_ACCEPTED:
            if state.lease is None or decision.registration is None:
                self._halt_capability_locked(
                    state,
                    SupervisionRuntimeFailure.STALE_RUNTIME_EVENT,
                )
                return
            chain = self._refresh_chain(state, decision)
            if chain is None:
                self._halt_capability_locked(
                    state,
                    SupervisionRuntimeFailure.ROLE_WAKE_CHAIN_UNAVAILABLE,
                )
                return
            closed_lease = reduce_supervision_lease(
                state.lease,
                LeaseEvent(
                    kind=LeaseEventKind.TERMINAL_HANDOFF,
                    occurred_at_ms=self._clock.now_ms(),
                ),
                state.model_override,
            )
            self._deadline_port.cancel(cancel_request_for(state.lease))
            closed_registration = self._git_adapter.close(decision.registration)
            wake_request = wake_request_from_git_decision(
                _attempt_id(
                    "handoff",
                    chain.chain_digest,
                    decision.handoff.handoff_id if decision.handoff is not None else "missing",
                ),
                chain,
                decision,
            )
            if wake_request is None:
                self._halt_capability_locked(
                    state,
                    SupervisionRuntimeFailure.STALE_RUNTIME_EVENT,
                )
                return
            wake = self._wake_coordinator.wake(wake_request)
            lifecycle = (
                SupervisionRuntimeLifecycle.CLOSED
                if wake.status in (
                    RoleWakeStatus.HOST_ACCEPTED,
                    RoleWakeStatus.QUEUED_NO_WAKE,
                )
                else SupervisionRuntimeLifecycle.HALTED
            )
            self._states[signal.subscription_id] = _replace_runtime(
                state,
                registration=closed_registration,
                chain=chain,
                lease=closed_lease.lease,
                lifecycle=lifecycle,
                git_decision=decision,
                supervision_decision=closed_lease,
                wake_result=wake,
                failure=(
                    None
                    if lifecycle is SupervisionRuntimeLifecycle.CLOSED
                    else SupervisionRuntimeFailure.ROLE_WAKE_UNAVAILABLE
                ),
            )
            return
        if decision.decision in (
            GitEventAdapterDecisionKind.INVALID_HANDOFF_FAULT,
            GitEventAdapterDecisionKind.STALE_BINDING_FAULT,
        ):
            wake_request = wake_request_from_git_decision(
                _attempt_id(
                    "git-fault",
                    state.chain.chain_digest,
                    decision.decision.value,
                    decision.registration.last_observed_commit
                    if decision.registration is not None
                    else state.registration.last_observed_commit,
                ),
                state.chain,
                decision,
            )
            if wake_request is not None:
                fault_wake: RoleWakeResult | None = self._wake_coordinator.wake(
                    wake_request
                )
            else:
                fault_wake = None
            self._halt_capability_locked(
                state,
                SupervisionRuntimeFailure.STALE_RUNTIME_EVENT,
                registration=decision.registration,
                git_decision=decision,
                wake_result=fault_wake,
            )
            return
        if decision.decision is GitEventAdapterDecisionKind.READBACK_FAILED:
            wake = self._wake_capability_fault_locked(
                state,
                SupervisionRuntimeFailure.GIT_READBACK_UNAVAILABLE,
            )
            self._halt_capability_locked(
                state,
                SupervisionRuntimeFailure.GIT_READBACK_UNAVAILABLE,
                registration=decision.registration,
                git_decision=decision,
                wake_result=wake,
            )

    def _on_native_failure_locked(self, signal: GitNativeFailureSignal) -> None:
        state = self._states.get(signal.subscription_id)
        if (
            state is None
            or signal.event_source_ref != state.registration.event_source_ref
            or signal.subscription_id != state.registration.subscription_id
        ):
            return
        wake = self._wake_capability_fault_locked(
            state,
            SupervisionRuntimeFailure.NATIVE_NOTIFICATION_UNAVAILABLE,
        )
        self._halt_capability_locked(
            state,
            SupervisionRuntimeFailure.NATIVE_NOTIFICATION_UNAVAILABLE,
            wake_result=wake,
        )

    def _wake_capability_fault_locked(
        self,
        state: SupervisionRuntimeState,
        failure: SupervisionRuntimeFailure,
    ) -> RoleWakeResult:
        return self._wake_coordinator.wake(
            RoleWakeRequest(
                attempt_id=_attempt_id(
                    "capability-fault",
                    state.chain.chain_digest,
                    failure.value,
                    state.registration.last_observed_commit,
                ),
                chain=state.chain,
                trigger=RoleWakeTriggerKind.SUPERVISION_FAULT,
                observed_commit=state.registration.last_observed_commit,
                handoff_id=None,
                lease_id=None,
                fault_kind=SupervisionFaultKind.WAKE_CHAIN_LOST,
            )
        )

    def _halt_capability_locked(
        self,
        state: SupervisionRuntimeState,
        failure: SupervisionRuntimeFailure,
        *,
        registration: GitEventRegistrationState | None = None,
        git_decision: GitEventAdapterDecision | None = None,
        wake_result: RoleWakeResult | None = None,
    ) -> None:
        current_registration = state.registration
        if registration is not None:
            current_registration = registration
        closed_registration = self._git_adapter.close(current_registration)
        closed_decision = state.last_supervision_decision
        closed_lease = state.lease
        if state.lease is not None:
            self._deadline_port.cancel(cancel_request_for(state.lease))
            closed_decision = close_supervision_lease(state.lease, state.model_override)
            closed_lease = closed_decision.lease
        self._states[state.registration.subscription_id] = _replace_runtime(
            state,
            registration=closed_registration,
            lease=closed_lease,
            lifecycle=SupervisionRuntimeLifecycle.HALTED,
            git_decision=git_decision,
            supervision_decision=closed_decision,
            wake_result=wake_result,
            failure=failure,
        )


__all__ = ["ReceiptBoundSupervisionController"]
