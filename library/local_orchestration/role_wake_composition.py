"""Claim-before-effect composition for one receipt-bound reviewer wake."""

from __future__ import annotations

from typing import Protocol

from pydantic import ValidationError

from library.workflow_router.role_wake_contracts import (
    RoleWakeAttemptClaimRequest,
    RoleWakeAttemptClaimResult,
    RoleWakeAttemptLifecycle,
    RoleWakeAttemptRecord,
    RoleWakeAttemptSettleRequest,
    RoleWakeAttemptSettleResult,
    RoleWakeCommand,
    RoleWakeEffectResult,
    RoleWakeEffectStatus,
    RoleWakeRequest,
    RoleWakeResult,
    RoleWakeStatus,
    RoleWakeTriggerKind,
    WakeAttemptClaimStatus,
    WakeAttemptSettleStatus,
    derive_role_wake_attempt_identity,
)


class RoleWakeAttemptStorePort(Protocol):
    """Durable compare-and-swap boundary for non-retryable wake effects."""

    def claim(self, request: RoleWakeAttemptClaimRequest) -> RoleWakeAttemptClaimResult: ...

    def settle(self, request: RoleWakeAttemptSettleRequest) -> RoleWakeAttemptSettleResult: ...


class RoleWakeAttemptBoundaryPort(Protocol):
    """Installer-owned wake-attempt methods on the durable metadata boundary."""

    def claim_role_wake_attempt(
        self,
        request: RoleWakeAttemptClaimRequest,
    ) -> RoleWakeAttemptClaimResult: ...

    def settle_role_wake_attempt(
        self,
        request: RoleWakeAttemptSettleRequest,
    ) -> RoleWakeAttemptSettleResult: ...


class DurableRoleWakeAttemptStore:
    """Strict adapter from the shared durable boundary to wake-store names."""

    def __init__(self, boundary: RoleWakeAttemptBoundaryPort) -> None:
        self._boundary = boundary

    def claim(self, request: RoleWakeAttemptClaimRequest) -> RoleWakeAttemptClaimResult:
        try:
            result = self._boundary.claim_role_wake_attempt(request)
            return RoleWakeAttemptClaimResult.model_validate(result, strict=True)
        except Exception:
            return RoleWakeAttemptClaimResult(
                status=WakeAttemptClaimStatus.STORAGE_UNAVAILABLE
            )

    def settle(self, request: RoleWakeAttemptSettleRequest) -> RoleWakeAttemptSettleResult:
        try:
            result = self._boundary.settle_role_wake_attempt(request)
            return RoleWakeAttemptSettleResult.model_validate(result, strict=True)
        except Exception:
            return RoleWakeAttemptSettleResult(
                status=WakeAttemptSettleStatus.STORAGE_UNAVAILABLE
            )


class RoleWakePort(Protocol):
    """Injected host bridge for exactly one reviewer wake invocation."""

    def wake(self, command: RoleWakeCommand) -> RoleWakeEffectResult: ...


def _result_from_record(record: RoleWakeAttemptRecord) -> RoleWakeResult:
    if record.lifecycle is RoleWakeAttemptLifecycle.HOST_ACCEPTED:
        return RoleWakeResult(status=RoleWakeStatus.HOST_ACCEPTED, record=record)
    if record.lifecycle is RoleWakeAttemptLifecycle.NO_EFFECT:
        return RoleWakeResult(status=RoleWakeStatus.NO_EFFECT, record=record)
    if record.lifecycle is RoleWakeAttemptLifecycle.EFFECT_UNCERTAIN:
        return RoleWakeResult(status=RoleWakeStatus.EFFECT_UNCERTAIN, record=record)
    return RoleWakeResult(status=RoleWakeStatus.EFFECT_UNCERTAIN)


class RoleWakeCoordinator:
    """Persist a claim, call the named reviewer once, settle, never retry ambiguity."""

    def __init__(
        self,
        attempt_store: RoleWakeAttemptStorePort,
        wake_port: RoleWakePort,
    ) -> None:
        self._attempt_store = attempt_store
        self._wake_port = wake_port

    def wake(self, request: RoleWakeRequest) -> RoleWakeResult:
        if type(request) is not RoleWakeRequest:
            return RoleWakeResult(status=RoleWakeStatus.ATTEMPT_CONFLICT)
        try:
            trusted = RoleWakeRequest.model_validate(request, strict=True)
        except ValidationError:
            return RoleWakeResult(status=RoleWakeStatus.ATTEMPT_CONFLICT)
        if (
            trusted.trigger is RoleWakeTriggerKind.REVIEW_HANDOFF
            and trusted.review_instruction is None
        ):
            return RoleWakeResult(status=RoleWakeStatus.ATTEMPT_CONFLICT)
        identity = derive_role_wake_attempt_identity(trusted)
        try:
            claim = self._attempt_store.claim(
                RoleWakeAttemptClaimRequest(identity=identity)
            )
            claim = RoleWakeAttemptClaimResult.model_validate(claim, strict=True)
        except Exception:
            return RoleWakeResult(status=RoleWakeStatus.STORAGE_UNAVAILABLE)
        if claim.status is WakeAttemptClaimStatus.STORAGE_UNAVAILABLE:
            return RoleWakeResult(status=RoleWakeStatus.STORAGE_UNAVAILABLE)
        if claim.status is WakeAttemptClaimStatus.ATTEMPT_CONFLICT:
            return RoleWakeResult(status=RoleWakeStatus.ATTEMPT_CONFLICT)
        if claim.record is None:
            return RoleWakeResult(status=RoleWakeStatus.STORAGE_UNAVAILABLE)
        if claim.status is WakeAttemptClaimStatus.ALREADY_CLAIMED:
            return _result_from_record(claim.record)

        wake = trusted.chain.wake_capability
        payload = trusted.render_identifiers_only_payload()
        command = RoleWakeCommand(
            attempt_id=trusted.attempt_id,
            reviewer_task_id=wake.reviewer_task_id,
            reviewer_thread_id=wake.reviewer_thread_id,
            host_id=wake.host_id,
            payload=payload,
            payload_digest=identity.payload_digest,
        )
        effect = self._invoke_once(command)
        try:
            settlement = self._attempt_store.settle(
                RoleWakeAttemptSettleRequest(identity=identity, effect=effect)
            )
            settlement = RoleWakeAttemptSettleResult.model_validate(
                settlement,
                strict=True,
            )
        except Exception:
            return RoleWakeResult(status=RoleWakeStatus.EFFECT_UNCERTAIN)
        if settlement.status not in (
            WakeAttemptSettleStatus.SETTLED,
            WakeAttemptSettleStatus.ALREADY_SETTLED,
        ) or settlement.record is None:
            return RoleWakeResult(status=RoleWakeStatus.EFFECT_UNCERTAIN)
        return _result_from_record(settlement.record)

    def _invoke_once(self, command: RoleWakeCommand) -> RoleWakeEffectResult:
        try:
            effect = self._wake_port.wake(command)
            if type(effect) is not RoleWakeEffectResult:
                return RoleWakeEffectResult(
                    status=RoleWakeEffectStatus.EFFECT_UNCERTAIN
                )
            return RoleWakeEffectResult.model_validate(effect, strict=True)
        except Exception:
            return RoleWakeEffectResult(status=RoleWakeEffectStatus.EFFECT_UNCERTAIN)


__all__ = [
    "DurableRoleWakeAttemptStore",
    "RoleWakeAttemptBoundaryPort",
    "RoleWakeAttemptStorePort",
    "RoleWakeCoordinator",
    "RoleWakePort",
]
