"""Public API for deterministic, strongly typed NLP field parsing."""

from typing import Final

from .contracts import (
    FieldRule,
    FramePosition,
    LiteralDelimiter,
    ParseRationale,
    ParseReason,
    ParseStatus,
    RuleParseResult,
    RuleSet,
    RuleToken,
)
from .parser import parse_fields

__all__: Final[tuple[str, ...]] = (
    "FieldRule",
    "FramePosition",
    "LiteralDelimiter",
    "ParseRationale",
    "ParseReason",
    "ParseStatus",
    "RuleParseResult",
    "RuleSet",
    "RuleToken",
    "parse_fields",
)
