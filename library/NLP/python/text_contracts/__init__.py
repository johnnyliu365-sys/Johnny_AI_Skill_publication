"""Public API for reusable, strongly typed NLP text contracts."""

from typing import Final

from .contracts import (
    ExtractedTextField,
    FieldExtractionResult,
    MAX_NORMALIZED_TEXT_LENGTH,
    NormalizationAccepted,
    NormalizationRejected,
    NormalizationResult,
    NormalizedText,
    RejectionReason,
    TextClassificationResult,
    TextFieldName,
    TextInput,
    TextInputOrigin,
    TextLabel,
    normalize_text,
)

__all__: Final[tuple[str, ...]] = (
    "ExtractedTextField",
    "FieldExtractionResult",
    "MAX_NORMALIZED_TEXT_LENGTH",
    "NormalizationAccepted",
    "NormalizationRejected",
    "NormalizationResult",
    "NormalizedText",
    "RejectionReason",
    "TextClassificationResult",
    "TextFieldName",
    "TextInput",
    "TextInputOrigin",
    "TextLabel",
    "normalize_text",
)
