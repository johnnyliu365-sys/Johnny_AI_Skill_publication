"""Strongly typed contracts for provider-free NLP analysis boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, TypeAlias
import unicodedata

from library.NLP.python.text_contracts import (
    NormalizedText,
    TextClassificationResult,
    TextLabel,
)


class ProviderFailureKind(str, Enum):
    """Named failure classes that callers may safely handle."""

    TRANSIENT = "transient"
    PERMANENT = "permanent"
    TIMEOUT = "timeout"
    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    INVALID_STRUCTURE = "invalid_structure"


class ProviderRetryability(str, Enum):
    """Whether a classified failure may be retried by a caller."""

    RETRYABLE = "retryable"
    NOT_RETRYABLE = "not_retryable"


@dataclass(frozen=True, slots=True)
class ProviderRequestId:
    """A safe, caller-supplied identifier for one provider request."""

    value: str

    def __post_init__(self) -> None:
        _validate_identifier(value=self.value, type_name="ProviderRequestId")


@dataclass(frozen=True, slots=True)
class ConfidenceBasisPoints:
    """An integral confidence in the inclusive range from 0 to 10,000."""

    value: int

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, int):
            raise TypeError("confidence value must be an int")
        if self.value < 0 or self.value > 10_000:
            raise ValueError("confidence value must be within 0 and 10000")


@dataclass(frozen=True, slots=True)
class TextAnalysisRequest:
    """A closed request contract for a provider to classify validated text."""

    request_id: ProviderRequestId
    input_text: NormalizedText
    allowed_labels: tuple[TextLabel, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, ProviderRequestId):
            raise TypeError("request_id must be a ProviderRequestId")
        if not isinstance(self.input_text, NormalizedText):
            raise TypeError("input_text must be a NormalizedText")
        if not isinstance(self.allowed_labels, tuple) or not self.allowed_labels:
            raise ValueError("allowed_labels must be a non-empty tuple")

        seen_labels: list[TextLabel] = []
        label: TextLabel
        for label in self.allowed_labels:
            if not isinstance(label, TextLabel):
                raise TypeError("allowed_labels must contain TextLabel values")
            if label in seen_labels:
                raise ValueError("allowed_labels must be unique")
            seen_labels.append(label)


@dataclass(frozen=True, slots=True)
class ValidatedModelOutput:
    """A provider answer that has passed structure and request validation."""

    classification: TextClassificationResult
    confidence: ConfidenceBasisPoints

    def __post_init__(self) -> None:
        if not isinstance(self.classification, TextClassificationResult):
            raise TypeError("classification must be a TextClassificationResult")
        if not isinstance(self.confidence, ConfidenceBasisPoints):
            raise TypeError("confidence must be a ConfidenceBasisPoints")


@dataclass(frozen=True, slots=True)
class ProviderSuccess:
    """A successful call containing only validated model output."""

    request_id: ProviderRequestId
    output: ValidatedModelOutput

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, ProviderRequestId):
            raise TypeError("request_id must be a ProviderRequestId")
        if not isinstance(self.output, ValidatedModelOutput):
            raise TypeError("output must be a ValidatedModelOutput")


@dataclass(frozen=True, slots=True)
class ProviderFailure:
    """A safe failure with retry behaviour derived from its named kind."""

    request_id: ProviderRequestId
    kind: ProviderFailureKind
    retryability: ProviderRetryability

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, ProviderRequestId):
            raise TypeError("request_id must be a ProviderRequestId")
        if not isinstance(self.kind, ProviderFailureKind):
            raise TypeError("kind must be a ProviderFailureKind")
        if not isinstance(self.retryability, ProviderRetryability):
            raise TypeError("retryability must be a ProviderRetryability")
        expected_retryability: ProviderRetryability = retryability_for(self.kind)
        if self.retryability is not expected_retryability:
            raise ValueError("retryability must match the failure kind")


ProviderCallResult: TypeAlias = ProviderSuccess | ProviderFailure


class AnalysisProviderPort(Protocol):
    """Provider port that exposes only typed results to calling code."""

    def analyze(self, request: TextAnalysisRequest) -> ProviderCallResult:
        """Analyze a validated request without leaking transport payloads."""


def retryability_for(kind: ProviderFailureKind) -> ProviderRetryability:
    """Classify retry safety from a finite, provider-independent failure kind."""
    if not isinstance(kind, ProviderFailureKind):
        raise TypeError("kind must be a ProviderFailureKind")
    if kind in (
        ProviderFailureKind.TRANSIENT,
        ProviderFailureKind.TIMEOUT,
        ProviderFailureKind.RATE_LIMIT,
    ):
        return ProviderRetryability.RETRYABLE
    return ProviderRetryability.NOT_RETRYABLE


def failure_for(
    request_id: ProviderRequestId, kind: ProviderFailureKind
) -> ProviderFailure:
    """Build a consistently classified failure without retaining raw provider data."""
    if not isinstance(request_id, ProviderRequestId):
        raise TypeError("request_id must be a ProviderRequestId")
    return ProviderFailure(
        request_id=request_id,
        kind=kind,
        retryability=retryability_for(kind),
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
