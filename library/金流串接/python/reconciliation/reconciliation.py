"""Pure, replay-safe reconciliation of typed fake payment provider results."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from library.金流串接.python.payment_contracts import (
    IdempotencyKey,
    PaymentIntent,
    PaymentIntentId,
)
from library.金流串接.python.provider_ports import (
    ProviderEvent,
    ProviderEventId,
    ProviderEventResult,
    ProviderEventSuccess,
    ProviderFailure,
    ProviderFailureKind,
    ProviderFinalState,
    ProviderTransactionId,
)
from library.金流串接.python.subscription_ledger import (
    LedgerAccepted,
    LedgerRejected,
    SubscriptionEntitlement,
    SubscriptionLedger,
)


class ReconciliationManualReviewReason(str, Enum):
    """Finite reasons that must stop automatic reconciliation."""

    PROVIDER_TIMEOUT = "provider_timeout"
    UNKNOWN_TRANSACTION = "unknown_transaction"
    CONFLICTING_FINAL_STATE = "conflicting_final_state"
    OWNERSHIP_MISMATCH = "ownership_mismatch"
    LEDGER_REJECTED = "ledger_rejected"


@dataclass(frozen=True, slots=True)
class ReconciliationRecord:
    """One provider event already applied to a local ledger snapshot."""

    event_id: ProviderEventId
    transaction_id: ProviderTransactionId
    payment_intent_id: PaymentIntentId
    final_state: ProviderFinalState

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, ProviderEventId):
            raise TypeError("event_id must be a ProviderEventId")
        if not isinstance(self.transaction_id, ProviderTransactionId):
            raise TypeError("transaction_id must be a ProviderTransactionId")
        if not isinstance(self.payment_intent_id, PaymentIntentId):
            raise TypeError("payment_intent_id must be a PaymentIntentId")
        if not isinstance(self.final_state, ProviderFinalState):
            raise TypeError("final_state must be a ProviderFinalState")


@dataclass(frozen=True, slots=True)
class ReconciliationJournal:
    """Immutable record of applied provider events used for replay detection."""

    records: tuple[ReconciliationRecord, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.records, tuple):
            raise TypeError("records must be a tuple")
        seen_event_ids: list[ProviderEventId] = []
        record: ReconciliationRecord
        for record in self.records:
            if not isinstance(record, ReconciliationRecord):
                raise TypeError("records must contain ReconciliationRecord values")
            if record.event_id in seen_event_ids:
                raise ValueError("reconciliation event identifiers must be unique")
            seen_event_ids.append(record.event_id)

    @classmethod
    def empty(cls) -> ReconciliationJournal:
        """Create a journal with no provider event processing history."""
        no_records: tuple[ReconciliationRecord, ...] = ()
        return cls(records=no_records)

    def has_event_id(self, event_id: ProviderEventId) -> bool:
        """Check whether an exact provider event has already been applied."""
        if not isinstance(event_id, ProviderEventId):
            raise TypeError("event_id must be a ProviderEventId")
        record: ReconciliationRecord
        for record in self.records:
            if record.event_id == event_id:
                return True
        return False

    def latest_final_state(
        self, transaction_id: ProviderTransactionId
    ) -> ProviderFinalState | None:
        """Return the most recently applied final state for one transaction."""
        if not isinstance(transaction_id, ProviderTransactionId):
            raise TypeError("transaction_id must be a ProviderTransactionId")
        record: ReconciliationRecord
        for record in reversed(self.records):
            if record.transaction_id == transaction_id:
                return record.final_state
        return None

    def appended(self, provider_event: ProviderEvent) -> ReconciliationJournal:
        """Return a new journal that records an applied provider event once."""
        if not isinstance(provider_event, ProviderEvent):
            raise TypeError("provider_event must be a ProviderEvent")
        if self.has_event_id(provider_event.event_id):
            raise ValueError("provider event is already recorded")
        record: ReconciliationRecord = ReconciliationRecord(
            event_id=provider_event.event_id,
            transaction_id=provider_event.transaction_id,
            payment_intent_id=provider_event.payment_intent_id,
            final_state=provider_event.final_state,
        )
        return ReconciliationJournal(records=self.records + (record,))


@dataclass(frozen=True, slots=True)
class ReconciliationApplied:
    """A provider event was validated and produced a new journal and ledger."""

    journal: ReconciliationJournal
    ledger: SubscriptionLedger
    payment_intent: PaymentIntent
    entitlement: SubscriptionEntitlement | None

    def __post_init__(self) -> None:
        if not isinstance(self.journal, ReconciliationJournal):
            raise TypeError("journal must be a ReconciliationJournal")
        if not isinstance(self.ledger, SubscriptionLedger):
            raise TypeError("ledger must be a SubscriptionLedger")
        if not isinstance(self.payment_intent, PaymentIntent):
            raise TypeError("payment_intent must be a PaymentIntent")
        if self.entitlement is not None and not isinstance(
            self.entitlement, SubscriptionEntitlement
        ):
            raise TypeError("entitlement must be a SubscriptionEntitlement or None")


@dataclass(frozen=True, slots=True)
class ReconciliationAlreadyProcessed:
    """A replayed event that leaves journal and ledger unchanged."""

    journal: ReconciliationJournal
    ledger: SubscriptionLedger

    def __post_init__(self) -> None:
        if not isinstance(self.journal, ReconciliationJournal):
            raise TypeError("journal must be a ReconciliationJournal")
        if not isinstance(self.ledger, SubscriptionLedger):
            raise TypeError("ledger must be a SubscriptionLedger")


@dataclass(frozen=True, slots=True)
class ReconciliationManualReview:
    """A fail-closed result that requires an authorized human decision."""

    journal: ReconciliationJournal
    ledger: SubscriptionLedger
    reason: ReconciliationManualReviewReason

    def __post_init__(self) -> None:
        if not isinstance(self.journal, ReconciliationJournal):
            raise TypeError("journal must be a ReconciliationJournal")
        if not isinstance(self.ledger, SubscriptionLedger):
            raise TypeError("ledger must be a SubscriptionLedger")
        if not isinstance(self.reason, ReconciliationManualReviewReason):
            raise TypeError("reason must be a ReconciliationManualReviewReason")


ReconciliationResult: TypeAlias = (
    ReconciliationApplied | ReconciliationAlreadyProcessed | ReconciliationManualReview
)


def reconcile_provider_event(
    provider_result: ProviderEventResult,
    payment_intent: PaymentIntent,
    ledger: SubscriptionLedger,
    journal: ReconciliationJournal,
) -> ReconciliationResult:
    """Apply one typed result once, or return a fail-closed review outcome."""
    if not isinstance(payment_intent, PaymentIntent):
        raise TypeError("payment_intent must be a PaymentIntent")
    if not isinstance(ledger, SubscriptionLedger):
        raise TypeError("ledger must be a SubscriptionLedger")
    if not isinstance(journal, ReconciliationJournal):
        raise TypeError("journal must be a ReconciliationJournal")
    if isinstance(provider_result, ProviderFailure):
        return ReconciliationManualReview(
            journal=journal,
            ledger=ledger,
            reason=_review_reason_for_failure(provider_result.kind),
        )
    if not isinstance(provider_result, ProviderEventSuccess):
        raise TypeError("provider_result must be a ProviderEventSuccess or ProviderFailure")

    provider_event: ProviderEvent = provider_result.event
    if not _matches_payment_intent(provider_event, payment_intent):
        return ReconciliationManualReview(
            journal=journal,
            ledger=ledger,
            reason=ReconciliationManualReviewReason.OWNERSHIP_MISMATCH,
        )
    if journal.has_event_id(provider_event.event_id):
        return ReconciliationAlreadyProcessed(journal=journal, ledger=ledger)

    prior_state: ProviderFinalState | None = journal.latest_final_state(
        provider_event.transaction_id
    )
    if _is_conflicting_final_state(prior_state, provider_event.final_state):
        return ReconciliationManualReview(
            journal=journal,
            ledger=ledger,
            reason=ReconciliationManualReviewReason.CONFLICTING_FINAL_STATE,
        )
    if prior_state is provider_event.final_state:
        return ReconciliationAlreadyProcessed(journal=journal, ledger=ledger)

    if provider_event.final_state is ProviderFinalState.CONFIRMED:
        ledger_result = ledger.confirm_payment(payment_intent)
    else:
        ledger_result = ledger.refund_payment(payment_intent)
    if isinstance(ledger_result, LedgerRejected):
        return ReconciliationManualReview(
            journal=journal,
            ledger=ledger,
            reason=ReconciliationManualReviewReason.LEDGER_REJECTED,
        )
    if not isinstance(ledger_result, LedgerAccepted):
        raise RuntimeError("ledger returned an unsupported reconciliation result")

    next_journal: ReconciliationJournal = journal.appended(provider_event)
    return ReconciliationApplied(
        journal=next_journal,
        ledger=ledger_result.ledger,
        payment_intent=_required_payment_intent(ledger_result.payment_intent),
        entitlement=ledger_result.entitlement,
    )


def _matches_payment_intent(
    provider_event: ProviderEvent, payment_intent: PaymentIntent
) -> bool:
    """Require provider event ownership to match the local payment intent exactly."""
    return (
        provider_event.payment_intent_id == payment_intent.intent_id
        and provider_event.idempotency_key == payment_intent.idempotency_key
    )


def _is_conflicting_final_state(
    prior_state: ProviderFinalState | None, next_state: ProviderFinalState
) -> bool:
    """Allow confirmation then refund, but never regress a refunded transaction."""
    if prior_state is None:
        return False
    return (
        prior_state is ProviderFinalState.REFUNDED
        and next_state is ProviderFinalState.CONFIRMED
    )


def _review_reason_for_failure(
    failure_kind: ProviderFailureKind,
) -> ReconciliationManualReviewReason:
    """Map each provider failure to a non-guessing manual-review reason."""
    if failure_kind is ProviderFailureKind.TIMEOUT:
        return ReconciliationManualReviewReason.PROVIDER_TIMEOUT
    if failure_kind is ProviderFailureKind.UNKNOWN_TRANSACTION:
        return ReconciliationManualReviewReason.UNKNOWN_TRANSACTION
    return ReconciliationManualReviewReason.CONFLICTING_FINAL_STATE


def _required_payment_intent(payment_intent: PaymentIntent | None) -> PaymentIntent:
    """Assert accepted confirmation or refund always returns a next payment intent."""
    if payment_intent is None:
        raise RuntimeError("accepted payment ledger result must include a payment intent")
    return payment_intent
