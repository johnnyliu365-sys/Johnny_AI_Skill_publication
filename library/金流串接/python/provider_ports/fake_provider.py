"""Deterministic fake payment provider with no network or persistent state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from library.金流串接.python.payment_contracts import PaymentIntent

from .contracts import (
    PaymentProviderPort,
    ProviderAuthorization,
    ProviderAuthorizationResult,
    ProviderAuthorizationSuccess,
    ProviderEvent,
    ProviderEventId,
    ProviderEventResult,
    ProviderEventSuccess,
    ProviderFailure,
    ProviderFailureKind,
    ProviderFinalState,
    ProviderTransactionId,
)


class FakeProviderScenario(str, Enum):
    """Finite, deterministic outcomes for local provider behaviour tests."""

    SUCCESS = "success"
    TIMEOUT = "timeout"
    UNKNOWN_TRANSACTION = "unknown_transaction"


@dataclass(frozen=True, slots=True)
class FakePaymentProvider(PaymentProviderPort):
    """A local provider double that emits typed results only."""

    transaction_id: ProviderTransactionId
    scenario: FakeProviderScenario

    def __post_init__(self) -> None:
        if not isinstance(self.transaction_id, ProviderTransactionId):
            raise TypeError("transaction_id must be a ProviderTransactionId")
        if not isinstance(self.scenario, FakeProviderScenario):
            raise TypeError("scenario must be a FakeProviderScenario")

    def authorize(self, payment_intent: PaymentIntent) -> ProviderAuthorizationResult:
        """Authorize an intent or return the configured typed failure."""
        if not isinstance(payment_intent, PaymentIntent):
            raise TypeError("payment_intent must be a PaymentIntent")
        failure: ProviderFailure | None = self._configured_failure(payment_intent)
        if failure is not None:
            return failure
        authorization: ProviderAuthorization = ProviderAuthorization(
            transaction_id=self.transaction_id,
            payment_intent_id=payment_intent.intent_id,
            idempotency_key=payment_intent.idempotency_key,
        )
        return ProviderAuthorizationSuccess(authorization=authorization)

    def confirm(self, authorization: ProviderAuthorization) -> ProviderEventResult:
        """Emit one typed confirmation event for a known fake authorization."""
        return self._event_result(
            authorization=authorization,
            final_state=ProviderFinalState.CONFIRMED,
            event_prefix="confirm",
        )

    def refund(self, authorization: ProviderAuthorization) -> ProviderEventResult:
        """Emit one typed refund event for a known fake authorization."""
        return self._event_result(
            authorization=authorization,
            final_state=ProviderFinalState.REFUNDED,
            event_prefix="refund",
        )

    def _event_result(
        self,
        authorization: ProviderAuthorization,
        final_state: ProviderFinalState,
        event_prefix: str,
    ) -> ProviderEventResult:
        if not isinstance(authorization, ProviderAuthorization):
            raise TypeError("authorization must be a ProviderAuthorization")
        if authorization.transaction_id != self.transaction_id:
            return ProviderFailure(
                payment_intent_id=authorization.payment_intent_id,
                idempotency_key=authorization.idempotency_key,
                kind=ProviderFailureKind.UNKNOWN_TRANSACTION,
            )
        failure: ProviderFailure | None = self._configured_failure_for_authorization(
            authorization
        )
        if failure is not None:
            return failure
        event: ProviderEvent = ProviderEvent(
            event_id=ProviderEventId(
                value=f"{event_prefix}-{self.transaction_id.value}"
            ),
            transaction_id=self.transaction_id,
            payment_intent_id=authorization.payment_intent_id,
            idempotency_key=authorization.idempotency_key,
            final_state=final_state,
        )
        return ProviderEventSuccess(event=event)

    def _configured_failure(self, payment_intent: PaymentIntent) -> ProviderFailure | None:
        if self.scenario is FakeProviderScenario.TIMEOUT:
            return ProviderFailure(
                payment_intent_id=payment_intent.intent_id,
                idempotency_key=payment_intent.idempotency_key,
                kind=ProviderFailureKind.TIMEOUT,
            )
        if self.scenario is FakeProviderScenario.UNKNOWN_TRANSACTION:
            return ProviderFailure(
                payment_intent_id=payment_intent.intent_id,
                idempotency_key=payment_intent.idempotency_key,
                kind=ProviderFailureKind.UNKNOWN_TRANSACTION,
            )
        return None

    def _configured_failure_for_authorization(
        self, authorization: ProviderAuthorization
    ) -> ProviderFailure | None:
        if self.scenario is FakeProviderScenario.TIMEOUT:
            return ProviderFailure(
                payment_intent_id=authorization.payment_intent_id,
                idempotency_key=authorization.idempotency_key,
                kind=ProviderFailureKind.TIMEOUT,
            )
        if self.scenario is FakeProviderScenario.UNKNOWN_TRANSACTION:
            return ProviderFailure(
                payment_intent_id=authorization.payment_intent_id,
                idempotency_key=authorization.idempotency_key,
                kind=ProviderFailureKind.UNKNOWN_TRANSACTION,
            )
        return None
