"""Adapter-only validation of raw provider payloads into typed results."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, TypeGuard

from library.NLP.python.text_contracts import TextClassificationResult, TextLabel

from .contracts import (
    ConfidenceBasisPoints,
    ProviderCallResult,
    ProviderFailureKind,
    ProviderSuccess,
    TextAnalysisRequest,
    ValidatedModelOutput,
    failure_for,
)


_EXPECTED_PAYLOAD_KEYS: Final[frozenset[str]] = frozenset(
    ("label", "confidence_basis_points")
)


class ProviderPayloadValidator:
    """The only public boundary that may receive unvalidated provider payloads."""

    def validate(
        self, raw_payload: object, request: TextAnalysisRequest
    ) -> ProviderCallResult:
        """Fail closed unless a raw payload exactly matches the request schema."""
        if not isinstance(request, TextAnalysisRequest):
            raise TypeError("request must be a TextAnalysisRequest")
        if not _is_string_keyed_payload(raw_payload):
            return failure_for(
                request_id=request.request_id,
                kind=ProviderFailureKind.INVALID_STRUCTURE,
            )

        payload_keys: frozenset[str] = frozenset(raw_payload.keys())
        if payload_keys != _EXPECTED_PAYLOAD_KEYS:
            return failure_for(
                request_id=request.request_id,
                kind=ProviderFailureKind.INVALID_STRUCTURE,
            )

        raw_label: object = raw_payload["label"]
        raw_confidence: object = raw_payload["confidence_basis_points"]
        if not isinstance(raw_label, str):
            return failure_for(
                request_id=request.request_id,
                kind=ProviderFailureKind.INVALID_STRUCTURE,
            )
        if isinstance(raw_confidence, bool) or not isinstance(raw_confidence, int):
            return failure_for(
                request_id=request.request_id,
                kind=ProviderFailureKind.INVALID_STRUCTURE,
            )

        try:
            label: TextLabel = TextLabel(value=raw_label)
            confidence: ConfidenceBasisPoints = ConfidenceBasisPoints(value=raw_confidence)
        except (TypeError, ValueError):
            return failure_for(
                request_id=request.request_id,
                kind=ProviderFailureKind.INVALID_STRUCTURE,
            )
        if label not in request.allowed_labels:
            return failure_for(
                request_id=request.request_id,
                kind=ProviderFailureKind.INVALID_STRUCTURE,
            )

        classification: TextClassificationResult = TextClassificationResult(
            label=label,
            normalized_text=request.input_text,
        )
        output: ValidatedModelOutput = ValidatedModelOutput(
            classification=classification,
            confidence=confidence,
        )
        return ProviderSuccess(request_id=request.request_id, output=output)


def _is_string_keyed_payload(value: object) -> TypeGuard[Mapping[str, object]]:
    """Narrow unknown adapter input before it can reach typed contract code."""
    if not isinstance(value, Mapping):
        return False
    key: object
    for key in value:
        if not isinstance(key, str):
            return False
    return True
