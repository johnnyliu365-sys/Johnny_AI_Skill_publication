"""Strongly typed, provider-free payment value objects and intent states."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import unicodedata


class CurrencyCode(str, Enum):
    """Supported explicit currency codes for the first reusable contract set."""

    TWD = "TWD"
    USD = "USD"
    JPY = "JPY"
    EUR = "EUR"


class PaymentStatus(str, Enum):
    """Finite lifecycle states for one payment intent."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


@dataclass(frozen=True, slots=True)
class Money:
    """A non-negative integral amount in the currency's smallest unit."""

    minor_units: int
    currency: CurrencyCode

    def __post_init__(self) -> None:
        if type(self.minor_units) is not int:
            raise TypeError("minor_units must be an int, not a float or bool")
        if self.minor_units < 0:
            raise ValueError("minor_units cannot be negative")
        if not isinstance(self.currency, CurrencyCode):
            raise TypeError("currency must be a CurrencyCode")


@dataclass(frozen=True, slots=True)
class PaymentIntentId:
    """A validated identifier for one payment intent."""

    value: str

    def __post_init__(self) -> None:
        _validate_identifier(value=self.value, type_name="PaymentIntentId")


@dataclass(frozen=True, slots=True)
class IdempotencyKey:
    """A validated caller key that prevents duplicate payment effects."""

    value: str

    def __post_init__(self) -> None:
        _validate_identifier(value=self.value, type_name="IdempotencyKey")


@dataclass(frozen=True, slots=True)
class EntitlementId:
    """A validated identifier for the entitlement granted after confirmation."""

    value: str

    def __post_init__(self) -> None:
        _validate_identifier(value=self.value, type_name="EntitlementId")


@dataclass(frozen=True, slots=True)
class PaymentIntent:
    """One paid-benefit request with an explicit, validated lifecycle state."""

    intent_id: PaymentIntentId
    idempotency_key: IdempotencyKey
    amount: Money
    entitlement_id: EntitlementId
    status: PaymentStatus

    def __post_init__(self) -> None:
        if not isinstance(self.intent_id, PaymentIntentId):
            raise TypeError("intent_id must be a PaymentIntentId")
        if not isinstance(self.idempotency_key, IdempotencyKey):
            raise TypeError("idempotency_key must be an IdempotencyKey")
        if not isinstance(self.amount, Money):
            raise TypeError("amount must be Money")
        if self.amount.minor_units <= 0:
            raise ValueError("payment intent amount must be positive")
        if not isinstance(self.entitlement_id, EntitlementId):
            raise TypeError("entitlement_id must be an EntitlementId")
        if not isinstance(self.status, PaymentStatus):
            raise TypeError("status must be a PaymentStatus")

    def can_transition_to(self, target_status: PaymentStatus) -> bool:
        """Return whether a state change is permitted by the local lifecycle."""
        if not isinstance(target_status, PaymentStatus):
            raise TypeError("target_status must be a PaymentStatus")
        if self.status is PaymentStatus.PENDING:
            return target_status in (PaymentStatus.CONFIRMED, PaymentStatus.CANCELLED)
        if self.status is PaymentStatus.CONFIRMED:
            return target_status is PaymentStatus.REFUNDED
        return False

    def transitioned_to(self, target_status: PaymentStatus) -> PaymentIntent:
        """Create the next immutable intent or reject an invalid state transition."""
        if not self.can_transition_to(target_status):
            raise ValueError("payment state transition is not allowed")
        return PaymentIntent(
            intent_id=self.intent_id,
            idempotency_key=self.idempotency_key,
            amount=self.amount,
            entitlement_id=self.entitlement_id,
            status=target_status,
        )


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
