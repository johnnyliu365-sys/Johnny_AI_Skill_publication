"""Strongly typed provider contracts for local payment reconciliation tests."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, TypeAlias
import unicodedata

from library.金流串接.python.payment_contracts import (
    IdempotencyKey,
    PaymentIntent,
    PaymentIntentId,
)


class ProviderFinalState(str, Enum):
    """Final states a provider event may claim for one transaction."""

    CONFIRMED = "confirmed"
    REFUNDED = "refunded"


class ProviderFailureKind(str, Enum):
    """Finite provider failure categories safe for reconciliation decisions."""

    TIMEOUT = "timeout"
    UNKNOWN_TRANSACTION = "unknown_transaction"
    CONFLICTING_FINAL_STATE = "conflicting_final_state"


@dataclass(frozen=True, slots=True)
class ProviderTransactionId:
    """A validated provider-neutral transaction identifier."""

    value: str

    def __post_init__(self) -> None:
        _validate_identifier(value=self.value, type_name="ProviderTransactionId")


@dataclass(frozen=True, slots=True)
class ProviderEventId:
    """A validated provider event identifier used for replay protection."""

    value: str

    def __post_init__(self) -> None:
        _validate_identifier(value=self.value, type_name="ProviderEventId")


@dataclass(frozen=True, slots=True)
class ProviderAuthorization:
    """A fake-provider authorization bound to exactly one local payment intent."""

    transaction_id: ProviderTransactionId
    payment_intent_id: PaymentIntentId
    idempotency_key: IdempotencyKey

    def __post_init__(self) -> None:
        if not isinstance(self.transaction_id, ProviderTransactionId):
            raise TypeError("transaction_id must be a ProviderTransactionId")
        if not isinstance(self.payment_intent_id, PaymentIntentId):
            raise TypeError("payment_intent_id must be a PaymentIntentId")
        if not isinstance(self.idempotency_key, IdempotencyKey):
            raise TypeError("idempotency_key must be an IdempotencyKey")


@dataclass(frozen=True, slots=True)
class ProviderEvent:
    """A verified provider event that reconciliation may inspect once."""

    event_id: ProviderEventId
    transaction_id: ProviderTransactionId
    payment_intent_id: PaymentIntentId
    idempotency_key: IdempotencyKey
    final_state: ProviderFinalState

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, ProviderEventId):
            raise TypeError("event_id must be a ProviderEventId")
        if not isinstance(self.transaction_id, ProviderTransactionId):
            raise TypeError("transaction_id must be a ProviderTransactionId")
        if not isinstance(self.payment_intent_id, PaymentIntentId):
            raise TypeError("payment_intent_id must be a PaymentIntentId")
        if not isinstance(self.idempotency_key, IdempotencyKey):
            raise TypeError("idempotency_key must be an IdempotencyKey")
        if not isinstance(self.final_state, ProviderFinalState):
            raise TypeError("final_state must be a ProviderFinalState")


@dataclass(frozen=True, slots=True)
class ProviderAuthorizationSuccess:
    """Typed success result for a local authorization request."""

    authorization: ProviderAuthorization

    def __post_init__(self) -> None:
        if not isinstance(self.authorization, ProviderAuthorization):
            raise TypeError("authorization must be a ProviderAuthorization")


@dataclass(frozen=True, slots=True)
class ProviderEventSuccess:
    """Typed success result for confirmation or refund provider events."""

    event: ProviderEvent

    def __post_init__(self) -> None:
        if not isinstance(self.event, ProviderEvent):
            raise TypeError("event must be a ProviderEvent")


@dataclass(frozen=True, slots=True)
class ProviderFailure:
    """A provider failure with no raw response, secret or transport detail."""

    payment_intent_id: PaymentIntentId
    idempotency_key: IdempotencyKey
    kind: ProviderFailureKind

    def __post_init__(self) -> None:
        if not isinstance(self.payment_intent_id, PaymentIntentId):
            raise TypeError("payment_intent_id must be a PaymentIntentId")
        if not isinstance(self.idempotency_key, IdempotencyKey):
            raise TypeError("idempotency_key must be an IdempotencyKey")
        if not isinstance(self.kind, ProviderFailureKind):
            raise TypeError("kind must be a ProviderFailureKind")


ProviderAuthorizationResult: TypeAlias = ProviderAuthorizationSuccess | ProviderFailure
ProviderEventResult: TypeAlias = ProviderEventSuccess | ProviderFailure


class PaymentProviderPort(Protocol):
    """Provider port exposing only typed, transport-free outcomes."""

    def authorize(self, payment_intent: PaymentIntent) -> ProviderAuthorizationResult:
        """Authorize one local payment intent."""

    def confirm(self, authorization: ProviderAuthorization) -> ProviderEventResult:
        """Return a confirmation event for a known authorization."""

    def refund(self, authorization: ProviderAuthorization) -> ProviderEventResult:
        """Return a refund event for a known authorization."""


def _validate_identifier(value: str, type_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{type_name} value must be a str")
    if not value or value != value.strip():
        raise ValueError(f"{type_name} value cannot be blank or padded")
    character: str
    for character in value:
        category: str = unicodedata.category(character)
        if category.startswith("C"):
            raise ValueError(f"{type_name} value cannot contain control characters")
