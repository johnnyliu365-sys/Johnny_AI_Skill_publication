"""Pure deterministic parsing for one-frame marked-field grammars."""

from __future__ import annotations

from library.NLP.python.text_contracts import (
    ExtractedTextField,
    FieldExtractionResult,
    NormalizedText,
    TextFieldName,
)

from .contracts import (
    FieldRule,
    FramePosition,
    ParseRationale,
    ParseReason,
    ParseStatus,
    RuleParseResult,
    RuleSet,
    _FrameScan,
)


def parse_fields(
    normalized_text: NormalizedText, rule_set: RuleSet
) -> RuleParseResult:
    """Extract actual marked values without merging evidence across frames."""
    if not isinstance(normalized_text, NormalizedText):
        raise TypeError("normalized_text must be a NormalizedText")
    if not isinstance(rule_set, RuleSet):
        raise TypeError("rule_set must be a RuleSet")

    source_frames: tuple[str, ...] = tuple(
        normalized_text.value.split(rule_set.frame_delimiter.value)
    )
    frame_scans: list[_FrameScan] = []
    frame_index: int
    frame_text: str
    for frame_index, frame_text in enumerate(source_frames):
        frame_position: FramePosition = FramePosition(value=frame_index)
        frame_scan: _FrameScan = _scan_frame(
            frame_text=frame_text,
            frame_position=frame_position,
            rule_set=rule_set,
        )
        frame_scans.append(frame_scan)
    scans: tuple[_FrameScan, ...] = tuple(frame_scans)

    duplicate_scans: tuple[_FrameScan, ...] = tuple(
        scan for scan in scans if scan.duplicate_field_names
    )
    if duplicate_scans:
        duplicate_scan: _FrameScan = duplicate_scans[0]
        return RuleParseResult(
            status=ParseStatus.AMBIGUOUS,
            rationale=ParseRationale(
                reason=ParseReason.DUPLICATE_FIELD,
                frame_positions=(duplicate_scan.position,),
                observed_field_names=duplicate_scan.duplicate_field_names,
            ),
            extraction=None,
        )

    complete_scans: tuple[_FrameScan, ...] = tuple(
        scan for scan in scans if _has_all_required_fields(scan=scan, rule_set=rule_set)
    )
    if len(complete_scans) == 1:
        complete_scan: _FrameScan = complete_scans[0]
        return RuleParseResult(
            status=ParseStatus.COMPLETE,
            rationale=ParseRationale(
                reason=ParseReason.COMPLETE_FRAME,
                frame_positions=(complete_scan.position,),
                observed_field_names=_field_names(complete_scan.fields),
            ),
            extraction=_extraction(
                normalized_text=normalized_text,
                fields=complete_scan.fields,
            ),
        )
    if len(complete_scans) > 1:
        return RuleParseResult(
            status=ParseStatus.AMBIGUOUS,
            rationale=ParseRationale(
                reason=ParseReason.MULTIPLE_COMPLETE_FRAMES,
                frame_positions=tuple(scan.position for scan in complete_scans),
                observed_field_names=_observed_field_names(scans),
            ),
            extraction=None,
        )

    if not _has_recognized_field(scans):
        return RuleParseResult(
            status=ParseStatus.REJECTED,
            rationale=ParseRationale(
                reason=ParseReason.NO_RECOGNIZED_FIELD,
                frame_positions=(),
                observed_field_names=(),
            ),
            extraction=None,
        )

    empty_value_scans: tuple[_FrameScan, ...] = tuple(
        scan for scan in scans if scan.has_empty_field_value
    )
    if empty_value_scans:
        return RuleParseResult(
            status=ParseStatus.REJECTED,
            rationale=ParseRationale(
                reason=ParseReason.EMPTY_FIELD_VALUE,
                frame_positions=tuple(scan.position for scan in empty_value_scans),
                observed_field_names=_observed_field_names(empty_value_scans),
            ),
            extraction=None,
        )

    if _required_fields_are_split_across_frames(scans=scans, rule_set=rule_set):
        return RuleParseResult(
            status=ParseStatus.INCOMPLETE,
            rationale=ParseRationale(
                reason=ParseReason.SPLIT_ACROSS_FRAMES,
                frame_positions=_positions_with_fields(scans),
                observed_field_names=_observed_field_names(scans),
            ),
            extraction=None,
        )

    partial_scan: _FrameScan | None = _most_complete_partial_scan(scans)
    if partial_scan is None:
        raise RuntimeError("recognized fields must produce a partial scan")
    return RuleParseResult(
        status=ParseStatus.INCOMPLETE,
        rationale=ParseRationale(
            reason=ParseReason.MISSING_REQUIRED_FIELD,
            frame_positions=(partial_scan.position,),
            observed_field_names=_field_names(partial_scan.fields),
        ),
        extraction=_extraction(normalized_text=normalized_text, fields=partial_scan.fields),
    )


def _scan_frame(
    frame_text: str, frame_position: FramePosition, rule_set: RuleSet
) -> _FrameScan:
    """Read one frame only, retaining duplicates rather than choosing a value."""
    segments: tuple[str, ...] = tuple(frame_text.split(rule_set.field_delimiter.value))
    extracted_fields: list[ExtractedTextField] = []
    duplicate_field_names: list[TextFieldName] = []
    seen_field_names: list[TextFieldName] = []
    has_empty_field_value: bool = False
    segment: str
    for segment in segments:
        matched_rule: FieldRule | None = _matching_rule(segment=segment, rule_set=rule_set)
        if matched_rule is None:
            continue
        field_value: str = segment[len(matched_rule.token.value) :].strip()
        if not field_value:
            has_empty_field_value = True
            continue
        if matched_rule.field_name in seen_field_names:
            duplicate_field_names.append(matched_rule.field_name)
            continue
        extracted_field: ExtractedTextField = ExtractedTextField(
            name=matched_rule.field_name,
            value=NormalizedText(value=field_value),
        )
        extracted_fields.append(extracted_field)
        seen_field_names.append(matched_rule.field_name)

    return _FrameScan(
        position=frame_position,
        fields=tuple(extracted_fields),
        duplicate_field_names=tuple(duplicate_field_names),
        has_empty_field_value=has_empty_field_value,
    )


def _matching_rule(segment: str, rule_set: RuleSet) -> FieldRule | None:
    """Return the sole configured rule whose token prefixes a segment."""
    field_rule: FieldRule
    for field_rule in rule_set.field_rules:
        if segment.startswith(field_rule.token.value):
            return field_rule
    return None


def _has_all_required_fields(scan: _FrameScan, rule_set: RuleSet) -> bool:
    """Check completeness inside one frame, never across the source text."""
    present_names: tuple[TextFieldName, ...] = _field_names(scan.fields)
    field_rule: FieldRule
    for field_rule in rule_set.field_rules:
        if field_rule.required and field_rule.field_name not in present_names:
            return False
    return True


def _has_recognized_field(scans: tuple[_FrameScan, ...]) -> bool:
    """Tell whether at least one configured token was recognized in source text."""
    scan: _FrameScan
    for scan in scans:
        if scan.fields or scan.has_empty_field_value:
            return True
    return False


def _required_fields_are_split_across_frames(
    scans: tuple[_FrameScan, ...], rule_set: RuleSet
) -> bool:
    """Detect global presence without a complete single frame to prevent borrowing."""
    field_rule: FieldRule
    for field_rule in rule_set.field_rules:
        if field_rule.required and not _field_name_occurs(
            field_name=field_rule.field_name, scans=scans
        ):
            return False
    return True


def _field_name_occurs(field_name: TextFieldName, scans: tuple[_FrameScan, ...]) -> bool:
    """Find actual evidence of one field without constructing a combined result."""
    scan: _FrameScan
    for scan in scans:
        if field_name in _field_names(scan.fields):
            return True
    return False


def _most_complete_partial_scan(scans: tuple[_FrameScan, ...]) -> _FrameScan | None:
    """Choose the first maximum partial frame deterministically for inspection only."""
    selected_scan: _FrameScan | None = None
    scan: _FrameScan
    for scan in scans:
        if not scan.fields:
            continue
        if selected_scan is None or len(scan.fields) > len(selected_scan.fields):
            selected_scan = scan
    return selected_scan


def _extraction(
    normalized_text: NormalizedText, fields: tuple[ExtractedTextField, ...]
) -> FieldExtractionResult:
    """Keep source text bound to actual fields that came from one frame."""
    return FieldExtractionResult(normalized_text=normalized_text, fields=fields)


def _field_names(fields: tuple[ExtractedTextField, ...]) -> tuple[TextFieldName, ...]:
    """Retain parser encounter order in an immutable typed collection."""
    return tuple(field.name for field in fields)


def _observed_field_names(scans: tuple[_FrameScan, ...]) -> tuple[TextFieldName, ...]:
    """Expose observed evidence without manufacturing a field extraction."""
    observed_names: list[TextFieldName] = []
    scan: _FrameScan
    for scan in scans:
        observed_names.extend(_field_names(scan.fields))
    return tuple(observed_names)


def _positions_with_fields(scans: tuple[_FrameScan, ...]) -> tuple[FramePosition, ...]:
    """Return only frames that carry real extracted evidence."""
    return tuple(scan.position for scan in scans if scan.fields)
