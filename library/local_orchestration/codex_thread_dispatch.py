"""One-shot receipt-bound Codex thread dispatch composition."""

from __future__ import annotations

from typing import Protocol

from pydantic import ValidationError

from library.workflow_router.thread_dispatch_contracts import (
    CodexThreadDispatchAttemptRecord,
    CodexThreadDispatchClaimRequest,
    CodexThreadDispatchClaimResult,
    CodexThreadDispatchCommand,
    CodexThreadDispatchEffectResult,
    CodexThreadDispatchEffectStatus,
    CodexThreadDispatchFailure,
    CodexThreadDispatchLifecycle,
    CodexThreadDispatchRequest,
    CodexThreadDispatchResult,
    CodexThreadDispatchSettlementRequest,
    CodexThreadDispatchSettlementResult,
    CodexThreadDispatchStatus,
    DispatchClaimStatus,
    DispatchSettlementStatus,
    dispatch_claim_identity,
)

from .live_dispatch_metadata_store import ThreadDispatchAttemptStorePort


class CodexThreadDispatchPort(Protocol):
    """Injected bridge for exactly one send_message_to_thread invocation."""

    def send(
        self,
        command: CodexThreadDispatchCommand,
    ) -> CodexThreadDispatchEffectResult: ...


def _failed(
    status: CodexThreadDispatchStatus,
    failure: CodexThreadDispatchFailure,
) -> CodexThreadDispatchResult:
    return CodexThreadDispatchResult(status=status, failure=failure)


def _uncertain(
    record: CodexThreadDispatchAttemptRecord | None = None,
) -> CodexThreadDispatchResult:
    return CodexThreadDispatchResult(
        status=CodexThreadDispatchStatus.EFFECT_UNCERTAIN,
        record=record,
        failure=CodexThreadDispatchFailure.EFFECT_UNCERTAIN,
    )


def _from_record(
    record: CodexThreadDispatchAttemptRecord,
) -> CodexThreadDispatchResult:
    if record.lifecycle is CodexThreadDispatchLifecycle.HOST_ACCEPTED:
        return CodexThreadDispatchResult(
            status=CodexThreadDispatchStatus.HOST_ACCEPTED,
            record=record,
        )
    if record.lifecycle is CodexThreadDispatchLifecycle.NO_EFFECT:
        return CodexThreadDispatchResult(
            status=CodexThreadDispatchStatus.NO_EFFECT,
            record=record,
        )
    return _uncertain(record)


class CodexThreadDispatchCoordinator:
    """Claim durably, call the host once, settle, and never retry ambiguity."""

    def __init__(
        self,
        attempt_store: ThreadDispatchAttemptStorePort,
        dispatch_port: CodexThreadDispatchPort,
    ) -> None:
        self._attempt_store = attempt_store
        self._dispatch_port = dispatch_port

    def dispatch(
        self,
        request: CodexThreadDispatchRequest,
    ) -> CodexThreadDispatchResult:
        """Execute at most one host effect for one exact durable claim."""

        if type(request) is not CodexThreadDispatchRequest:
            return _failed(
                CodexThreadDispatchStatus.ATTEMPT_CONFLICT,
                CodexThreadDispatchFailure.ATTEMPT_CONFLICT,
            )
        identity = dispatch_claim_identity(request)
        claim_request = CodexThreadDispatchClaimRequest(identity=identity)
        try:
            claim = self._attempt_store.claim_dispatch_attempt(claim_request)
        except Exception:
            return _failed(
                CodexThreadDispatchStatus.STORAGE_UNAVAILABLE,
                CodexThreadDispatchFailure.STORAGE_UNAVAILABLE,
            )
        try:
            if type(claim) is not CodexThreadDispatchClaimResult:
                return _failed(
                    CodexThreadDispatchStatus.STORAGE_UNAVAILABLE,
                    CodexThreadDispatchFailure.STORAGE_UNAVAILABLE,
                )
            claim = CodexThreadDispatchClaimResult.model_validate(claim)
        except ValidationError:
            return _failed(
                CodexThreadDispatchStatus.STORAGE_UNAVAILABLE,
                CodexThreadDispatchFailure.STORAGE_UNAVAILABLE,
            )
        if claim.status is DispatchClaimStatus.STORAGE_UNAVAILABLE:
            return _failed(
                CodexThreadDispatchStatus.STORAGE_UNAVAILABLE,
                CodexThreadDispatchFailure.STORAGE_UNAVAILABLE,
            )
        if claim.status is DispatchClaimStatus.RECEIPT_UNAVAILABLE:
            return _failed(
                CodexThreadDispatchStatus.RECEIPT_UNAVAILABLE,
                CodexThreadDispatchFailure.RECEIPT_UNAVAILABLE,
            )
        if claim.status is DispatchClaimStatus.ATTEMPT_CONFLICT:
            return _failed(
                CodexThreadDispatchStatus.ATTEMPT_CONFLICT,
                CodexThreadDispatchFailure.ATTEMPT_CONFLICT,
            )
        if claim.record is None:
            return _failed(
                CodexThreadDispatchStatus.STORAGE_UNAVAILABLE,
                CodexThreadDispatchFailure.STORAGE_UNAVAILABLE,
            )
        if claim.status is DispatchClaimStatus.ALREADY_CLAIMED:
            return _from_record(claim.record)

        command = CodexThreadDispatchCommand(
            attempt_id=identity.attempt_id,
            thread_id=identity.thread_id,
            host_id=identity.host_id,
            prompt=request.render_identifiers_only_payload(),
            payload_digest=identity.payload_digest,
        )
        effect = self._invoke_once(command)
        settlement_request = CodexThreadDispatchSettlementRequest(
            identity=identity,
            effect=effect,
        )
        try:
            settlement = self._attempt_store.settle_dispatch_attempt(
                settlement_request
            )
            if type(settlement) is not CodexThreadDispatchSettlementResult:
                return _uncertain(claim.record)
            settlement = CodexThreadDispatchSettlementResult.model_validate(settlement)
        except Exception:
            return _uncertain(claim.record)
        if settlement.status not in (
            DispatchSettlementStatus.SETTLED,
            DispatchSettlementStatus.ALREADY_SETTLED,
        ):
            return _uncertain(claim.record)
        if settlement.record is None:
            return _uncertain(claim.record)
        return _from_record(settlement.record)

    def _invoke_once(
        self,
        command: CodexThreadDispatchCommand,
    ) -> CodexThreadDispatchEffectResult:
        try:
            effect = self._dispatch_port.send(command)
            if type(effect) is not CodexThreadDispatchEffectResult:
                return CodexThreadDispatchEffectResult(
                    status=CodexThreadDispatchEffectStatus.EFFECT_UNCERTAIN
                )
            return CodexThreadDispatchEffectResult.model_validate(effect)
        except Exception:
            return CodexThreadDispatchEffectResult(
                status=CodexThreadDispatchEffectStatus.EFFECT_UNCERTAIN
            )


__all__ = ["CodexThreadDispatchCoordinator", "CodexThreadDispatchPort"]
