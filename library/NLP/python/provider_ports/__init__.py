"""Public API for local, strongly typed NLP provider boundaries."""

from typing import Final

from .contracts import (
    AnalysisProviderPort,
    ConfidenceBasisPoints,
    ProviderCallResult,
    ProviderFailure,
    ProviderFailureKind,
    ProviderRequestId,
    ProviderRetryability,
    ProviderSuccess,
    TextAnalysisRequest,
    ValidatedModelOutput,
    failure_for,
    retryability_for,
)
from .fake_provider import FakeAnalysisProvider, FakeProviderScenario
from .validator import ProviderPayloadValidator

__all__: Final[tuple[str, ...]] = (
    "AnalysisProviderPort",
    "ConfidenceBasisPoints",
    "FakeAnalysisProvider",
    "FakeProviderScenario",
    "ProviderCallResult",
    "ProviderFailure",
    "ProviderFailureKind",
    "ProviderPayloadValidator",
    "ProviderRequestId",
    "ProviderRetryability",
    "ProviderSuccess",
    "TextAnalysisRequest",
    "ValidatedModelOutput",
    "failure_for",
    "retryability_for",
)
