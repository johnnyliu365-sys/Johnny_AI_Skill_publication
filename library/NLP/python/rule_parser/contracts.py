"""Strongly typed contracts for deterministic marked-field parsing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import unicodedata

from library.NLP.python.text_contracts import (
    ExtractedTextField,
    FieldExtractionResult,
    NormalizedText,
    TextFieldName,
)


class ParseStatus(str, Enum):
    """The complete state set for one deterministic parse attempt."""

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    AMBIGUOUS = "ambiguous"
    REJECTED = "rejected"


class ParseReason(str, Enum):
    """Machine-readable rationale retained with each parse result."""

    COMPLETE_FRAME = "complete_frame"
    MISSING_REQUIRED_FIELD = "missing_required_field"
    DUPLICATE_FIELD = "duplicate_field"
    MULTIPLE_COMPLETE_FRAMES = "multiple_complete_frames"
    SPLIT_ACROSS_FRAMES = "split_across_frames"
    EMPTY_FIELD_VALUE = "empty_field_value"
    NO_RECOGNIZED_FIELD = "no_recognized_field"


@dataclass(frozen=True, slots=True)
class RuleToken:
    """A fixed literal that must prefix one field segment."""

    value: str

    def __post_init__(self) -> None:
        _validate_rule_text(value=self.value, type_name="RuleToken")


@dataclass(frozen=True, slots=True)
class LiteralDelimiter:
    """A fixed literal used to separate fields or independent frames."""

    value: str

    def __post_init__(self) -> None:
        _validate_rule_text(value=self.value, type_name="LiteralDelimiter")


@dataclass(frozen=True, slots=True)
class FieldRule:
    """One named field and the deterministic token that introduces it."""

    field_name: TextFieldName
    token: RuleToken
    required: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.field_name, TextFieldName):
            raise TypeError("field_name must be a TextFieldName")
        if not isinstance(self.token, RuleToken):
            raise TypeError("token must be a RuleToken")
        if not isinstance(self.required, bool):
            raise TypeError("required must be a bool")


@dataclass(frozen=True, slots=True)
class RuleSet:
    """Complete fixed grammar for one independent parsing operation."""

    field_rules: tuple[FieldRule, ...]
    field_delimiter: LiteralDelimiter
    frame_delimiter: LiteralDelimiter

    def __post_init__(self) -> None:
        if not isinstance(self.field_rules, tuple) or not self.field_rules:
            raise ValueError("field_rules must be a non-empty tuple")
        if not isinstance(self.field_delimiter, LiteralDelimiter):
            raise TypeError("field_delimiter must be a LiteralDelimiter")
        if not isinstance(self.frame_delimiter, LiteralDelimiter):
            raise TypeError("frame_delimiter must be a LiteralDelimiter")
        if self.field_delimiter == self.frame_delimiter:
            raise ValueError("field and frame delimiters must differ")

        field_names: list[TextFieldName] = []
        rule_tokens: list[RuleToken] = []
        field_rule: FieldRule
        for field_rule in self.field_rules:
            if not isinstance(field_rule, FieldRule):
                raise TypeError("field_rules must contain FieldRule values")
            if field_rule.field_name in field_names:
                raise ValueError("field rule names must be unique")
            if field_rule.token in rule_tokens:
                raise ValueError("field rule tokens must be unique")
            if self.field_delimiter.value in field_rule.token.value:
                raise ValueError("field tokens cannot contain the field delimiter")
            if self.frame_delimiter.value in field_rule.token.value:
                raise ValueError("field tokens cannot contain the frame delimiter")
            field_names.append(field_rule.field_name)
            rule_tokens.append(field_rule.token)


@dataclass(frozen=True, slots=True)
class FramePosition:
    """A zero-based position of an independent frame in source text."""

    value: int

    def __post_init__(self) -> None:
        if not isinstance(self.value, int):
            raise TypeError("value must be an int")
        if self.value < 0:
            raise ValueError("frame position cannot be negative")


@dataclass(frozen=True, slots=True)
class ParseRationale:
    """Explicit evidence describing why a parser state was returned."""

    reason: ParseReason
    frame_positions: tuple[FramePosition, ...]
    observed_field_names: tuple[TextFieldName, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.reason, ParseReason):
            raise TypeError("reason must be a ParseReason")
        if not isinstance(self.frame_positions, tuple):
            raise TypeError("frame_positions must be a tuple")
        if not isinstance(self.observed_field_names, tuple):
            raise TypeError("observed_field_names must be a tuple")

        frame_position: FramePosition
        for frame_position in self.frame_positions:
            if not isinstance(frame_position, FramePosition):
                raise TypeError("frame_positions must contain FramePosition values")

        field_name: TextFieldName
        for field_name in self.observed_field_names:
            if not isinstance(field_name, TextFieldName):
                raise TypeError("observed_field_names must contain TextFieldName values")


@dataclass(frozen=True, slots=True)
class RuleParseResult:
    """A typed parser state, rationale and optional actual field extraction."""

    status: ParseStatus
    rationale: ParseRationale
    extraction: FieldExtractionResult | None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ParseStatus):
            raise TypeError("status must be a ParseStatus")
        if not isinstance(self.rationale, ParseRationale):
            raise TypeError("rationale must be a ParseRationale")
        if self.extraction is not None and not isinstance(
            self.extraction, FieldExtractionResult
        ):
            raise TypeError("extraction must be a FieldExtractionResult or None")
        if self.status is ParseStatus.COMPLETE:
            if self.rationale.reason is not ParseReason.COMPLETE_FRAME:
                raise ValueError("complete results require a complete-frame rationale")
            if self.extraction is None:
                raise ValueError("complete results require an extraction")
        if self.status is ParseStatus.AMBIGUOUS and self.extraction is not None:
            raise ValueError("ambiguous results cannot select one extraction")
        if self.status is ParseStatus.REJECTED and self.extraction is not None:
            raise ValueError("rejected results cannot contain extracted fields")


@dataclass(frozen=True, slots=True)
class _FrameScan:
    """Private scan evidence for exactly one frame."""

    position: FramePosition
    fields: tuple[ExtractedTextField, ...]
    duplicate_field_names: tuple[TextFieldName, ...]
    has_empty_field_value: bool


def _validate_rule_text(value: str, type_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{type_name} value must be a str")
    if not value or value != value.strip():
        raise ValueError(f"{type_name} value cannot be blank or padded")
    character: str
    for character in value:
        category: str = unicodedata.category(character)
        if category.startswith("C"):
            raise ValueError(f"{type_name} value cannot contain control characters")
