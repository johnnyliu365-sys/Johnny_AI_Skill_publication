"""Claim-once metadata runtime with one injected guarded decision."""

from __future__ import annotations

from enum import Enum
from hashlib import sha256
from typing import Protocol

from .runtime_contracts import (
    EvidenceDigest,
    EventId,
    FastForwardBlocked,
    GuardedBlockReason,
    GuardedDecision,
    GuardedDecisionRequest,
    MetadataCheckpoint,
    RouterResumeRequest,
    RouterResumeResult,
    RouterResumeStatus,
    RuntimeCompleted,
    RuntimeEvent,
    RuntimeFailureCode,
    RuntimeHalted,
    RuntimeHaltReason,
    RuntimeNeedsUserAction,
    RuntimePortError,
    RuntimeResult,
    RuntimeStatus,
)


class EventClaimResult(str, Enum):
    CLAIMED = "CLAIMED"
    REPLAYED = "REPLAYED"


class CheckpointWriteResult(str, Enum):
    SAVED = "SAVED"


class MetadataEventStorePort(Protocol):
    def claim(self, event_id: EventId) -> EventClaimResult: ...

    def save(self, checkpoint: MetadataCheckpoint) -> CheckpointWriteResult: ...


class RuntimeRouterPort(Protocol):
    def resume(self, request: RouterResumeRequest) -> RouterResumeResult: ...


class GuardedDecisionPort(Protocol):
    def decide(self, request: GuardedDecisionRequest) -> GuardedDecision: ...


class InMemoryMetadataEventStore:
    def __init__(self) -> None:
        self._claimed: set[str] = set()
        self._checkpoints: list[MetadataCheckpoint] = []
        self._fail_claim = False
        self.claim_calls = 0

    @property
    def checkpoints(self) -> tuple[MetadataCheckpoint, ...]:
        return tuple(self._checkpoints)

    def serialized_checkpoints(self) -> tuple[str, ...]:
        return tuple(checkpoint.model_dump_json() for checkpoint in self._checkpoints)

    def fail_next_claim(self) -> None:
        self._fail_claim = True

    def claim(self, event_id: EventId) -> EventClaimResult:
        self.claim_calls += 1
        if self._fail_claim:
            self._fail_claim = False
            raise RuntimePortError(RuntimeFailureCode.EVENT_CLAIM)
        if event_id.value in self._claimed:
            return EventClaimResult.REPLAYED
        self._claimed.add(event_id.value)
        return EventClaimResult.CLAIMED

    def save(self, checkpoint: MetadataCheckpoint) -> CheckpointWriteResult:
        self._checkpoints.append(checkpoint)
        return CheckpointWriteResult.SAVED


class FakeRuntimeRouter:
    def __init__(self, status: RouterResumeStatus = RouterResumeStatus.COMPLETED) -> None:
        self.status = status
        self._fail_resume = False
        self.resume_calls = 0
        self.requests: list[RouterResumeRequest] = []

    def fail_next_resume(self) -> None:
        self._fail_resume = True

    def resume(self, request: RouterResumeRequest) -> RouterResumeResult:
        self.resume_calls += 1
        self.requests.append(request)
        if self._fail_resume:
            self._fail_resume = False
            raise RuntimePortError(RuntimeFailureCode.ROUTER_RESUME)
        return RouterResumeResult(status=self.status)


class ResumeOrchestration:
    def __init__(
        self,
        store: MetadataEventStorePort,
        router: RuntimeRouterPort,
        guarded: GuardedDecisionPort,
    ) -> None:
        self._store = store
        self._router = router
        self._guarded = guarded

    def resume(self, event: RuntimeEvent) -> RuntimeResult:
        try:
            claim = self._store.claim(event.event_id)
        except RuntimePortError:
            return self._halt(event, RuntimeHaltReason.EVENT_CLAIM_FAILED, persist=False)
        if claim is EventClaimResult.REPLAYED:
            return self._halt(event, RuntimeHaltReason.REPLAYED, persist=False)
        try:
            router_result = self._router.resume(RouterResumeRequest.from_event(event))
        except RuntimePortError:
            return self._halt(event, RuntimeHaltReason.ROUTER_RESUME_FAILED)
        if router_result.status is RouterResumeStatus.NEEDS_USER_ACTION:
            checkpoint = self._checkpoint(event, RuntimeStatus.NEEDS_USER_ACTION)
            self._store.save(checkpoint)
            return RuntimeNeedsUserAction(checkpoint=checkpoint)
        if router_result.status is RouterResumeStatus.HALTED:
            return self._halt(event, RuntimeHaltReason.ROUTER_HALTED)
        try:
            decision = self._guarded.decide(GuardedDecisionRequest.from_event(event))
        except RuntimePortError as error:
            reason = (
                RuntimeHaltReason.REGISTRY_RESOLVE_FAILED
                if error.code is RuntimeFailureCode.REGISTRY_RESOLVE
                else RuntimeHaltReason.GUARDED_DECISION_FAILED
            )
            return self._halt(event, reason)
        if isinstance(decision, FastForwardBlocked):
            return self._halt(event, _runtime_reason(decision.reason))
        checkpoint = self._checkpoint(event, RuntimeStatus.COMPLETED)
        self._store.save(checkpoint)
        return RuntimeCompleted(checkpoint=checkpoint)

    def _halt(
        self, event: RuntimeEvent, reason: RuntimeHaltReason, persist: bool = True
    ) -> RuntimeHalted:
        checkpoint = self._checkpoint(event, RuntimeStatus.HALTED)
        if persist:
            self._store.save(checkpoint)
        return RuntimeHalted(reason=reason, checkpoint=checkpoint)

    @staticmethod
    def _checkpoint(event: RuntimeEvent, status: RuntimeStatus) -> MetadataCheckpoint:
        metadata = "|".join(
            (
                event.event_id.value,
                event.installation_id.value,
                event.project.value,
                event.expected_base.value,
                event.correlation_id.value,
                status.value,
            )
        )
        return MetadataCheckpoint(
            event_id=event.event_id,
            installation_id=event.installation_id,
            project=event.project,
            expected_base=event.expected_base,
            correlation_id=event.correlation_id,
            status=status,
            evidence_digest=EvidenceDigest(value="sha256-" + sha256(metadata.encode()).hexdigest()),
        )


def _runtime_reason(reason: GuardedBlockReason) -> RuntimeHaltReason:
    return RuntimeHaltReason(reason.value)
