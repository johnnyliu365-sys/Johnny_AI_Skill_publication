"""Static, read-only report of what Router-based context loading should save.

This module answers a narrower question than "how many tokens did routing save":
for each row of the live routing table (`profile.TransitionRule`), how many bytes
would a "read every reference" baseline load, versus how many would the single
reference that row names? Both numbers are then converted to a token count via
`telemetry.estimate_text_tokens`.

Every produced number is a size-derived **estimate**, never a provider-billed token
count. `LoadEstimate.is_estimate` is fixed at the type level so that label can never
be dropped or flipped by a caller. See
`modules/tickets/context-load-telemetry/03-measure-what-routing-actually-saves.md`
for the full contract, including what this module explicitly does not claim: it does
not compare against real provider usage (see that ticket's section explaining why a
real-usage comparison is out of scope).

Both inputs are read-only:
- the routing table is the caller-supplied `transition_rules` (normally
  `profile.build_router_poc_profile().transition_rules`);
- reference sizes are read from `references_dir` (normally
  `skills/johnny-project-takeover/references/`).

This module never writes to the filesystem and never imports anything that would let
it do so.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .contracts import NonBlankText, OpaqueMetadataId, ProcessStage, RouterEventKind, RouterModel
from .profile import TransitionRule, build_router_poc_profile
from .telemetry import NonNegativeCount, estimate_text_tokens

DEFAULT_REFERENCES_DIR: Path = (
    Path(__file__).resolve().parents[2] / "skills" / "johnny-project-takeover" / "references"
)

_RATIO_PATTERN = r"^[0-9]+(?:\.[0-9]{1,6})?$"
_RATIO_QUANTUM = Decimal("0.000001")


class ContextLoadReportStatus(str, Enum):
    """Finite outcomes of one report computation."""

    GENERATED = "GENERATED"
    BLOCKED = "BLOCKED"


class ContextLoadReportFailure(str, Enum):
    """Finite, distinguishable reasons a report computation fails closed.

    Every member fails the whole computation rather than substituting a zero or a
    partial result; a routing table naming a reference that does not exist on disk
    is a `ROUTED_REFERENCE_FILE_MISSING` failure, never a silently-zero row.
    """

    REFERENCES_DIRECTORY_MISSING = "REFERENCES_DIRECTORY_MISSING"
    REFERENCES_DIRECTORY_EMPTY = "REFERENCES_DIRECTORY_EMPTY"
    ROUTING_TABLE_EMPTY = "ROUTING_TABLE_EMPTY"
    ROUTED_REFERENCE_FILE_MISSING = "ROUTED_REFERENCE_FILE_MISSING"
    REFERENCE_FILE_UNREADABLE = "REFERENCE_FILE_UNREADABLE"


class LoadEstimate(RouterModel):
    """A self-labeled, non-billing size estimate for one set of loaded files.

    `is_estimate` is a fixed `Literal[True]` rather than a plain `bool`: a caller
    cannot construct a `LoadEstimate` that claims to be a measured value, and cannot
    omit the label, because the field cannot validate to anything but `True`.
    """

    byte_count: NonNegativeCount
    estimated_tokens: NonNegativeCount
    is_estimate: Literal[True] = True
    measurement_basis: Literal["repo_file_size_estimate"] = "repo_file_size_estimate"


class StageRouteLoadEntry(RouterModel):
    """Baseline-vs-routed load comparison for one routing-table row.

    One entry exists per `(current_stage, event_kind)` row actually present in the
    routing table -- not one per `ProcessStage` -- because several stages route to
    different references depending on the event (for example `wayfinder` routes to
    `discovery-change` on three events and to `router-control` on
    `WAYFINDER_NO_GO`). Collapsing those rows to a single "the" reference per stage
    would misrepresent the table, so this type never does it.
    """

    current_stage: ProcessStage
    event_kind: RouterEventKind
    reference_id: OpaqueMetadataId
    baseline: LoadEstimate
    routed: LoadEstimate
    routed_to_baseline_ratio: str = Field(pattern=_RATIO_PATTERN)
    byte_reduction: NonNegativeCount
    token_reduction: NonNegativeCount

    @model_validator(mode="after")
    def routed_load_is_bounded_by_baseline(self) -> StageRouteLoadEntry:
        """Keep a routed reference from ever exceeding the baseline it was drawn from."""

        if self.routed.byte_count > self.baseline.byte_count:
            raise ValueError("a routed reference cannot be larger than the full baseline")
        if self.routed.estimated_tokens > self.baseline.estimated_tokens:
            raise ValueError("a routed reference cannot exceed the baseline token estimate")
        if self.byte_reduction != self.baseline.byte_count - self.routed.byte_count:
            raise ValueError("byte_reduction must equal baseline minus routed byte counts")
        if self.token_reduction != self.baseline.estimated_tokens - self.routed.estimated_tokens:
            raise ValueError("token_reduction must equal baseline minus routed token estimates")
        return self


class ContextLoadReportSummary(RouterModel):
    """Cross-row rollup computed only over rows that actually route to a reference.

    `unrouted_stages` names every `ProcessStage` with zero rows in the routing table
    (for the live table: `blocked` and `stopped`, which are terminal states an agent
    never "enters" to do reference-guided work). They are listed explicitly rather
    than folded into the average, and never appear as a 100%-reduction entry.
    """

    routed_entry_count: NonNegativeCount
    average_routed_to_baseline_ratio: str = Field(pattern=_RATIO_PATTERN)
    worst_case_entry: StageRouteLoadEntry
    unrouted_stages: tuple[ProcessStage, ...]

    @model_validator(mode="after")
    def counts_are_consistent(self) -> ContextLoadReportSummary:
        """Keep the declared entry count from silently drifting from reality."""

        if self.routed_entry_count < 1:
            raise ValueError("a summary requires at least one routed entry")
        if len(set(self.unrouted_stages)) != len(self.unrouted_stages):
            raise ValueError("unrouted_stages must not repeat a stage")
        return self


class ContextLoadReport(RouterModel):
    """Exactly one generated report, or exactly one named, fail-closed failure."""

    status: ContextLoadReportStatus
    failure: ContextLoadReportFailure | None = None
    failure_detail: NonBlankText | None = None
    entries: tuple[StageRouteLoadEntry, ...] = ()
    summary: ContextLoadReportSummary | None = None

    @model_validator(mode="after")
    def exact_report_shape(self) -> ContextLoadReport:
        """Keep a generated report and a blocked report from ever looking alike."""

        if self.status is ContextLoadReportStatus.GENERATED:
            if self.failure is not None or self.failure_detail is not None:
                raise ValueError("a generated report cannot expose a failure")
            if not self.entries or self.summary is None:
                raise ValueError("a generated report requires entries and a summary")
        else:
            if self.failure is None or self.failure_detail is None:
                raise ValueError("a blocked report requires a failure and its detail")
            if self.entries or self.summary is not None:
                raise ValueError("a blocked report cannot expose entries or a summary")
        return self


def _blocked(failure: ContextLoadReportFailure, detail: str) -> ContextLoadReport:
    """Build one fail-closed report; the only way this module reports a problem."""

    return ContextLoadReport(
        status=ContextLoadReportStatus.BLOCKED,
        failure=failure,
        failure_detail=detail,
    )


def _ratio(numerator: int, denominator: int) -> str:
    """Format numerator/denominator as a fixed-point decimal string in [0, 1].

    denominator <= 0 is unreached by any live-data path (it would require every
    matched reference file to be zero bytes, which non-empty markdown references
    never are); it is handled rather than left to raise so this stays fail-closed
    even under a degenerate fixture.
    """

    if denominator <= 0:
        return "0.000000"
    value = (Decimal(numerator) / Decimal(denominator)).quantize(
        _RATIO_QUANTUM, rounding=ROUND_HALF_UP
    )
    return format(value, "f")


def _load_estimate(*, raw_bytes: bytes) -> LoadEstimate:
    """Derive byte count and estimated tokens from the same byte stream.

    Decoding raw bytes (rather than text-mode file reads, which perform universal
    newline translation) keeps `byte_count` and `estimated_tokens` mutually
    consistent even on a CRLF working copy: `text.encode("utf-8")` below round-trips
    back to exactly `raw_bytes`.
    """

    text = raw_bytes.decode("utf-8")
    return LoadEstimate(
        byte_count=len(raw_bytes),
        estimated_tokens=estimate_text_tokens(text=text) if text else 0,
    )


def generate_context_load_report(
    *,
    references_dir: Path,
    transition_rules: tuple[TransitionRule, ...],
) -> ContextLoadReport:
    """Compute the static, repo-derived baseline-vs-routed load report.

    `references_dir` is scanned non-recursively for `*.md` files -- a subdirectory
    or sibling directory's files are never counted. The reference-file set is never
    hardcoded: it is read fresh from `references_dir` on every call, so adding a
    file there changes the baseline on the next call with no code change.
    """

    if not references_dir.is_dir():
        return _blocked(
            ContextLoadReportFailure.REFERENCES_DIRECTORY_MISSING,
            f"{references_dir} is not a directory",
        )

    reference_paths = sorted(p for p in references_dir.glob("*.md") if p.is_file())
    if not reference_paths:
        return _blocked(
            ContextLoadReportFailure.REFERENCES_DIRECTORY_EMPTY,
            f"{references_dir} contains no *.md reference files",
        )

    if not transition_rules:
        return _blocked(
            ContextLoadReportFailure.ROUTING_TABLE_EMPTY,
            "transition_rules is empty; no routing row to report on",
        )

    per_reference: dict[str, LoadEstimate] = {}
    total_bytes = 0
    total_tokens = 0
    for path in reference_paths:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            return _blocked(
                ContextLoadReportFailure.REFERENCE_FILE_UNREADABLE,
                f"{path}: {exc}",
            )
        try:
            estimate = _load_estimate(raw_bytes=raw)
        except UnicodeDecodeError as exc:
            return _blocked(
                ContextLoadReportFailure.REFERENCE_FILE_UNREADABLE,
                f"{path}: {exc}",
            )
        per_reference[path.stem] = estimate
        total_bytes += estimate.byte_count
        total_tokens += estimate.estimated_tokens

    baseline = LoadEstimate(byte_count=total_bytes, estimated_tokens=total_tokens)

    entries: list[StageRouteLoadEntry] = []
    routed_stages: set[ProcessStage] = set()
    for rule in transition_rules:
        reference_id = rule.skill_reference.reference_id
        routed_estimate = per_reference.get(reference_id)
        if routed_estimate is None:
            expected_path = references_dir / f"{reference_id}.md"
            return _blocked(
                ContextLoadReportFailure.ROUTED_REFERENCE_FILE_MISSING,
                f"{rule.current_stage.value}/{rule.event_kind.value} names "
                f"'{reference_id}' but {expected_path} does not exist",
            )
        entries.append(
            StageRouteLoadEntry(
                current_stage=rule.current_stage,
                event_kind=rule.event_kind,
                reference_id=reference_id,
                baseline=baseline,
                routed=routed_estimate,
                routed_to_baseline_ratio=_ratio(routed_estimate.byte_count, baseline.byte_count),
                byte_reduction=baseline.byte_count - routed_estimate.byte_count,
                token_reduction=baseline.estimated_tokens - routed_estimate.estimated_tokens,
            )
        )
        routed_stages.add(rule.current_stage)

    unrouted_stages = tuple(stage for stage in ProcessStage if stage not in routed_stages)
    ratio_total = sum((Decimal(entry.routed_to_baseline_ratio) for entry in entries), Decimal(0))
    average_ratio = (ratio_total / len(entries)).quantize(_RATIO_QUANTUM, rounding=ROUND_HALF_UP)
    worst_case_entry = max(entries, key=lambda entry: Decimal(entry.routed_to_baseline_ratio))

    summary = ContextLoadReportSummary(
        routed_entry_count=len(entries),
        average_routed_to_baseline_ratio=format(average_ratio, "f"),
        worst_case_entry=worst_case_entry,
        unrouted_stages=unrouted_stages,
    )

    return ContextLoadReport(
        status=ContextLoadReportStatus.GENERATED,
        entries=tuple(entries),
        summary=summary,
    )


def generate_default_context_load_report() -> ContextLoadReport:
    """Compute the report for the live repo's real routing table and references dir.

    Both reads are read-only: `build_router_poc_profile()` (from `profile.py`, not
    modified by this module) supplies the routing table, and `DEFAULT_REFERENCES_DIR`
    points at the real `skills/johnny-project-takeover/references/` directory.
    """

    return generate_context_load_report(
        references_dir=DEFAULT_REFERENCES_DIR,
        transition_rules=build_router_poc_profile().transition_rules,
    )
