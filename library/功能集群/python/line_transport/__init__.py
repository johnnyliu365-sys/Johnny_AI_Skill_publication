"""Public local-only message transport contracts and fake adapter."""

from .contracts import (
    MessageContent,
    MessageRequestId,
    MessageScopeId,
    MessageTransport,
    OutboundMessageRequest,
    TransportFailure,
    TransportFailureKind,
    TransportResult,
    TransportSuccess,
)
from .fake_transport import FakeLineTransport, FakeTransportScenario

__all__ = [
    "FakeLineTransport",
    "FakeTransportScenario",
    "MessageContent",
    "MessageRequestId",
    "MessageScopeId",
    "MessageTransport",
    "OutboundMessageRequest",
    "TransportFailure",
    "TransportFailureKind",
    "TransportResult",
    "TransportSuccess",
]
