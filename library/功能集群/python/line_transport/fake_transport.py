"""Deterministic fake transport with no external delivery capability."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .contracts import (
    OutboundMessageRequest,
    TransportFailure,
    TransportFailureKind,
    TransportResult,
    TransportSuccess,
)


class FakeTransportScenario(str, Enum):
    """The finite outcomes supported by the local fake transport."""

    SUCCESS = "success"
    PROVIDER_FAILURE = "provider_failure"


@dataclass(slots=True)
class FakeLineTransport:
    """Record local attempts and return configured outcomes without network I/O."""

    scenario: FakeTransportScenario
    delivery_attempt_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.scenario, FakeTransportScenario):
            raise TypeError("scenario must be a FakeTransportScenario")
        if not isinstance(self.delivery_attempt_count, int) or isinstance(
            self.delivery_attempt_count, bool
        ):
            raise TypeError("delivery_attempt_count must be an integer")
        if self.delivery_attempt_count < 0:
            raise ValueError("delivery_attempt_count must not be negative")

    def send(self, request: OutboundMessageRequest) -> TransportResult:
        """Record one fake send attempt and return a fully redacted result."""
        if not isinstance(request, OutboundMessageRequest):
            raise TypeError("request must be an OutboundMessageRequest")
        self.delivery_attempt_count += 1
        if self.scenario is FakeTransportScenario.SUCCESS:
            return TransportSuccess(request_id=request.request_id)
        return TransportFailure(
            request_id=request.request_id,
            kind=TransportFailureKind.PROVIDER_UNAVAILABLE,
        )
