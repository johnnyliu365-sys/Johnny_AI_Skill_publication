"""Metadata-only context-load telemetry for Router baseline comparisons."""

from __future__ import annotations

import re
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Literal, Protocol

from pydantic import Field, ValidationError, model_validator

from .contracts import (
    ArtifactKind,
    BlockerCode,
    ConsumerFingerprint,
    DeliveryStage,
    NonBlankText,
    ProcessStage,
    ResolvedContext,
    RouterDecision,
    RouterEvent,
    RouterEventKind,
    RouterModel,
    RouterOutcome,
    RouterState,
    SourceSnippet,
)
from .profile import ProjectWorkflowProfile


NonNegativeCount = Annotated[int, Field(ge=0)]
PositiveAttempt = Annotated[int, Field(gt=0)]


class TelemetryMode(str, Enum):
    """The two comparable context-construction modes."""

    BASELINE = "baseline"
    ROUTER = "router"


class RunAcceptance(str, Enum):
    """The outcome of the human or automated task acceptance check."""

    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"


class TelemetryIssueCode(str, Enum):
    """Closed reasons why evidence cannot substantiate a reduction claim."""

    NO_RECORDS = "no_records"
    CONTEXT_BUDGET_EXCEEDED = "context_budget_exceeded"
    UNDECLARED_SOURCE = "undeclared_source"
    RAW_TEXT_IN_SHARED_STATE = "raw_text_in_shared_state"
    INCOMPLETE_COMPARISON_PAIR = "incomplete_comparison_pair"
    DUPLICATE_COMPARISON_PAIR = "duplicate_comparison_pair"
    MISMATCHED_STAGE = "mismatched_stage"
    MISSING_PROVIDER_INPUT_TOKENS = "missing_provider_input_tokens"
    ZERO_BASELINE_INPUT_TOKENS = "zero_baseline_input_tokens"
    QUALITY_REGRESSION = "quality_regression"


class AgentUsage(RouterModel):
    """Provider metadata and usage counts; it intentionally excludes prompts and outputs."""

    provider: NonBlankText
    model: NonBlankText
    consumer: ConsumerFingerprint
    provider_input_tokens: NonNegativeCount | None = None
    provider_output_tokens: NonNegativeCount | None = None
    tool_read_count: NonNegativeCount
    retry_count: NonNegativeCount
    duration_ms: NonNegativeCount


class ContextSourceUsage(RouterModel):
    """A safe fingerprint and size estimate for one source span, never the source text or URI."""

    kind: ArtifactKind
    identifier: NonBlankText
    revision: NonBlankText
    span: NonBlankText
    source_fingerprint: NonBlankText
    estimated_tokens: NonNegativeCount

    @classmethod
    def from_snippet(cls, *, snippet: SourceSnippet) -> ContextSourceUsage:
        """Project a raw snippet into safe measurement metadata."""

        fingerprint_material = "\x1f".join(
            (
                snippet.source.kind.value,
                snippet.source.identifier,
                snippet.source.uri,
                snippet.source.revision,
                snippet.span,
            )
        )
        return cls(
            kind=snippet.source.kind,
            identifier=snippet.source.identifier,
            revision=snippet.source.revision,
            span=snippet.span,
            source_fingerprint=sha256(fingerprint_material.encode("utf-8")).hexdigest(),
            estimated_tokens=estimate_text_tokens(text=snippet.text),
        )


class ContextLoadMeasurement(RouterModel):
    """Metadata-only observation of one ContextPacket."""

    sources: tuple[ContextSourceUsage, ...]
    declared_source_count: NonNegativeCount
    actual_source_count: NonNegativeCount
    undeclared_source_count: NonNegativeCount
    estimated_packet_tokens: NonNegativeCount
    token_budget: NonNegativeCount | None
    budget_exceeded: bool
    raw_text_in_shared_state: bool

    @model_validator(mode="after")
    def measurement_is_consistent(self) -> ContextLoadMeasurement:
        """Keep telemetry counters meaningful even when written by an external runner."""

        if self.actual_source_count != len(self.sources):
            raise ValueError("actual_source_count must equal the number of source measurements")
        if self.undeclared_source_count > self.actual_source_count:
            raise ValueError("undeclared_source_count cannot exceed actual_source_count")
        if self.token_budget is None and self.budget_exceeded:
            raise ValueError("baseline measurements cannot report a budget breach")
        if self.token_budget is not None and self.budget_exceeded != (
            self.estimated_packet_tokens > self.token_budget
        ):
            raise ValueError("budget_exceeded must match estimated_packet_tokens and token_budget")
        return self


class RouterUsageMetadata(RouterModel):
    """Router-only fields needed to audit a selected ContextView without source content."""

    profile_id: NonBlankText
    profile_version: NonBlankText
    event_kind: RouterEventKind
    decision_outcome: RouterOutcome
    blocker_codes: tuple[BlockerCode, ...]
    context_view_id: NonBlankText


class ContextUsageRecord(RouterModel):
    """One safe, schema-validated local evidence record for a baseline or Router run."""

    schema_version: Literal["1"] = "1"
    run_id: NonBlankText
    comparison_group_id: NonBlankText
    attempt: PositiveAttempt
    project_snapshot_id: NonBlankText
    mode: TelemetryMode
    stage: ProcessStage
    delivery_stage: DeliveryStage
    agent: AgentUsage
    router: RouterUsageMetadata | None = None
    context: ContextLoadMeasurement
    acceptance: RunAcceptance
    human_correction_required: bool

    @model_validator(mode="after")
    def record_mode_matches_router_metadata(self) -> ContextUsageRecord:
        """Prevent a baseline record from masquerading as a router-selected context run."""

        if self.mode is TelemetryMode.ROUTER:
            if self.router is None or self.context.token_budget is None:
                raise ValueError("router records require router metadata and a ContextView token budget")
        elif self.router is not None or self.context.token_budget is not None:
            raise ValueError("baseline records cannot contain router metadata or a token budget")
        return self

    @classmethod
    def from_router(
        cls,
        *,
        run_id: NonBlankText,
        comparison_group_id: NonBlankText,
        attempt: PositiveAttempt,
        project_snapshot_id: NonBlankText,
        state: RouterState,
        event: RouterEvent,
        profile: ProjectWorkflowProfile,
        decision: RouterDecision,
        resolved_context: ResolvedContext,
        agent: AgentUsage,
        acceptance: RunAcceptance,
        human_correction_required: bool,
    ) -> ContextUsageRecord:
        """Capture a Router-selected packet without retaining its raw snippets."""

        sources = tuple(
            ContextSourceUsage.from_snippet(snippet=snippet)
            for snippet in resolved_context.packet.snippets
        )
        declared_sources = decision.required_sources
        undeclared_source_count = sum(
            1
            for snippet in resolved_context.packet.snippets
            if snippet.source not in declared_sources
        )
        estimated_packet_tokens = sum(source.estimated_tokens for source in sources)
        token_budget = resolved_context.view.token_budget
        return cls(
            run_id=run_id,
            comparison_group_id=comparison_group_id,
            attempt=attempt,
            project_snapshot_id=project_snapshot_id,
            mode=TelemetryMode.ROUTER,
            stage=state.stage,
            delivery_stage=state.delivery_stage,
            agent=agent,
            router=RouterUsageMetadata(
                profile_id=profile.profile_id,
                profile_version=profile.profile_version,
                event_kind=event.kind,
                decision_outcome=decision.outcome,
                blocker_codes=tuple(blocker.code for blocker in decision.blockers),
                context_view_id=resolved_context.view.view_id,
            ),
            context=ContextLoadMeasurement(
                sources=sources,
                declared_source_count=len(declared_sources),
                actual_source_count=len(sources),
                undeclared_source_count=undeclared_source_count,
                estimated_packet_tokens=estimated_packet_tokens,
                token_budget=token_budget,
                budget_exceeded=estimated_packet_tokens > token_budget,
                raw_text_in_shared_state=context_view_contains_text_field(
                    resolved_context=resolved_context
                ),
            ),
            acceptance=acceptance,
            human_correction_required=human_correction_required,
        )

    @classmethod
    def from_baseline(
        cls,
        *,
        run_id: NonBlankText,
        comparison_group_id: NonBlankText,
        attempt: PositiveAttempt,
        project_snapshot_id: NonBlankText,
        stage: ProcessStage,
        delivery_stage: DeliveryStage,
        source_snippets: tuple[SourceSnippet, ...],
        agent: AgentUsage,
        acceptance: RunAcceptance,
        human_correction_required: bool,
    ) -> ContextUsageRecord:
        """Capture a non-router baseline with the same safe output schema."""

        sources = tuple(
            ContextSourceUsage.from_snippet(snippet=snippet) for snippet in source_snippets
        )
        return cls(
            run_id=run_id,
            comparison_group_id=comparison_group_id,
            attempt=attempt,
            project_snapshot_id=project_snapshot_id,
            mode=TelemetryMode.BASELINE,
            stage=stage,
            delivery_stage=delivery_stage,
            agent=agent,
            context=ContextLoadMeasurement(
                sources=sources,
                declared_source_count=len(sources),
                actual_source_count=len(sources),
                undeclared_source_count=0,
                estimated_packet_tokens=sum(source.estimated_tokens for source in sources),
                token_budget=None,
                budget_exceeded=False,
                raw_text_in_shared_state=False,
            ),
            acceptance=acceptance,
            human_correction_required=human_correction_required,
        )


class TelemetryValidationIssue(RouterModel):
    """One non-sensitive reason why a reduction claim is invalid."""

    code: TelemetryIssueCode
    run_ids: tuple[NonBlankText, ...]
    detail: NonBlankText


class ContextLoadComparison(RouterModel):
    """One matched baseline/router pair measured using provider token reports."""

    comparison_group_id: NonBlankText
    attempt: PositiveAttempt
    project_snapshot_id: NonBlankText
    provider: NonBlankText
    model: NonBlankText
    baseline_run_id: NonBlankText
    router_run_id: NonBlankText
    baseline_input_tokens: NonNegativeCount
    router_input_tokens: NonNegativeCount
    reduction_basis_points: int
    quality_preserved: bool


class ContextLoadValidationReport(RouterModel):
    """Fail-closed validation output suitable for a later offline review."""

    evidence_valid: bool
    reduction_verified: bool
    minimum_reduction_basis_points: NonNegativeCount
    median_reduction_basis_points: int | None
    comparisons: tuple[ContextLoadComparison, ...]
    issues: tuple[TelemetryValidationIssue, ...]


class JsonlContextUsageStore:
    """Append and restore validated metadata-only telemetry records from local JSONL."""

    @staticmethod
    def append(*, path: Path, record: ContextUsageRecord) -> None:
        """Append one validated record; callers choose an ignored local path."""

        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(record.model_dump_json())
            handle.write("\n")

    @staticmethod
    def read(*, path: Path) -> tuple[ContextUsageRecord, ...]:
        """Restore records while exposing only a line number for malformed evidence."""

        records: list[ContextUsageRecord] = []
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                serialized = line.strip()
                if not serialized:
                    continue
                try:
                    records.append(ContextUsageRecord.model_validate_json(serialized))
                except ValidationError as error:
                    raise ValueError(f"invalid context telemetry on line {line_number}") from error
        return tuple(records)


class ContextUsageValidator:
    """Validate Router guards and matched evidence before a reduction claim is accepted."""

    def validate(
        self,
        *,
        records: tuple[ContextUsageRecord, ...],
        minimum_reduction_basis_points: NonNegativeCount = 1,
    ) -> ContextLoadValidationReport:
        """Return a fail-closed report without inspecting source text or prompts."""

        issues: list[TelemetryValidationIssue] = []
        if not records:
            issues.append(
                TelemetryValidationIssue(
                    code=TelemetryIssueCode.NO_RECORDS,
                    run_ids=(),
                    detail="no context telemetry records were supplied",
                )
            )
        for record in records:
            self._append_router_guard_issues(record=record, issues=issues)

        grouped: defaultdict[tuple[str, int, str, str, str], list[ContextUsageRecord]] = defaultdict(list)
        for record in records:
            grouped[
                (
                    record.comparison_group_id,
                    record.attempt,
                    record.project_snapshot_id,
                    record.agent.provider,
                    record.agent.model,
                )
            ].append(record)

        comparisons: list[ContextLoadComparison] = []
        for grouped_records in grouped.values():
            self._validate_group(
                grouped_records=tuple(grouped_records),
                comparisons=comparisons,
                issues=issues,
            )

        median_reduction_basis_points = self._median_basis_points(comparisons=comparisons)
        evidence_valid = not issues and bool(comparisons)
        reduction_verified = (
            evidence_valid
            and median_reduction_basis_points is not None
            and median_reduction_basis_points >= minimum_reduction_basis_points
        )
        return ContextLoadValidationReport(
            evidence_valid=evidence_valid,
            reduction_verified=reduction_verified,
            minimum_reduction_basis_points=minimum_reduction_basis_points,
            median_reduction_basis_points=median_reduction_basis_points,
            comparisons=tuple(comparisons),
            issues=tuple(issues),
        )

    @staticmethod
    def _append_router_guard_issues(
        *,
        record: ContextUsageRecord,
        issues: list[TelemetryValidationIssue],
    ) -> None:
        """Reject any Router run that did not obey its declared context constraints."""

        if record.mode is not TelemetryMode.ROUTER:
            return
        if record.context.budget_exceeded:
            issues.append(
                TelemetryValidationIssue(
                    code=TelemetryIssueCode.CONTEXT_BUDGET_EXCEEDED,
                    run_ids=(record.run_id,),
                    detail="router ContextPacket exceeded its ContextView token budget",
                )
            )
        if record.context.undeclared_source_count:
            issues.append(
                TelemetryValidationIssue(
                    code=TelemetryIssueCode.UNDECLARED_SOURCE,
                    run_ids=(record.run_id,),
                    detail="router ContextPacket contained a source outside RouterDecision.required_sources",
                )
            )
        if record.context.raw_text_in_shared_state:
            issues.append(
                TelemetryValidationIssue(
                    code=TelemetryIssueCode.RAW_TEXT_IN_SHARED_STATE,
                    run_ids=(record.run_id,),
                    detail="ContextView serialization exposed a raw text field",
                )
            )

    @staticmethod
    def _validate_group(
        *,
        grouped_records: tuple[ContextUsageRecord, ...],
        comparisons: list[ContextLoadComparison],
        issues: list[TelemetryValidationIssue],
    ) -> None:
        """Validate one candidate baseline/router pair deterministically."""

        baseline_records = tuple(
            record for record in grouped_records if record.mode is TelemetryMode.BASELINE
        )
        router_records = tuple(
            record for record in grouped_records if record.mode is TelemetryMode.ROUTER
        )
        run_ids = tuple(record.run_id for record in grouped_records)
        if not baseline_records or not router_records:
            issues.append(
                TelemetryValidationIssue(
                    code=TelemetryIssueCode.INCOMPLETE_COMPARISON_PAIR,
                    run_ids=run_ids,
                    detail="each comparison group requires one baseline run and one router run",
                )
            )
            return
        if len(baseline_records) != 1 or len(router_records) != 1:
            issues.append(
                TelemetryValidationIssue(
                    code=TelemetryIssueCode.DUPLICATE_COMPARISON_PAIR,
                    run_ids=run_ids,
                    detail="each comparison group may contain exactly one baseline and one router run",
                )
            )
            return
        baseline = baseline_records[0]
        router = router_records[0]
        if baseline.stage is not router.stage or baseline.delivery_stage is not router.delivery_stage:
            issues.append(
                TelemetryValidationIssue(
                    code=TelemetryIssueCode.MISMATCHED_STAGE,
                    run_ids=(baseline.run_id, router.run_id),
                    detail="baseline and router runs must use the same process and delivery stage",
                )
            )
            return
        if baseline.agent.provider_input_tokens is None or router.agent.provider_input_tokens is None:
            issues.append(
                TelemetryValidationIssue(
                    code=TelemetryIssueCode.MISSING_PROVIDER_INPUT_TOKENS,
                    run_ids=(baseline.run_id, router.run_id),
                    detail="provider-reported input tokens are required for a reduction claim",
                )
            )
            return
        if baseline.agent.provider_input_tokens == 0:
            issues.append(
                TelemetryValidationIssue(
                    code=TelemetryIssueCode.ZERO_BASELINE_INPUT_TOKENS,
                    run_ids=(baseline.run_id, router.run_id),
                    detail="baseline provider input tokens must be greater than zero",
                )
            )
            return
        quality_preserved = not (
            baseline.acceptance is RunAcceptance.PASSED
            and (
                router.acceptance is not RunAcceptance.PASSED
                or (
                    not baseline.human_correction_required
                    and router.human_correction_required
                )
            )
        )
        if not quality_preserved:
            issues.append(
                TelemetryValidationIssue(
                    code=TelemetryIssueCode.QUALITY_REGRESSION,
                    run_ids=(baseline.run_id, router.run_id),
                    detail="router run reduced acceptance quality relative to its baseline",
                )
            )
            return
        baseline_input_tokens = baseline.agent.provider_input_tokens
        router_input_tokens = router.agent.provider_input_tokens
        reduction_basis_points = (
            (baseline_input_tokens - router_input_tokens) * 10_000
        ) // baseline_input_tokens
        comparisons.append(
            ContextLoadComparison(
                comparison_group_id=baseline.comparison_group_id,
                attempt=baseline.attempt,
                project_snapshot_id=baseline.project_snapshot_id,
                provider=baseline.agent.provider,
                model=baseline.agent.model,
                baseline_run_id=baseline.run_id,
                router_run_id=router.run_id,
                baseline_input_tokens=baseline_input_tokens,
                router_input_tokens=router_input_tokens,
                reduction_basis_points=reduction_basis_points,
                quality_preserved=True,
            )
        )

    @staticmethod
    def _median_basis_points(*, comparisons: list[ContextLoadComparison]) -> int | None:
        """Return a deterministic integer median without a floating-point measurement claim."""

        if not comparisons:
            return None
        values = sorted(comparison.reduction_basis_points for comparison in comparisons)
        middle = len(values) // 2
        if len(values) % 2:
            return values[middle]
        return (values[middle - 1] + values[middle]) // 2


def estimate_text_tokens(*, text: NonBlankText) -> NonNegativeCount:
    """Return a deterministic UTF-8-size estimate, never a provider usage substitute."""

    return (len(text.encode("utf-8")) + 3) // 4


def context_view_contains_text_field(*, resolved_context: ResolvedContext) -> bool:
    """Detect a forbidden text field in the durable descriptor without persisting raw text."""

    return '"text"' in resolved_context.view.model_dump_json()


# --- Explicit receipt-indexed telemetry report (Plugin Distribution AC-14) ---


class TelemetryRole(str, Enum):
    """The finite workflow roles a usage evidence record may claim."""

    ARCHITECTURE_OWNER = "ARCHITECTURE_OWNER"
    SUPERVISOR_REVIEWER = "SUPERVISOR_REVIEWER"
    IMPLEMENTATION_OWNER = "IMPLEMENTATION_OWNER"
    RESEARCH_HELPER = "RESEARCH_HELPER"


class ReasoningLevel(str, Enum):
    """The finite reasoning levels a usage evidence record may claim."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    XHIGH = "XHIGH"


_OPAQUE_REF_PATTERN = re.compile(r"^[a-z][a-z0-9-]{2,127}$")


class ModelPriceSnapshot(RouterModel):
    """Original-currency prices per million tokens captured with the evidence."""

    currency: str = Field(pattern=r"^[A-Z]{3}$")
    input_price_per_million: str = Field(pattern=r"^[0-9]+(?:\.[0-9]{1,6})?$")
    cached_input_price_per_million: str = Field(pattern=r"^[0-9]+(?:\.[0-9]{1,6})?$")
    output_price_per_million: str = Field(pattern=r"^[0-9]+(?:\.[0-9]{1,6})?$")


class RoleModelUsageEvidence(RouterModel):
    """One receipt-indexed committed usage observation; identifiers only."""

    schema_version: Literal["1"] = "1"
    receipt_ref: str = Field(pattern=r"^[a-z][a-z0-9-]{2,127}$")
    evidence_commit: str = Field(pattern=r"^[0-9a-f]{7,64}$")
    role: TelemetryRole
    provider: str = Field(pattern=r"^[a-z][a-z0-9-]{2,127}$")
    model: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]{0,127}$")
    reasoning_level: ReasoningLevel
    input_tokens: NonNegativeCount
    cached_input_tokens: NonNegativeCount
    output_tokens: NonNegativeCount
    price: ModelPriceSnapshot


class TelemetryReportStatus(str, Enum):
    """Finite outcomes of one explicit report request."""

    GENERATED = "GENERATED"
    BLOCKED = "BLOCKED"


class TelemetryReportFailure(str, Enum):
    """Finite reasons an explicit report request produces no report."""

    REQUEST_INVALID = "REQUEST_INVALID"
    RECEIPT_NOT_FOUND = "RECEIPT_NOT_FOUND"
    EVIDENCE_UNAVAILABLE = "EVIDENCE_UNAVAILABLE"
    RAW_CONTENT_REJECTED = "RAW_CONTENT_REJECTED"
    PRICE_SNAPSHOT_CONFLICT = "PRICE_SNAPSHOT_CONFLICT"


class TelemetryReportRequest(RouterModel):
    """One explicit user report request; the type admits no implicit run."""

    receipt_refs: tuple[str, ...] = Field(min_length=1)
    explicit_user_request: Literal[True]

    @model_validator(mode="after")
    def receipt_refs_are_opaque(self) -> TelemetryReportRequest:
        if any(
            _OPAQUE_REF_PATTERN.fullmatch(reference) is None
            for reference in self.receipt_refs
        ):
            raise ValueError("receipt references must be opaque identifiers")
        return self


class TelemetryReportGroup(RouterModel):
    """Aggregated token and cost evidence for one role/model/reasoning/currency."""

    role: TelemetryRole
    provider: str = Field(pattern=r"^[a-z][a-z0-9-]{2,127}$")
    model: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]{0,127}$")
    reasoning_level: ReasoningLevel
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    input_tokens: NonNegativeCount
    cached_input_tokens: NonNegativeCount
    output_tokens: NonNegativeCount
    input_cost: str = Field(pattern=r"^[0-9]+(?:\.[0-9]{1,6})?$")
    cached_input_cost: str = Field(pattern=r"^[0-9]+(?:\.[0-9]{1,6})?$")
    output_cost: str = Field(pattern=r"^[0-9]+(?:\.[0-9]{1,6})?$")
    total_cost: str = Field(pattern=r"^[0-9]+(?:\.[0-9]{1,6})?$")


class TelemetryReport(RouterModel):
    """Exactly one generated report or exactly one finite failure."""

    status: TelemetryReportStatus
    failure: TelemetryReportFailure | None = None
    groups: tuple[TelemetryReportGroup, ...] = ()

    @model_validator(mode="after")
    def exact_report_shape(self) -> TelemetryReport:
        if self.status is TelemetryReportStatus.GENERATED:
            if self.failure is not None:
                raise ValueError("a generated report cannot expose a failure")
        elif self.failure is None or self.groups:
            raise ValueError("a blocked report requires one failure and no groups")
        return self


class TelemetryBarDatum(RouterModel):
    """One bar-chart value derived from exactly one report group."""

    group_index: NonNegativeCount
    label: NonBlankText
    token_class: Literal["input", "cached_input", "output"]
    value: NonNegativeCount


class ReceiptUsageEvidenceSource(Protocol):
    """Resolve committed usage evidence for one receipt reference."""

    def resolve(
        self, receipt_ref: str
    ) -> tuple[RoleModelUsageEvidence, ...] | None: ...


def _blocked_report(failure: TelemetryReportFailure) -> TelemetryReport:
    return TelemetryReport(status=TelemetryReportStatus.BLOCKED, failure=failure)


def _cost_amount(tokens: int, price_per_million: str) -> Decimal:
    return (
        Decimal(tokens) * Decimal(price_per_million) / Decimal(1_000_000)
    ).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def generate_telemetry_report(
    request: TelemetryReportRequest,
    source: ReceiptUsageEvidenceSource,
) -> TelemetryReport:
    """Resolve receipt-indexed evidence and aggregate it; never run implicitly."""

    if type(request) is not TelemetryReportRequest:
        return _blocked_report(TelemetryReportFailure.REQUEST_INVALID)
    try:
        trusted = TelemetryReportRequest.model_validate(request, strict=True)
    except ValidationError:
        return _blocked_report(TelemetryReportFailure.REQUEST_INVALID)

    evidence: list[RoleModelUsageEvidence] = []
    for receipt_ref in trusted.receipt_refs:
        try:
            resolved = source.resolve(receipt_ref)
        except Exception:
            return _blocked_report(TelemetryReportFailure.EVIDENCE_UNAVAILABLE)
        if resolved is None:
            return _blocked_report(TelemetryReportFailure.RECEIPT_NOT_FOUND)
        for record in resolved:
            # Raw-content denial: forged records that bypassed construction
            # validation are re-proven field by field before any aggregation.
            try:
                payload = (
                    record.model_dump()
                    if isinstance(record, RoleModelUsageEvidence)
                    else record
                )
                evidence.append(RoleModelUsageEvidence.model_validate(payload))
            except (ValidationError, AttributeError, TypeError):
                return _blocked_report(TelemetryReportFailure.RAW_CONTENT_REJECTED)

    grouped: dict[
        tuple[TelemetryRole, str, str, ReasoningLevel, str],
        list[RoleModelUsageEvidence],
    ] = defaultdict(list)
    for record in evidence:
        grouped[
            (
                record.role,
                record.provider,
                record.model,
                record.reasoning_level,
                record.price.currency,
            )
        ].append(record)

    groups: list[TelemetryReportGroup] = []
    for key in sorted(grouped, key=lambda item: tuple(str(part) for part in item)):
        members = grouped[key]
        first_price = members[0].price
        if any(member.price != first_price for member in members):
            return _blocked_report(TelemetryReportFailure.PRICE_SNAPSHOT_CONFLICT)
        input_tokens = sum(member.input_tokens for member in members)
        cached_tokens = sum(member.cached_input_tokens for member in members)
        output_tokens = sum(member.output_tokens for member in members)
        input_cost = _cost_amount(input_tokens, first_price.input_price_per_million)
        cached_cost = _cost_amount(
            cached_tokens, first_price.cached_input_price_per_million
        )
        output_cost = _cost_amount(output_tokens, first_price.output_price_per_million)
        groups.append(
            TelemetryReportGroup(
                role=key[0],
                provider=key[1],
                model=key[2],
                reasoning_level=key[3],
                currency=key[4],
                input_tokens=input_tokens,
                cached_input_tokens=cached_tokens,
                output_tokens=output_tokens,
                input_cost=format(input_cost, "f"),
                cached_input_cost=format(cached_cost, "f"),
                output_cost=format(output_cost, "f"),
                total_cost=format(input_cost + cached_cost + output_cost, "f"),
            )
        )
    return TelemetryReport(status=TelemetryReportStatus.GENERATED, groups=tuple(groups))


_REPORT_CSV_COLUMNS: tuple[str, ...] = (
    "role",
    "provider",
    "model",
    "reasoning_level",
    "currency",
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "input_cost",
    "cached_input_cost",
    "output_cost",
    "total_cost",
)


def render_report_json(report: TelemetryReport) -> str:
    """Render the exact typed report as JSON."""

    return report.model_dump_json(indent=2)


def render_report_csv(report: TelemetryReport) -> str:
    """Render one CSV row per group with the exact aggregated values."""

    lines = [",".join(_REPORT_CSV_COLUMNS)]
    for group in report.groups:
        record = group.model_dump()
        lines.append(",".join(str(record[column]) for column in _REPORT_CSV_COLUMNS))
    return "\n".join(lines) + "\n"


def render_report_table(report: TelemetryReport) -> str:
    """Render one aligned terminal row per group with the exact values."""

    header = (
        f"{'role':24} {'model':20} {'level':6} {'ccy':3} "
        f"{'input':>10} {'cached':>10} {'output':>10} {'total_cost':>14}"
    )
    divider = "-" * len(header)
    rows = [header, divider]
    for group in report.groups:
        rows.append(
            f"{group.role.value:24} {group.model:20} "
            f"{group.reasoning_level.value:6} {group.currency:3} "
            f"{group.input_tokens:>10} {group.cached_input_tokens:>10} "
            f"{group.output_tokens:>10} {group.total_cost:>14}"
        )
    return "\n".join(rows) + "\n"


def report_bar_chart_data(report: TelemetryReport) -> tuple[TelemetryBarDatum, ...]:
    """Return three bars per group carrying the exact token class values."""

    data: list[TelemetryBarDatum] = []
    token_classes: tuple[Literal["input", "cached_input", "output"], ...] = (
        "input",
        "cached_input",
        "output",
    )
    for index, group in enumerate(report.groups):
        label = f"{group.role.value}/{group.model}/{group.reasoning_level.value}"
        values = (
            group.input_tokens,
            group.cached_input_tokens,
            group.output_tokens,
        )
        for token_class, value in zip(token_classes, values, strict=True):
            data.append(
                TelemetryBarDatum(
                    group_index=index,
                    label=label,
                    token_class=token_class,
                    value=value,
                )
            )
    return tuple(data)


class JsonlReceiptUsageEvidenceStore:
    """Read receipt-indexed usage evidence from one local JSONL file."""

    def __init__(self, records: tuple[RoleModelUsageEvidence, ...]) -> None:
        self._records = records

    @classmethod
    def read(cls, *, path: Path) -> JsonlReceiptUsageEvidenceStore:
        records: list[RoleModelUsageEvidence] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            records.append(RoleModelUsageEvidence.model_validate_json(stripped))
        return cls(tuple(records))

    def resolve(self, receipt_ref: str) -> tuple[RoleModelUsageEvidence, ...] | None:
        matched = tuple(
            record for record in self._records if record.receipt_ref == receipt_ref
        )
        return matched if matched else None
