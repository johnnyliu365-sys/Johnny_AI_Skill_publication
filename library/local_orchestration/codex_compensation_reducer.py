"""Pure, finite compensation planning and reduction for one Codex attempt."""

from __future__ import annotations

from enum import Enum
from typing import Literal, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from .codex_registration_contracts import (
    CodexAttemptEffect,
    CodexAttemptEffectState,
    CodexRegistrationAttemptId,
    CodexRegistrationAttemptJournal,
    CodexRegistrationRejectReason,
    CodexRegistrationRejected,
    revalidate_current_attempt_journal,
)
from .host_contracts import CodexPreflightRequest


class _StrictModel(BaseModel):
    """Freeze every pure compensation boundary and forbid undeclared fields."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, revalidate_instances="always")


class CodexCompensationStep(str, Enum):
    """The only finite actions that a later composition ticket may perform."""

    REMOVE_PLUGIN = "REMOVE_PLUGIN"
    REMOVE_MARKETPLACE = "REMOVE_MARKETPLACE"
    PROVE_PLUGIN_LISTS_ABSENT = "PROVE_PLUGIN_LISTS_ABSENT"
    PROVE_INSTALLED_LOCATION_ABSENT = "PROVE_INSTALLED_LOCATION_ABSENT"
    PROVE_MARKETPLACE_ABSENT = "PROVE_MARKETPLACE_ABSENT"


class CodexProofTruth(str, Enum):
    """Normalized metadata-only truth for one absence proof."""

    PROVED_ABSENT = "PROVED_ABSENT"
    RESIDUE = "RESIDUE"
    UNPROVED = "UNPROVED"
    MALFORMED = "MALFORMED"
    MISMATCH = "MISMATCH"


class CodexCompensationBlockReason(str, Enum):
    """Finite fail-closed reasons before a result can be reduced."""

    JOURNAL_INVALID = "JOURNAL_INVALID"
    JOURNAL_REQUEST_MISMATCH = "JOURNAL_REQUEST_MISMATCH"
    JOURNAL_ATTEMPT_MISMATCH = "JOURNAL_ATTEMPT_MISMATCH"
    UNREACHABLE_JOURNAL_STATE = "UNREACHABLE_JOURNAL_STATE"
    PLAN_INVALID = "PLAN_INVALID"
    OUTCOME_SEQUENCE_INVALID = "OUTCOME_SEQUENCE_INVALID"
    OUTCOME_INVALID = "OUTCOME_INVALID"


class CodexCompensationReason(str, Enum):
    """Ordered metadata-only reasons retained by a complete reduction."""

    PLUGIN_REMOVAL_DECLARED_FAILURE = "PLUGIN_REMOVAL_DECLARED_FAILURE"
    MARKETPLACE_REMOVAL_DECLARED_FAILURE = "MARKETPLACE_REMOVAL_DECLARED_FAILURE"
    PLUGIN_INSTALLED_RESIDUE = "PLUGIN_INSTALLED_RESIDUE"
    PLUGIN_INSTALLED_UNPROVED = "PLUGIN_INSTALLED_UNPROVED"
    PLUGIN_INSTALLED_MALFORMED = "PLUGIN_INSTALLED_MALFORMED"
    PLUGIN_INSTALLED_MISMATCH = "PLUGIN_INSTALLED_MISMATCH"
    PLUGIN_AVAILABLE_RESIDUE = "PLUGIN_AVAILABLE_RESIDUE"
    PLUGIN_AVAILABLE_UNPROVED = "PLUGIN_AVAILABLE_UNPROVED"
    PLUGIN_AVAILABLE_MALFORMED = "PLUGIN_AVAILABLE_MALFORMED"
    PLUGIN_AVAILABLE_MISMATCH = "PLUGIN_AVAILABLE_MISMATCH"
    INSTALLED_LOCATION_RESIDUE = "INSTALLED_LOCATION_RESIDUE"
    INSTALLED_LOCATION_UNPROVED = "INSTALLED_LOCATION_UNPROVED"
    INSTALLED_LOCATION_MALFORMED = "INSTALLED_LOCATION_MALFORMED"
    INSTALLED_LOCATION_MISMATCH = "INSTALLED_LOCATION_MISMATCH"
    MARKETPLACE_RESIDUE = "MARKETPLACE_RESIDUE"
    MARKETPLACE_UNPROVED = "MARKETPLACE_UNPROVED"
    MARKETPLACE_MALFORMED = "MARKETPLACE_MALFORMED"
    MARKETPLACE_MISMATCH = "MARKETPLACE_MISMATCH"


class CodexCompensationPlanIdentity(_StrictModel):
    """Immutable current-attempt identity bound into one compensation plan."""

    request: CodexPreflightRequest
    attempt_id: CodexRegistrationAttemptId
    marketplace_state: CodexAttemptEffectState
    plugin_state: CodexAttemptEffectState


class CodexCompensationPlan(_StrictModel):
    """An exact journal-bound ordered plan with one or more owned removals."""

    journal: CodexRegistrationAttemptJournal
    request: CodexPreflightRequest
    attempt_id: CodexRegistrationAttemptId
    identity: CodexCompensationPlanIdentity
    status: Literal["COMPENSATION_REQUIRED"]
    steps: tuple[CodexCompensationStep, ...]

    @model_validator(mode="after")
    def requires_steps(self) -> Self:
        if not self.steps:
            raise ValueError("required compensation plan must contain steps")
        return self


class CodexNoCompensationPlan(_StrictModel):
    """An exact journal-bound plan that has no installer-owned authority."""

    journal: CodexRegistrationAttemptJournal
    request: CodexPreflightRequest
    attempt_id: CodexRegistrationAttemptId
    identity: CodexCompensationPlanIdentity
    status: Literal["NO_COMPENSATION_REQUIRED"]
    steps: tuple[CodexCompensationStep, ...]

    @model_validator(mode="after")
    def forbids_steps(self) -> Self:
        if self.steps:
            raise ValueError("no-compensation plan must not contain steps")
        return self


class CodexCompensationBlocked(_StrictModel):
    """A finite pre-reduction block with no raw diagnostic payload."""

    status: Literal["COMPENSATION_BLOCKED"]
    reason: CodexCompensationBlockReason


class CodexCompensationResidualJournal(_StrictModel):
    """Exact request-bound current-attempt state after pure reduction."""

    request: CodexPreflightRequest
    attempt_id: CodexRegistrationAttemptId
    marketplace_state: CodexAttemptEffectState
    plugin_state: CodexAttemptEffectState

    def unresolved_removal_order(self) -> tuple[CodexAttemptEffect, ...]:
        """Expose only the authority that still belongs to this exact journal."""

        effects: list[CodexAttemptEffect] = []
        if self.plugin_state in (CodexAttemptEffectState.MAY_EXIST, CodexAttemptEffectState.OWNED):
            effects.append(CodexAttemptEffect.PLUGIN)
        if self.marketplace_state in (CodexAttemptEffectState.MAY_EXIST, CodexAttemptEffectState.OWNED):
            effects.append(CodexAttemptEffect.MARKETPLACE)
        return tuple(effects)


class CodexRemovalConfirmed(_StrictModel):
    """A normalized exact confirmation for one planned removal step."""

    step: Literal[CodexCompensationStep.REMOVE_PLUGIN, CodexCompensationStep.REMOVE_MARKETPLACE]
    status: Literal["CONFIRMED"]


class CodexRemovalFailed(_StrictModel):
    """A normalized declared failure for one planned removal step."""

    step: Literal[CodexCompensationStep.REMOVE_PLUGIN, CodexCompensationStep.REMOVE_MARKETPLACE]
    status: Literal["DECLARED_FAILURE"]


class CodexPluginListsProof(_StrictModel):
    """Independent installed and available plugin-list absence truth."""

    step: Literal[CodexCompensationStep.PROVE_PLUGIN_LISTS_ABSENT]
    installed: CodexProofTruth
    available: CodexProofTruth


class CodexInstalledLocationProof(_StrictModel):
    """Normalized truth for the exact receipt-bound installed location."""

    step: Literal[CodexCompensationStep.PROVE_INSTALLED_LOCATION_ABSENT]
    truth: CodexProofTruth


class CodexMarketplaceProof(_StrictModel):
    """Normalized truth for the exact receipt-bound marketplace entry."""

    step: Literal[CodexCompensationStep.PROVE_MARKETPLACE_ABSENT]
    truth: CodexProofTruth


CodexCompensationObservation: TypeAlias = (
    CodexRemovalConfirmed
    | CodexRemovalFailed
    | CodexPluginListsProof
    | CodexInstalledLocationProof
    | CodexMarketplaceProof
)


class _CodexCompensationResult(_StrictModel):
    """Shared metadata-only completed-reduction fields."""

    reasons: tuple[CodexCompensationReason, ...]
    residual_journal: CodexCompensationResidualJournal

    @field_validator("reasons")
    @classmethod
    def unique_reasons(cls, reasons: tuple[CodexCompensationReason, ...]) -> tuple[CodexCompensationReason, ...]:
        if len(reasons) != len(set(reasons)):
            raise ValueError("compensation reasons must be unique")
        return reasons

    @property
    def remaining_authority(self) -> tuple[CodexAttemptEffect, ...]:
        """Derived compatibility view; the residual journal remains authoritative."""

        return self.residual_journal.unresolved_removal_order()


class CodexCompensationNoop(_CodexCompensationResult):
    """Complete reduction for an exact no-authority plan."""

    status: Literal["COMPENSATION_NOT_REQUIRED"]

    @model_validator(mode="after")
    def no_authority_or_reasons(self) -> Self:
        if self.reasons or self.residual_journal.unresolved_removal_order():
            raise ValueError("no-compensation result cannot retain a reason or authority")
        return self


class CodexCompensated(_CodexCompensationResult):
    """Complete reduction whose exact absence proofs clear all authority."""

    status: Literal["COMPENSATED"]

    @model_validator(mode="after")
    def no_authority_or_reasons(self) -> Self:
        if self.reasons or self.residual_journal.unresolved_removal_order():
            raise ValueError("compensated result cannot retain a reason or authority")
        return self


class CodexCompensationFailed(_CodexCompensationResult):
    """Complete reduction that retains declared failures and unresolved authority."""

    status: Literal["COMPENSATION_FAILED"]

    @model_validator(mode="after")
    def requires_reason(self) -> Self:
        if not self.reasons:
            raise ValueError("failed compensation result requires a finite reason")
        return self


CodexCompensationResult: TypeAlias = (
    CodexCompensationBlocked | CodexCompensationNoop | CodexCompensated | CodexCompensationFailed
)
CodexCompensationPlanResult: TypeAlias = CodexCompensationPlan | CodexNoCompensationPlan | CodexCompensationBlocked


_PROOF_STEPS: tuple[CodexCompensationStep, ...] = (
    CodexCompensationStep.PROVE_PLUGIN_LISTS_ABSENT,
    CodexCompensationStep.PROVE_MARKETPLACE_ABSENT,
    CodexCompensationStep.PROVE_INSTALLED_LOCATION_ABSENT,
)


def build_compensation_plan(
    journal: CodexRegistrationAttemptJournal,
    request: CodexPreflightRequest,
    attempt_id: CodexRegistrationAttemptId,
) -> CodexCompensationPlanResult:
    """Derive the only legal pure compensation plan for one current attempt."""

    validated_journal = _revalidate_current_journal(journal, request, attempt_id)
    if isinstance(validated_journal, CodexCompensationBlocked):
        return validated_journal
    state_pair = (validated_journal.marketplace_state, validated_journal.plugin_state)
    if state_pair == (CodexAttemptEffectState.OWNED, CodexAttemptEffectState.PREEXISTING):
        return _blocked(CodexCompensationBlockReason.UNREACHABLE_JOURNAL_STATE)
    steps = _steps_for_journal(validated_journal)
    if not steps:
        return CodexNoCompensationPlan(
            journal=validated_journal,
            request=request,
            attempt_id=attempt_id,
            identity=_plan_identity(validated_journal),
            status="NO_COMPENSATION_REQUIRED",
            steps=(),
        )
    return CodexCompensationPlan(
        journal=validated_journal,
        request=request,
        attempt_id=attempt_id,
        identity=_plan_identity(validated_journal),
        status="COMPENSATION_REQUIRED",
        steps=steps,
    )


def reduce_compensation(
    plan: CodexCompensationPlan | CodexNoCompensationPlan,
    outcomes: tuple[CodexCompensationObservation, ...],
) -> CodexCompensationResult:
    """Reduce a complete exact outcome sequence without invoking an effect boundary."""

    validated_plan = _revalidate_plan(plan)
    if isinstance(validated_plan, CodexCompensationBlocked):
        return validated_plan
    validated_outcomes = _revalidate_outcome_sequence(validated_plan, outcomes)
    if isinstance(validated_outcomes, CodexCompensationBlocked):
        return validated_outcomes
    if isinstance(validated_plan, CodexNoCompensationPlan):
        return CodexCompensationNoop(
            status="COMPENSATION_NOT_REQUIRED",
            reasons=(),
            residual_journal=_residual_journal(validated_plan, plugin_cleared=False, marketplace_cleared=False),
        )
    return _reduce_required_plan(validated_plan, validated_outcomes)


def _blocked(reason: CodexCompensationBlockReason) -> CodexCompensationBlocked:
    return CodexCompensationBlocked(status="COMPENSATION_BLOCKED", reason=reason)


def _journal_fields_are_exact(
    journal: CodexRegistrationAttemptJournal,
    request: CodexPreflightRequest,
    attempt_id: CodexRegistrationAttemptId,
) -> bool:
    return (
        type(journal) is CodexRegistrationAttemptJournal
        and type(request) is CodexPreflightRequest
        and type(attempt_id) is CodexRegistrationAttemptId
        and type(journal.request) is CodexPreflightRequest
        and type(journal.attempt_id) is CodexRegistrationAttemptId
        and type(journal.marketplace_state) is CodexAttemptEffectState
        and type(journal.plugin_state) is CodexAttemptEffectState
    )


def _revalidate_current_journal(
    journal: CodexRegistrationAttemptJournal,
    request: CodexPreflightRequest,
    attempt_id: CodexRegistrationAttemptId,
) -> CodexRegistrationAttemptJournal | CodexCompensationBlocked:
    try:
        if not _journal_fields_are_exact(journal, request, attempt_id):
            return _blocked(CodexCompensationBlockReason.JOURNAL_INVALID)
        validated = revalidate_current_attempt_journal(journal, request, attempt_id)
    except (AttributeError, TypeError, ValidationError, ValueError):
        return _blocked(CodexCompensationBlockReason.JOURNAL_INVALID)
    if isinstance(validated, CodexRegistrationRejected):
        return _journal_rejection(validated.reason)
    return validated


def _journal_rejection(reason: CodexRegistrationRejectReason) -> CodexCompensationBlocked:
    if reason is CodexRegistrationRejectReason.JOURNAL_REQUEST_MISMATCH:
        return _blocked(CodexCompensationBlockReason.JOURNAL_REQUEST_MISMATCH)
    if reason is CodexRegistrationRejectReason.JOURNAL_ATTEMPT_MISMATCH:
        return _blocked(CodexCompensationBlockReason.JOURNAL_ATTEMPT_MISMATCH)
    return _blocked(CodexCompensationBlockReason.JOURNAL_INVALID)


def _plan_identity(journal: CodexRegistrationAttemptJournal) -> CodexCompensationPlanIdentity:
    return CodexCompensationPlanIdentity(
        request=journal.request,
        attempt_id=journal.attempt_id,
        marketplace_state=journal.marketplace_state,
        plugin_state=journal.plugin_state,
    )


def _steps_for_journal(journal: CodexRegistrationAttemptJournal) -> tuple[CodexCompensationStep, ...]:
    steps: list[CodexCompensationStep] = []
    if journal.plugin_state in (CodexAttemptEffectState.MAY_EXIST, CodexAttemptEffectState.OWNED):
        steps.append(CodexCompensationStep.REMOVE_PLUGIN)
    if journal.marketplace_state in (CodexAttemptEffectState.MAY_EXIST, CodexAttemptEffectState.OWNED):
        steps.append(CodexCompensationStep.REMOVE_MARKETPLACE)
    if steps:
        steps.extend(_PROOF_STEPS)
    return tuple(steps)


def _plan_fields_are_exact(plan: CodexCompensationPlan | CodexNoCompensationPlan) -> bool:
    return (
        (type(plan) is CodexCompensationPlan or type(plan) is CodexNoCompensationPlan)
        and type(plan.journal) is CodexRegistrationAttemptJournal
        and type(plan.request) is CodexPreflightRequest
        and type(plan.attempt_id) is CodexRegistrationAttemptId
        and type(plan.identity) is CodexCompensationPlanIdentity
        and type(plan.identity.request) is CodexPreflightRequest
        and type(plan.identity.attempt_id) is CodexRegistrationAttemptId
        and type(plan.identity.marketplace_state) is CodexAttemptEffectState
        and type(plan.identity.plugin_state) is CodexAttemptEffectState
        and type(plan.status) is str
        and type(plan.steps) is tuple
        and all(type(step) is CodexCompensationStep for step in plan.steps)
    )


def _revalidate_plan(
    plan: CodexCompensationPlan | CodexNoCompensationPlan,
) -> CodexCompensationPlanResult:
    try:
        if not _plan_fields_are_exact(plan):
            return _blocked(CodexCompensationBlockReason.PLAN_INVALID)
        rebuilt_plan = build_compensation_plan(plan.journal, plan.request, plan.attempt_id)
    except (AttributeError, TypeError, ValidationError, ValueError):
        return _blocked(CodexCompensationBlockReason.PLAN_INVALID)
    if isinstance(rebuilt_plan, CodexCompensationBlocked):
        return rebuilt_plan
    if not _plan_matches_rebuild(rebuilt_plan, plan):
        return _blocked(CodexCompensationBlockReason.PLAN_INVALID)
    return rebuilt_plan


def _plan_matches_rebuild(
    rebuilt_plan: CodexCompensationPlan | CodexNoCompensationPlan,
    supplied_plan: CodexCompensationPlan | CodexNoCompensationPlan,
) -> bool:
    """Compare only exact trusted plan fields after identity-only type admission."""

    if type(rebuilt_plan) is not type(supplied_plan):
        return False
    if rebuilt_plan.status != supplied_plan.status or len(rebuilt_plan.steps) != len(supplied_plan.steps):
        return False
    if any(rebuilt_step is not supplied_step for rebuilt_step, supplied_step in zip(rebuilt_plan.steps, supplied_plan.steps, strict=True)):
        return False
    return (
        rebuilt_plan.journal.model_dump_json(warnings=False) == supplied_plan.journal.model_dump_json(warnings=False)
        and rebuilt_plan.request.model_dump_json(warnings=False) == supplied_plan.request.model_dump_json(warnings=False)
        and rebuilt_plan.attempt_id.model_dump_json(warnings=False) == supplied_plan.attempt_id.model_dump_json(warnings=False)
        and rebuilt_plan.identity.model_dump_json(warnings=False) == supplied_plan.identity.model_dump_json(warnings=False)
    )


def _revalidate_outcome_sequence(
    plan: CodexCompensationPlan | CodexNoCompensationPlan,
    outcomes: tuple[CodexCompensationObservation, ...],
) -> tuple[CodexCompensationObservation, ...] | CodexCompensationBlocked:
    if type(outcomes) is not tuple or len(outcomes) != len(plan.steps):
        return _blocked(CodexCompensationBlockReason.OUTCOME_SEQUENCE_INVALID)
    validated_outcomes: list[CodexCompensationObservation] = []
    for step, outcome in zip(plan.steps, outcomes, strict=True):
        validated_outcome = _revalidate_observation(outcome)
        if isinstance(validated_outcome, CodexCompensationBlocked):
            return validated_outcome
        if not _observation_matches_step(validated_outcome, step):
            return _blocked(CodexCompensationBlockReason.OUTCOME_SEQUENCE_INVALID)
        validated_outcomes.append(validated_outcome)
    return tuple(validated_outcomes)


def _revalidate_observation(
    observation: CodexCompensationObservation,
) -> CodexCompensationObservation | CodexCompensationBlocked:
    try:
        if type(observation) is CodexRemovalConfirmed:
            if type(observation.step) is not CodexCompensationStep or type(observation.status) is not str:
                return _blocked(CodexCompensationBlockReason.OUTCOME_INVALID)
            return CodexRemovalConfirmed(step=observation.step, status=observation.status)
        if type(observation) is CodexRemovalFailed:
            if type(observation.step) is not CodexCompensationStep or type(observation.status) is not str:
                return _blocked(CodexCompensationBlockReason.OUTCOME_INVALID)
            return CodexRemovalFailed(step=observation.step, status=observation.status)
        if type(observation) is CodexPluginListsProof:
            if (
                type(observation.step) is not CodexCompensationStep
                or type(observation.installed) is not CodexProofTruth
                or type(observation.available) is not CodexProofTruth
            ):
                return _blocked(CodexCompensationBlockReason.OUTCOME_INVALID)
            return CodexPluginListsProof(
                step=observation.step,
                installed=observation.installed,
                available=observation.available,
            )
        if type(observation) is CodexInstalledLocationProof:
            if type(observation.step) is not CodexCompensationStep or type(observation.truth) is not CodexProofTruth:
                return _blocked(CodexCompensationBlockReason.OUTCOME_INVALID)
            return CodexInstalledLocationProof(step=observation.step, truth=observation.truth)
        if type(observation) is CodexMarketplaceProof:
            if type(observation.step) is not CodexCompensationStep or type(observation.truth) is not CodexProofTruth:
                return _blocked(CodexCompensationBlockReason.OUTCOME_INVALID)
            return CodexMarketplaceProof(step=observation.step, truth=observation.truth)
    except (AttributeError, TypeError, ValidationError, ValueError):
        return _blocked(CodexCompensationBlockReason.OUTCOME_INVALID)
    return _blocked(CodexCompensationBlockReason.OUTCOME_INVALID)


def _observation_matches_step(observation: CodexCompensationObservation, step: CodexCompensationStep) -> bool:
    if step in (CodexCompensationStep.REMOVE_PLUGIN, CodexCompensationStep.REMOVE_MARKETPLACE):
        return (
            isinstance(observation, (CodexRemovalConfirmed, CodexRemovalFailed))
            and observation.step is step
        )
    if step is CodexCompensationStep.PROVE_PLUGIN_LISTS_ABSENT:
        return isinstance(observation, CodexPluginListsProof) and observation.step is step
    if step is CodexCompensationStep.PROVE_INSTALLED_LOCATION_ABSENT:
        return isinstance(observation, CodexInstalledLocationProof) and observation.step is step
    return isinstance(observation, CodexMarketplaceProof) and observation.step is step


def _reduce_required_plan(
    plan: CodexCompensationPlan,
    outcomes: tuple[CodexCompensationObservation, ...],
) -> CodexCompensationResult:
    plugin_authority = plan.journal.plugin_state in (CodexAttemptEffectState.MAY_EXIST, CodexAttemptEffectState.OWNED)
    marketplace_authority = plan.journal.marketplace_state in (
        CodexAttemptEffectState.MAY_EXIST,
        CodexAttemptEffectState.OWNED,
    )
    reasons: list[CodexCompensationReason] = []
    plugin_lists_absent = False
    installed_location_absent = False
    marketplace_absent = False
    for observation in outcomes:
        if isinstance(observation, CodexRemovalFailed):
            if observation.step is CodexCompensationStep.REMOVE_PLUGIN:
                _append_reason(reasons, CodexCompensationReason.PLUGIN_REMOVAL_DECLARED_FAILURE)
            else:
                _append_reason(reasons, CodexCompensationReason.MARKETPLACE_REMOVAL_DECLARED_FAILURE)
        elif isinstance(observation, CodexPluginListsProof):
            if plugin_authority:
                plugin_lists_absent = (
                    observation.installed is CodexProofTruth.PROVED_ABSENT
                    and observation.available is CodexProofTruth.PROVED_ABSENT
                )
                _append_plugin_list_reasons(reasons, observation)
        elif isinstance(observation, CodexInstalledLocationProof):
            if plugin_authority:
                installed_location_absent = observation.truth is CodexProofTruth.PROVED_ABSENT
                _append_installed_location_reason(reasons, observation.truth)
        elif isinstance(observation, CodexMarketplaceProof) and marketplace_authority:
            marketplace_absent = observation.truth is CodexProofTruth.PROVED_ABSENT
            _append_marketplace_reason(reasons, observation.truth)
    residual_journal = _residual_journal(
        plan,
        plugin_cleared=plugin_authority and plugin_lists_absent and installed_location_absent,
        marketplace_cleared=marketplace_authority and marketplace_absent,
    )
    if reasons:
        return CodexCompensationFailed(
            status="COMPENSATION_FAILED",
            reasons=tuple(reasons),
            residual_journal=residual_journal,
        )
    return CodexCompensated(status="COMPENSATED", reasons=(), residual_journal=residual_journal)


def _residual_journal(
    plan: CodexCompensationPlan | CodexNoCompensationPlan,
    plugin_cleared: bool,
    marketplace_cleared: bool,
) -> CodexCompensationResidualJournal:
    plugin_state = plan.journal.plugin_state
    marketplace_state = plan.journal.marketplace_state
    if plugin_cleared and plugin_state in (CodexAttemptEffectState.MAY_EXIST, CodexAttemptEffectState.OWNED):
        plugin_state = CodexAttemptEffectState.NOT_ATTEMPTED
    if marketplace_cleared and marketplace_state in (CodexAttemptEffectState.MAY_EXIST, CodexAttemptEffectState.OWNED):
        marketplace_state = CodexAttemptEffectState.NOT_ATTEMPTED
    return CodexCompensationResidualJournal(
        request=plan.request,
        attempt_id=plan.attempt_id,
        marketplace_state=marketplace_state,
        plugin_state=plugin_state,
    )


def _append_reason(reasons: list[CodexCompensationReason], reason: CodexCompensationReason) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _append_plugin_list_reasons(
    reasons: list[CodexCompensationReason],
    observation: CodexPluginListsProof,
) -> None:
    if observation.installed is not CodexProofTruth.PROVED_ABSENT:
        _append_reason(reasons, _plugin_installed_reason(observation.installed))
    if observation.available is not CodexProofTruth.PROVED_ABSENT:
        _append_reason(reasons, _plugin_available_reason(observation.available))


def _append_installed_location_reason(
    reasons: list[CodexCompensationReason],
    truth: CodexProofTruth,
) -> None:
    if truth is not CodexProofTruth.PROVED_ABSENT:
        _append_reason(reasons, _installed_location_reason(truth))


def _append_marketplace_reason(
    reasons: list[CodexCompensationReason],
    truth: CodexProofTruth,
) -> None:
    if truth is not CodexProofTruth.PROVED_ABSENT:
        _append_reason(reasons, _marketplace_reason(truth))


def _plugin_installed_reason(truth: CodexProofTruth) -> CodexCompensationReason:
    if truth is CodexProofTruth.RESIDUE:
        return CodexCompensationReason.PLUGIN_INSTALLED_RESIDUE
    if truth is CodexProofTruth.UNPROVED:
        return CodexCompensationReason.PLUGIN_INSTALLED_UNPROVED
    if truth is CodexProofTruth.MALFORMED:
        return CodexCompensationReason.PLUGIN_INSTALLED_MALFORMED
    return CodexCompensationReason.PLUGIN_INSTALLED_MISMATCH


def _plugin_available_reason(truth: CodexProofTruth) -> CodexCompensationReason:
    if truth is CodexProofTruth.RESIDUE:
        return CodexCompensationReason.PLUGIN_AVAILABLE_RESIDUE
    if truth is CodexProofTruth.UNPROVED:
        return CodexCompensationReason.PLUGIN_AVAILABLE_UNPROVED
    if truth is CodexProofTruth.MALFORMED:
        return CodexCompensationReason.PLUGIN_AVAILABLE_MALFORMED
    return CodexCompensationReason.PLUGIN_AVAILABLE_MISMATCH


def _installed_location_reason(truth: CodexProofTruth) -> CodexCompensationReason:
    if truth is CodexProofTruth.RESIDUE:
        return CodexCompensationReason.INSTALLED_LOCATION_RESIDUE
    if truth is CodexProofTruth.UNPROVED:
        return CodexCompensationReason.INSTALLED_LOCATION_UNPROVED
    if truth is CodexProofTruth.MALFORMED:
        return CodexCompensationReason.INSTALLED_LOCATION_MALFORMED
    return CodexCompensationReason.INSTALLED_LOCATION_MISMATCH


def _marketplace_reason(truth: CodexProofTruth) -> CodexCompensationReason:
    if truth is CodexProofTruth.RESIDUE:
        return CodexCompensationReason.MARKETPLACE_RESIDUE
    if truth is CodexProofTruth.UNPROVED:
        return CodexCompensationReason.MARKETPLACE_UNPROVED
    if truth is CodexProofTruth.MALFORMED:
        return CodexCompensationReason.MARKETPLACE_MALFORMED
    return CodexCompensationReason.MARKETPLACE_MISMATCH
