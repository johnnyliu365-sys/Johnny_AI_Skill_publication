"""Immutable append-only subscription ledger without a database or provider."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from library.金流串接.python.payment_contracts import (
    EntitlementId,
    IdempotencyKey,
    PaymentIntent,
    PaymentIntentId,
    PaymentStatus,
)


class LedgerEventKind(str, Enum):
    """All immutable facts that this local ledger can record."""

    PAYMENT_CONFIRMED = "payment_confirmed"
    PAYMENT_CANCELLED = "payment_cancelled"
    PAYMENT_REFUNDED = "payment_refunded"
    SUBSCRIPTION_GRANTED = "subscription_granted"
    SUBSCRIPTION_EXPIRED = "subscription_expired"


class EntitlementStatus(str, Enum):
    """Finite state for one subscription entitlement value object."""

    ACTIVE = "active"
    EXPIRED = "expired"


class LedgerRejectionReason(str, Enum):
    """Named fail-closed reasons for ledger operations."""

    DUPLICATE_IDEMPOTENCY_KEY = "duplicate_idempotency_key"
    INVALID_STATUS_TRANSITION = "invalid_status_transition"
    DUPLICATE_REFUND = "duplicate_refund"
    UNKNOWN_PAYMENT_INTENT = "unknown_payment_intent"
    UNKNOWN_ENTITLEMENT = "unknown_entitlement"
    DUPLICATE_EXPIRATION = "duplicate_expiration"


@dataclass(frozen=True, slots=True)
class LedgerSequence:
    """A one-based, append-only position in this ledger snapshot."""

    value: int

    def __post_init__(self) -> None:
        if type(self.value) is not int:
            raise TypeError("ledger sequence must be an int")
        if self.value <= 0:
            raise ValueError("ledger sequence must be positive")


@dataclass(frozen=True, slots=True)
class SubscriptionEntitlement:
    """A benefit derived from a confirmed payment, not from provider data."""

    entitlement_id: EntitlementId
    payment_intent_id: PaymentIntentId
    status: EntitlementStatus

    def __post_init__(self) -> None:
        if not isinstance(self.entitlement_id, EntitlementId):
            raise TypeError("entitlement_id must be an EntitlementId")
        if not isinstance(self.payment_intent_id, PaymentIntentId):
            raise TypeError("payment_intent_id must be a PaymentIntentId")
        if not isinstance(self.status, EntitlementStatus):
            raise TypeError("status must be an EntitlementStatus")

    def expired(self) -> SubscriptionEntitlement:
        """Return a distinct expired value after an active entitlement is recorded."""
        if self.status is not EntitlementStatus.ACTIVE:
            raise ValueError("only active entitlements can expire")
        return SubscriptionEntitlement(
            entitlement_id=self.entitlement_id,
            payment_intent_id=self.payment_intent_id,
            status=EntitlementStatus.EXPIRED,
        )


@dataclass(frozen=True, slots=True)
class LedgerEvent:
    """One append-only payment or subscription fact."""

    sequence: LedgerSequence
    kind: LedgerEventKind
    payment_intent_id: PaymentIntentId | None
    entitlement_id: EntitlementId | None
    idempotency_key: IdempotencyKey | None

    def __post_init__(self) -> None:
        if not isinstance(self.sequence, LedgerSequence):
            raise TypeError("sequence must be a LedgerSequence")
        if not isinstance(self.kind, LedgerEventKind):
            raise TypeError("kind must be a LedgerEventKind")
        if self.payment_intent_id is not None and not isinstance(
            self.payment_intent_id, PaymentIntentId
        ):
            raise TypeError("payment_intent_id must be a PaymentIntentId or None")
        if self.entitlement_id is not None and not isinstance(
            self.entitlement_id, EntitlementId
        ):
            raise TypeError("entitlement_id must be an EntitlementId or None")
        if self.idempotency_key is not None and not isinstance(
            self.idempotency_key, IdempotencyKey
        ):
            raise TypeError("idempotency_key must be an IdempotencyKey or None")
        _validate_event_references(self)


@dataclass(frozen=True, slots=True)
class LedgerAccepted:
    """An operation that returned a new immutable ledger snapshot."""

    ledger: SubscriptionLedger
    payment_intent: PaymentIntent | None
    entitlement: SubscriptionEntitlement | None

    def __post_init__(self) -> None:
        if not isinstance(self.ledger, SubscriptionLedger):
            raise TypeError("ledger must be a SubscriptionLedger")
        if self.payment_intent is not None and not isinstance(
            self.payment_intent, PaymentIntent
        ):
            raise TypeError("payment_intent must be a PaymentIntent or None")
        if self.entitlement is not None and not isinstance(
            self.entitlement, SubscriptionEntitlement
        ):
            raise TypeError("entitlement must be a SubscriptionEntitlement or None")


@dataclass(frozen=True, slots=True)
class LedgerRejected:
    """A fail-closed operation that preserves the current ledger snapshot."""

    ledger: SubscriptionLedger
    reason: LedgerRejectionReason

    def __post_init__(self) -> None:
        if not isinstance(self.ledger, SubscriptionLedger):
            raise TypeError("ledger must be a SubscriptionLedger")
        if not isinstance(self.reason, LedgerRejectionReason):
            raise TypeError("reason must be a LedgerRejectionReason")


LedgerOperationResult: TypeAlias = LedgerAccepted | LedgerRejected


@dataclass(frozen=True, slots=True)
class SubscriptionLedger:
    """An append-only local ledger that returns a new snapshot for each operation."""

    events: tuple[LedgerEvent, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.events, tuple):
            raise TypeError("events must be a tuple")
        expected_sequence: int = 1
        event: LedgerEvent
        for event in self.events:
            if not isinstance(event, LedgerEvent):
                raise TypeError("events must contain LedgerEvent values")
            if event.sequence.value != expected_sequence:
                raise ValueError("ledger event sequences must be continuous")
            expected_sequence += 1

    @classmethod
    def empty(cls) -> SubscriptionLedger:
        """Start a local ledger with no recorded facts."""
        no_events: tuple[LedgerEvent, ...] = ()
        return cls(events=no_events)

    def confirm_payment(self, payment_intent: PaymentIntent) -> LedgerOperationResult:
        """Confirm once and grant exactly one entitlement for a new key."""
        _require_payment_intent(payment_intent)
        if self._has_idempotency_key(payment_intent.idempotency_key):
            return self._rejected(LedgerRejectionReason.DUPLICATE_IDEMPOTENCY_KEY)
        if not payment_intent.can_transition_to(PaymentStatus.CONFIRMED):
            return self._rejected(LedgerRejectionReason.INVALID_STATUS_TRANSITION)

        confirmed_intent: PaymentIntent = payment_intent.transitioned_to(
            PaymentStatus.CONFIRMED
        )
        active_entitlement: SubscriptionEntitlement = SubscriptionEntitlement(
            entitlement_id=payment_intent.entitlement_id,
            payment_intent_id=payment_intent.intent_id,
            status=EntitlementStatus.ACTIVE,
        )
        confirmed_event: LedgerEvent = self._payment_event(
            kind=LedgerEventKind.PAYMENT_CONFIRMED,
            payment_intent=payment_intent,
        )
        granted_event: LedgerEvent = self._grant_event(
            payment_intent=payment_intent,
            entitlement=active_entitlement,
            sequence_offset=1,
        )
        next_ledger: SubscriptionLedger = self._append(
            (confirmed_event, granted_event)
        )
        return LedgerAccepted(
            ledger=next_ledger,
            payment_intent=confirmed_intent,
            entitlement=active_entitlement,
        )

    def cancel_payment(self, payment_intent: PaymentIntent) -> LedgerOperationResult:
        """Record cancellation only from the pending state."""
        _require_payment_intent(payment_intent)
        if self._has_idempotency_key(payment_intent.idempotency_key):
            return self._rejected(LedgerRejectionReason.DUPLICATE_IDEMPOTENCY_KEY)
        if not payment_intent.can_transition_to(PaymentStatus.CANCELLED):
            return self._rejected(LedgerRejectionReason.INVALID_STATUS_TRANSITION)

        cancelled_intent: PaymentIntent = payment_intent.transitioned_to(
            PaymentStatus.CANCELLED
        )
        cancelled_event: LedgerEvent = self._payment_event(
            kind=LedgerEventKind.PAYMENT_CANCELLED,
            payment_intent=payment_intent,
        )
        next_ledger: SubscriptionLedger = self._append((cancelled_event,))
        return LedgerAccepted(
            ledger=next_ledger,
            payment_intent=cancelled_intent,
            entitlement=None,
        )

    def refund_payment(self, payment_intent: PaymentIntent) -> LedgerOperationResult:
        """Record one refund for a ledger-confirmed payment only."""
        _require_payment_intent(payment_intent)
        if self._has_payment_event(
            kind=LedgerEventKind.PAYMENT_REFUNDED,
            payment_intent_id=payment_intent.intent_id,
        ):
            return self._rejected(LedgerRejectionReason.DUPLICATE_REFUND)
        if not payment_intent.can_transition_to(PaymentStatus.REFUNDED):
            return self._rejected(LedgerRejectionReason.INVALID_STATUS_TRANSITION)
        if not self._has_payment_event(
            kind=LedgerEventKind.PAYMENT_CONFIRMED,
            payment_intent_id=payment_intent.intent_id,
        ):
            return self._rejected(LedgerRejectionReason.UNKNOWN_PAYMENT_INTENT)

        refunded_intent: PaymentIntent = payment_intent.transitioned_to(
            PaymentStatus.REFUNDED
        )
        refunded_event: LedgerEvent = self._payment_event(
            kind=LedgerEventKind.PAYMENT_REFUNDED,
            payment_intent=payment_intent,
        )
        next_ledger: SubscriptionLedger = self._append((refunded_event,))
        return LedgerAccepted(
            ledger=next_ledger,
            payment_intent=refunded_intent,
            entitlement=None,
        )

    def expire_entitlement(
        self, entitlement: SubscriptionEntitlement
    ) -> LedgerOperationResult:
        """Record expiry as a fact distinct from cancellation and refund."""
        if not isinstance(entitlement, SubscriptionEntitlement):
            raise TypeError("entitlement must be a SubscriptionEntitlement")
        if self._has_entitlement_event(
            kind=LedgerEventKind.SUBSCRIPTION_EXPIRED,
            entitlement_id=entitlement.entitlement_id,
        ):
            return self._rejected(LedgerRejectionReason.DUPLICATE_EXPIRATION)
        if entitlement.status is not EntitlementStatus.ACTIVE:
            return self._rejected(LedgerRejectionReason.INVALID_STATUS_TRANSITION)
        if not self._has_entitlement_event(
            kind=LedgerEventKind.SUBSCRIPTION_GRANTED,
            entitlement_id=entitlement.entitlement_id,
        ):
            return self._rejected(LedgerRejectionReason.UNKNOWN_ENTITLEMENT)

        expired_entitlement: SubscriptionEntitlement = entitlement.expired()
        expired_event: LedgerEvent = LedgerEvent(
            sequence=self._next_sequence(sequence_offset=0),
            kind=LedgerEventKind.SUBSCRIPTION_EXPIRED,
            payment_intent_id=None,
            entitlement_id=entitlement.entitlement_id,
            idempotency_key=None,
        )
        next_ledger: SubscriptionLedger = self._append((expired_event,))
        return LedgerAccepted(
            ledger=next_ledger,
            payment_intent=None,
            entitlement=expired_entitlement,
        )

    def _append(self, events_to_append: tuple[LedgerEvent, ...]) -> SubscriptionLedger:
        """Return the next snapshot without changing existing tuple members."""
        return SubscriptionLedger(events=self.events + events_to_append)

    def _rejected(self, reason: LedgerRejectionReason) -> LedgerRejected:
        """Preserve this snapshot when a requested action is invalid or duplicate."""
        return LedgerRejected(ledger=self, reason=reason)

    def _next_sequence(self, sequence_offset: int) -> LedgerSequence:
        """Produce the sequence reserved for an event appended in this operation."""
        if type(sequence_offset) is not int or sequence_offset < 0:
            raise ValueError("sequence_offset must be a non-negative int")
        return LedgerSequence(value=len(self.events) + sequence_offset + 1)

    def _payment_event(
        self, kind: LedgerEventKind, payment_intent: PaymentIntent
    ) -> LedgerEvent:
        """Build one payment fact bound to the intent and its idempotency key."""
        return LedgerEvent(
            sequence=self._next_sequence(sequence_offset=0),
            kind=kind,
            payment_intent_id=payment_intent.intent_id,
            entitlement_id=None,
            idempotency_key=payment_intent.idempotency_key,
        )

    def _grant_event(
        self,
        payment_intent: PaymentIntent,
        entitlement: SubscriptionEntitlement,
        sequence_offset: int,
    ) -> LedgerEvent:
        """Build the entitlement fact that accompanies first payment confirmation."""
        return LedgerEvent(
            sequence=self._next_sequence(sequence_offset=sequence_offset),
            kind=LedgerEventKind.SUBSCRIPTION_GRANTED,
            payment_intent_id=payment_intent.intent_id,
            entitlement_id=entitlement.entitlement_id,
            idempotency_key=payment_intent.idempotency_key,
        )

    def _has_idempotency_key(self, idempotency_key: IdempotencyKey) -> bool:
        """Find prior key use without requiring mutable lookup state."""
        event: LedgerEvent
        for event in self.events:
            if event.idempotency_key == idempotency_key:
                return True
        return False

    def _has_payment_event(
        self, kind: LedgerEventKind, payment_intent_id: PaymentIntentId
    ) -> bool:
        """Check a specific payment fact in existing append-only events."""
        event: LedgerEvent
        for event in self.events:
            if event.kind is kind and event.payment_intent_id == payment_intent_id:
                return True
        return False

    def _has_entitlement_event(
        self, kind: LedgerEventKind, entitlement_id: EntitlementId
    ) -> bool:
        """Check a specific entitlement fact in existing append-only events."""
        event: LedgerEvent
        for event in self.events:
            if event.kind is kind and event.entitlement_id == entitlement_id:
                return True
        return False


def _require_payment_intent(payment_intent: PaymentIntent) -> None:
    if not isinstance(payment_intent, PaymentIntent):
        raise TypeError("payment_intent must be a PaymentIntent")


def _validate_event_references(event: LedgerEvent) -> None:
    payment_kinds: tuple[LedgerEventKind, ...] = (
        LedgerEventKind.PAYMENT_CONFIRMED,
        LedgerEventKind.PAYMENT_CANCELLED,
        LedgerEventKind.PAYMENT_REFUNDED,
    )
    if event.kind in payment_kinds:
        if event.payment_intent_id is None or event.idempotency_key is None:
            raise ValueError("payment events require intent and idempotency references")
        if event.entitlement_id is not None:
            raise ValueError("payment events cannot carry an entitlement reference")
        return
    if event.kind is LedgerEventKind.SUBSCRIPTION_GRANTED:
        if (
            event.payment_intent_id is None
            or event.entitlement_id is None
            or event.idempotency_key is None
        ):
            raise ValueError("subscription grants require payment and entitlement references")
        return
    if event.payment_intent_id is not None or event.idempotency_key is not None:
        raise ValueError("subscription expiry cannot carry payment references")
    if event.entitlement_id is None:
        raise ValueError("subscription expiry requires an entitlement reference")
