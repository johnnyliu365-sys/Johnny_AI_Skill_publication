"""Strongly typed, provider-free outbound message transport contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, TypeAlias

from library.功能集群.python.identity_resolution import StableIdentityId


@dataclass(frozen=True, slots=True)
class MessageRequestId:
    """A caller-supplied local identifier for one outbound message request."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value.strip():
            raise ValueError("message request identifier must be a non-blank string")


@dataclass(frozen=True, slots=True)
class MessageScopeId:
    """An explicit local scope used to keep message work separated."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value.strip():
            raise ValueError("message scope identifier must be a non-blank string")


@dataclass(frozen=True, slots=True)
class MessageContent:
    """A short, non-secret local message body for fake transport tests."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value.strip():
            raise ValueError("message content must be a non-blank string")
        if len(self.value) > 1_000:
            raise ValueError("message content must not exceed 1000 characters")


@dataclass(frozen=True, slots=True)
class OutboundMessageRequest:
    """An explicit scoped request with no credentials or authorization fields."""

    request_id: MessageRequestId
    scope_id: MessageScopeId
    recipient_identity: StableIdentityId
    content: MessageContent

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, MessageRequestId):
            raise TypeError("request_id must be a MessageRequestId")
        if not isinstance(self.scope_id, MessageScopeId):
            raise TypeError("scope_id must be a MessageScopeId")
        if not isinstance(self.recipient_identity, StableIdentityId):
            raise TypeError("recipient_identity must be a StableIdentityId")
        if not isinstance(self.content, MessageContent):
            raise TypeError("content must be a MessageContent")


class TransportFailureKind(str, Enum):
    """Safe categories that expose no provider exception or response content."""

    PROVIDER_UNAVAILABLE = "provider_unavailable"
    RECIPIENT_REJECTED = "recipient_rejected"


@dataclass(frozen=True, slots=True)
class TransportSuccess:
    """A fake transport accepted one local request."""

    request_id: MessageRequestId

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, MessageRequestId):
            raise TypeError("request_id must be a MessageRequestId")


@dataclass(frozen=True, slots=True)
class TransportFailure:
    """A redacted fake transport failure with only a finite safe category."""

    request_id: MessageRequestId
    kind: TransportFailureKind

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, MessageRequestId):
            raise TypeError("request_id must be a MessageRequestId")
        if not isinstance(self.kind, TransportFailureKind):
            raise TypeError("kind must be a TransportFailureKind")


TransportResult: TypeAlias = TransportSuccess | TransportFailure


class MessageTransport(Protocol):
    """A provider-free boundary that accepts only explicit local requests."""

    def send(self, request: OutboundMessageRequest) -> TransportResult:
        """Return a typed result without exposing provider transport details."""
