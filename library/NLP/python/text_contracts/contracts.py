"""Strongly typed, provider-free contracts for reusable NLP text boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final, TypeAlias
import unicodedata


MAX_NORMALIZED_TEXT_LENGTH: Final[int] = 2_000


class TextInputOrigin(str, Enum):
    """Trust state of text before it enters this library boundary."""

    LOCAL_VALIDATED = "local_validated"
    EXTERNAL_UNVALIDATED = "external_unvalidated"


class RejectionReason(str, Enum):
    """Explicit reasons for refusing text at the boundary."""

    BLANK = "blank"
    CONTROL_CHARACTER = "control_character"
    TOO_LONG = "too_long"
    UNVALIDATED_ORIGIN = "unvalidated_origin"


@dataclass(frozen=True, slots=True)
class TextInput:
    """Text and its verified trust origin before normalization."""

    raw_text: str
    origin: TextInputOrigin

    def __post_init__(self) -> None:
        if not isinstance(self.raw_text, str):
            raise TypeError("raw_text must be a str")
        if not isinstance(self.origin, TextInputOrigin):
            raise TypeError("origin must be a TextInputOrigin")


@dataclass(frozen=True, slots=True)
class NormalizedText:
    """A non-blank, control-free and canonically spaced text value."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TypeError("value must be a str")
        if not self.value:
            raise ValueError("normalized text cannot be blank")
        if _contains_control_character(self.value):
            raise ValueError("normalized text cannot contain control characters")
        if len(self.value) > MAX_NORMALIZED_TEXT_LENGTH:
            raise ValueError("normalized text exceeds the maximum length")
        if self.value != _normalize_whitespace(self.value):
            raise ValueError("normalized text must use canonical whitespace")


@dataclass(frozen=True, slots=True)
class TextLabel:
    """A validated provider-independent classification label."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TypeError("value must be a str")
        if not self.value or self.value != self.value.strip():
            raise ValueError("text label cannot be blank or padded")
        if _contains_control_character(self.value):
            raise ValueError("text label cannot contain control characters")


@dataclass(frozen=True, slots=True)
class TextFieldName:
    """A validated name for an extracted text field."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TypeError("value must be a str")
        if not self.value or self.value != self.value.strip():
            raise ValueError("field name cannot be blank or padded")
        if _contains_control_character(self.value):
            raise ValueError("field name cannot contain control characters")


@dataclass(frozen=True, slots=True)
class TextClassificationResult:
    """A provider-neutral classification bound to validated text."""

    label: TextLabel
    normalized_text: NormalizedText

    def __post_init__(self) -> None:
        if not isinstance(self.label, TextLabel):
            raise TypeError("label must be a TextLabel")
        if not isinstance(self.normalized_text, NormalizedText):
            raise TypeError("normalized_text must be a NormalizedText")


@dataclass(frozen=True, slots=True)
class ExtractedTextField:
    """One typed field obtained from validated text."""

    name: TextFieldName
    value: NormalizedText

    def __post_init__(self) -> None:
        if not isinstance(self.name, TextFieldName):
            raise TypeError("name must be a TextFieldName")
        if not isinstance(self.value, NormalizedText):
            raise TypeError("value must be a NormalizedText")


@dataclass(frozen=True, slots=True)
class FieldExtractionResult:
    """An immutable collection of named text fields for one input."""

    normalized_text: NormalizedText
    fields: tuple[ExtractedTextField, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.normalized_text, NormalizedText):
            raise TypeError("normalized_text must be a NormalizedText")
        if not isinstance(self.fields, tuple):
            raise TypeError("fields must be a tuple")
        extracted_field: ExtractedTextField
        for extracted_field in self.fields:
            if not isinstance(extracted_field, ExtractedTextField):
                raise TypeError("fields must contain ExtractedTextField values")

    @classmethod
    def empty(cls, normalized_text: NormalizedText) -> FieldExtractionResult:
        """Build an explicit no-fields result without a mutable dictionary."""
        no_fields: tuple[ExtractedTextField, ...] = ()
        return cls(normalized_text=normalized_text, fields=no_fields)


@dataclass(frozen=True, slots=True)
class NormalizationAccepted:
    """Successful normalization result."""

    normalized_text: NormalizedText

    def __post_init__(self) -> None:
        if not isinstance(self.normalized_text, NormalizedText):
            raise TypeError("normalized_text must be a NormalizedText")


@dataclass(frozen=True, slots=True)
class NormalizationRejected:
    """Fail-closed rejection result with no invented normalized text."""

    reason: RejectionReason

    def __post_init__(self) -> None:
        if not isinstance(self.reason, RejectionReason):
            raise TypeError("reason must be a RejectionReason")


NormalizationResult: TypeAlias = NormalizationAccepted | NormalizationRejected


def normalize_text(text_input: TextInput) -> NormalizationResult:
    """Validate and normalize local text, rejecting unsupported input explicitly."""
    if text_input.origin is not TextInputOrigin.LOCAL_VALIDATED:
        return NormalizationRejected(reason=RejectionReason.UNVALIDATED_ORIGIN)

    raw_text: str = text_input.raw_text
    if _contains_control_character(raw_text):
        return NormalizationRejected(reason=RejectionReason.CONTROL_CHARACTER)

    normalized_value: str = _normalize_whitespace(raw_text)
    if not normalized_value:
        return NormalizationRejected(reason=RejectionReason.BLANK)
    if len(normalized_value) > MAX_NORMALIZED_TEXT_LENGTH:
        return NormalizationRejected(reason=RejectionReason.TOO_LONG)

    accepted_text: NormalizedText = NormalizedText(value=normalized_value)
    return NormalizationAccepted(normalized_text=accepted_text)


def _contains_control_character(value: str) -> bool:
    character: str
    for character in value:
        category: str = unicodedata.category(character)
        if category.startswith("C"):
            return True
    return False


def _normalize_whitespace(value: str) -> str:
    unicode_normalized: str = unicodedata.normalize("NFKC", value)
    whitespace_collapsed: str = " ".join(unicode_normalized.split())
    return whitespace_collapsed
