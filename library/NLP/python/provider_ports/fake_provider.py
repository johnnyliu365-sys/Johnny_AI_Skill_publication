"""Provider-free fake implementation for deterministic local testing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from library.NLP.python.text_contracts import TextClassificationResult, TextLabel

from .contracts import (
    AnalysisProviderPort,
    ConfidenceBasisPoints,
    ProviderCallResult,
    ProviderFailureKind,
    ProviderSuccess,
    TextAnalysisRequest,
    ValidatedModelOutput,
    failure_for,
)


class FakeProviderScenario(str, Enum):
    """Finite local outcomes used to exercise provider callers safely."""

    SUCCESS = "success"
    TRANSIENT_FAILURE = "transient_failure"
    PERMANENT_FAILURE = "permanent_failure"
    TIMEOUT = "timeout"
    AUTH_FAILURE = "auth_failure"
    RATE_LIMIT = "rate_limit"


@dataclass(frozen=True, slots=True)
class FakeAnalysisProvider(AnalysisProviderPort):
    """A deterministic provider port with no network, secrets or raw payloads."""

    scenario: FakeProviderScenario
    success_label: TextLabel | None = None
    success_confidence: ConfidenceBasisPoints | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.scenario, FakeProviderScenario):
            raise TypeError("scenario must be a FakeProviderScenario")
        if self.success_label is not None and not isinstance(self.success_label, TextLabel):
            raise TypeError("success_label must be a TextLabel or None")
        if self.success_confidence is not None and not isinstance(
            self.success_confidence, ConfidenceBasisPoints
        ):
            raise TypeError(
                "success_confidence must be a ConfidenceBasisPoints or None"
            )

    def analyze(self, request: TextAnalysisRequest) -> ProviderCallResult:
        """Return a typed fixture outcome for one validated request."""
        if not isinstance(request, TextAnalysisRequest):
            raise TypeError("request must be a TextAnalysisRequest")
        if self.scenario is FakeProviderScenario.SUCCESS:
            return self._success_result(request)
        if self.scenario is FakeProviderScenario.TRANSIENT_FAILURE:
            return failure_for(request.request_id, ProviderFailureKind.TRANSIENT)
        if self.scenario is FakeProviderScenario.PERMANENT_FAILURE:
            return failure_for(request.request_id, ProviderFailureKind.PERMANENT)
        if self.scenario is FakeProviderScenario.TIMEOUT:
            return failure_for(request.request_id, ProviderFailureKind.TIMEOUT)
        if self.scenario is FakeProviderScenario.AUTH_FAILURE:
            return failure_for(request.request_id, ProviderFailureKind.AUTHENTICATION)
        return failure_for(request.request_id, ProviderFailureKind.RATE_LIMIT)

    def _success_result(self, request: TextAnalysisRequest) -> ProviderCallResult:
        """Build success only when the configured fake output is request-valid."""
        if self.success_label is None or self.success_confidence is None:
            return failure_for(request.request_id, ProviderFailureKind.INVALID_STRUCTURE)
        if self.success_label not in request.allowed_labels:
            return failure_for(request.request_id, ProviderFailureKind.INVALID_STRUCTURE)

        classification: TextClassificationResult = TextClassificationResult(
            label=self.success_label,
            normalized_text=request.input_text,
        )
        output: ValidatedModelOutput = ValidatedModelOutput(
            classification=classification,
            confidence=self.success_confidence,
        )
        return ProviderSuccess(request_id=request.request_id, output=output)
