"""Public API for local, strongly typed fake payment provider boundaries."""

from typing import Final

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
from .fake_provider import FakePaymentProvider, FakeProviderScenario

__all__: Final[tuple[str, ...]] = (
    "FakePaymentProvider",
    "FakeProviderScenario",
    "PaymentProviderPort",
    "ProviderAuthorization",
    "ProviderAuthorizationResult",
    "ProviderAuthorizationSuccess",
    "ProviderEvent",
    "ProviderEventId",
    "ProviderEventResult",
    "ProviderEventSuccess",
    "ProviderFailure",
    "ProviderFailureKind",
    "ProviderFinalState",
    "ProviderTransactionId",
)
