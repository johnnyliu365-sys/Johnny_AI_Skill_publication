"""Pure forward reduction for one exact current Codex registration attempt."""

from __future__ import annotations

from enum import Enum
from typing import Literal, TypeAlias, cast

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from .codex_command_attempts import (
    CodexCommandClassificationRejected,
    CodexCommandObservation,
    CodexCommandStartState,
    CodexCommandTarget,
    CodexMarketplaceAddConfirmed,
    CodexPluginAddConfirmed,
    CodexPreStartFailure,
    CodexStartedFailure,
    CodexStartedFailureReason,
    classify_command_attempt,
)
from .codex_compensation_reducer import (
    CodexCompensationPlan,
    CodexCompensationPlanIdentity,
    build_compensation_plan,
)
from .codex_registration_contracts import (
    CodexAttemptEffectState,
    CodexMarketplaceAddObservation,
    CodexPluginAddObservation,
    CodexPluginId,
    CodexRegistrationAttemptId,
    CodexRegistrationAttemptJournal,
    CodexRegistrationProofRequest,
    CodexRegistrationRejected,
    revalidate_current_attempt_journal,
)
from .codex_registration_port import (
    CodexFreshPreflightAccepted,
    CodexFreshPreflightRejected,
    CodexMarketplaceAddSucceeded,
    CodexPluginAddSucceeded,
    CodexRegistrationCommandFailed,
    CodexRegistrationPortRequest,
    CodexRegistrationPortValueRejectReason,
    CodexRegistrationPortValueRejected,
    revalidate_fresh_preflight_result,
    revalidate_marketplace_add_result,
    revalidate_plugin_add_result,
    revalidate_registration_port_request,
)
from .host_contracts import CodexPreflightRequest


class _StrictModel(BaseModel):
    """Frozen, strict values at the pure reducer boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, revalidate_instances="always")


class CodexRegistrationBlockReason(str, Enum):
    """Finite metadata-only reasons that never carry raw caller values."""

    INVALID_REQUEST = "INVALID_REQUEST"
    INVALID_STATE = "INVALID_STATE"
    FRESH_PREFLIGHT_INVALID = "FRESH_PREFLIGHT_INVALID"
    FRESH_PREFLIGHT_REJECTED = "FRESH_PREFLIGHT_REJECTED"
    MARKETPLACE_PREEXISTING = "MARKETPLACE_PREEXISTING"
    MARKETPLACE_ADD_NOT_STARTED = "MARKETPLACE_ADD_NOT_STARTED"
    CLASSIFICATION_INVALID = "CLASSIFICATION_INVALID"
    COMPENSATION_PLAN_INVALID = "COMPENSATION_PLAN_INVALID"
    PROOF_REQUEST_INVALID = "PROOF_REQUEST_INVALID"


class _PendingState(_StrictModel):
    request: CodexRegistrationPortRequest
    journal: CodexRegistrationAttemptJournal


class CodexFreshPreflightPending(_PendingState):
    status: Literal["FRESH_PREFLIGHT_PENDING"] = "FRESH_PREFLIGHT_PENDING"


class CodexMarketplaceAddPending(_PendingState):
    status: Literal["MARKETPLACE_ADD_PENDING"] = "MARKETPLACE_ADD_PENDING"


class CodexPluginAddPending(_PendingState):
    status: Literal["PLUGIN_ADD_PENDING"] = "PLUGIN_ADD_PENDING"
    marketplace_observation: CodexMarketplaceAddObservation


CodexRegistrationPending: TypeAlias = (
    CodexFreshPreflightPending | CodexMarketplaceAddPending | CodexPluginAddPending
)


class CodexRegistrationProofRequired(_StrictModel):
    status: Literal["PROOF_REQUIRED"] = "PROOF_REQUIRED"
    journal: CodexRegistrationAttemptJournal
    proof_request: CodexRegistrationProofRequest


class CodexRegistrationCompensationRequired(_StrictModel):
    """A terminal, recursively request-bound compensation decision."""

    status: Literal["COMPENSATION_REQUIRED"] = "COMPENSATION_REQUIRED"
    request: CodexRegistrationPortRequest
    journal: CodexRegistrationAttemptJournal
    plan: CodexCompensationPlan

    @model_validator(mode="after")
    def exact_compensation_context(self) -> CodexRegistrationCompensationRequired:
        _rebuild_compensation_context(self.request, self.journal, self.plan)
        return self


class CodexRegistrationBlocked(_StrictModel):
    status: Literal["REGISTRATION_BLOCKED"] = "REGISTRATION_BLOCKED"
    reason: CodexRegistrationBlockReason


CodexRegistrationReduction: TypeAlias = (
    CodexRegistrationPending
    | CodexRegistrationProofRequired
    | CodexRegistrationCompensationRequired
    | CodexRegistrationBlocked
)


def begin_codex_registration(value: object) -> CodexRegistrationReduction:
    """Begin one pure current attempt with no effect invocation."""

    request = revalidate_registration_port_request(value)
    if isinstance(request, CodexRegistrationPortValueRejected):
        return _blocked(CodexRegistrationBlockReason.INVALID_REQUEST)
    try:
        journal = CodexRegistrationAttemptJournal(
            request=request.preflight,
            attempt_id=request.attempt_id,
            marketplace_state=CodexAttemptEffectState.NOT_ATTEMPTED,
            plugin_state=CodexAttemptEffectState.NOT_ATTEMPTED,
        )
    except (AttributeError, TypeError, ValidationError, ValueError):
        return _blocked(CodexRegistrationBlockReason.INVALID_REQUEST)
    return _fresh_pending(request, journal)


def advance_codex_registration(state: object, result: object) -> CodexRegistrationReduction:
    """Reduce one exact phase result without calling any operation."""

    current = _revalidate_pending(state)
    if isinstance(current, CodexRegistrationBlocked):
        return current
    if isinstance(current, CodexFreshPreflightPending):
        return _advance_fresh_preflight(current, result)
    if isinstance(current, CodexMarketplaceAddPending):
        return _advance_marketplace_add(current, result)
    return _advance_plugin_add(current, result)


def _fresh_pending(
    request: CodexRegistrationPortRequest,
    journal: CodexRegistrationAttemptJournal,
) -> CodexFreshPreflightPending:
    return CodexFreshPreflightPending(request=request, journal=journal)


def _marketplace_pending(
    request: CodexRegistrationPortRequest,
    journal: CodexRegistrationAttemptJournal,
) -> CodexMarketplaceAddPending:
    return CodexMarketplaceAddPending(request=request, journal=journal)


def _plugin_pending(
    request: CodexRegistrationPortRequest,
    journal: CodexRegistrationAttemptJournal,
    observation: CodexMarketplaceAddObservation,
) -> CodexPluginAddPending:
    return CodexPluginAddPending(
        request=request,
        journal=journal,
        marketplace_observation=observation,
    )


def _revalidate_pending(value: object) -> CodexRegistrationPending | CodexRegistrationBlocked:
    if type(value) not in (CodexFreshPreflightPending, CodexMarketplaceAddPending, CodexPluginAddPending):
        return _blocked(CodexRegistrationBlockReason.INVALID_STATE)
    state = cast(CodexRegistrationPending, value)
    try:
        status_value: object = state.status
        request_value: object = state.request
        journal_value: object = state.journal
        request = revalidate_registration_port_request(request_value)
    except (AttributeError, TypeError, ValidationError, ValueError):
        return _blocked(CodexRegistrationBlockReason.INVALID_STATE)
    if isinstance(request, CodexRegistrationPortValueRejected):
        return _blocked(CodexRegistrationBlockReason.INVALID_STATE)
    journal = _revalidate_pending_journal(journal_value, request)
    if isinstance(journal, CodexRegistrationBlocked):
        return journal
    pair = (journal.marketplace_state, journal.plugin_state)
    if type(value) is CodexFreshPreflightPending:
        if status_value != "FRESH_PREFLIGHT_PENDING" or pair != (
            CodexAttemptEffectState.NOT_ATTEMPTED,
            CodexAttemptEffectState.NOT_ATTEMPTED,
        ):
            return _blocked(CodexRegistrationBlockReason.INVALID_STATE)
        return _fresh_pending(request, journal)
    if type(value) is CodexMarketplaceAddPending:
        if status_value != "MARKETPLACE_ADD_PENDING" or pair != (
            CodexAttemptEffectState.NOT_ATTEMPTED,
            CodexAttemptEffectState.NOT_ATTEMPTED,
        ):
            return _blocked(CodexRegistrationBlockReason.INVALID_STATE)
        return _marketplace_pending(request, journal)
    plugin_state = cast(CodexPluginAddPending, value)
    if status_value != "PLUGIN_ADD_PENDING" or pair != (
        CodexAttemptEffectState.OWNED,
        CodexAttemptEffectState.NOT_ATTEMPTED,
    ):
        return _blocked(CodexRegistrationBlockReason.INVALID_STATE)
    try:
        observation_value: object = plugin_state.marketplace_observation
    except AttributeError:
        return _blocked(CodexRegistrationBlockReason.INVALID_STATE)
    observation = _revalidate_carried_marketplace_observation(observation_value, request)
    if isinstance(observation, CodexRegistrationBlocked):
        return observation
    return _plugin_pending(request, journal, observation)


def _revalidate_pending_journal(
    value: object,
    request: CodexRegistrationPortRequest,
) -> CodexRegistrationAttemptJournal | CodexRegistrationBlocked:
    if type(value) is not CodexRegistrationAttemptJournal:
        return _blocked(CodexRegistrationBlockReason.INVALID_STATE)
    journal = value
    try:
        if (
            type(journal.request) is not type(request.preflight)
            or type(journal.attempt_id) is not type(request.attempt_id)
            or type(journal.marketplace_state) is not CodexAttemptEffectState
            or type(journal.plugin_state) is not CodexAttemptEffectState
        ):
            return _blocked(CodexRegistrationBlockReason.INVALID_STATE)
        request_probe = CodexRegistrationPortRequest.model_construct(
            preflight=journal.request,
            attempt_id=journal.attempt_id,
            expected_version=request.expected_version,
            source_locator=request.source_locator,
            installed_locator=request.installed_locator,
            digest=request.digest,
            expected_auth_policy=request.expected_auth_policy,
            expected_plugin_id=request.expected_plugin_id,
        )
        validated_probe = revalidate_registration_port_request(request_probe)
        if isinstance(validated_probe, CodexRegistrationPortValueRejected):
            return _blocked(CodexRegistrationBlockReason.INVALID_STATE)
        validated = revalidate_current_attempt_journal(journal, request.preflight, request.attempt_id)
    except (AttributeError, TypeError, ValidationError, ValueError):
        return _blocked(CodexRegistrationBlockReason.INVALID_STATE)
    if isinstance(validated, CodexRegistrationRejected):
        return _blocked(CodexRegistrationBlockReason.INVALID_STATE)
    return validated


def _revalidate_carried_marketplace_observation(
    value: object,
    request: CodexRegistrationPortRequest,
) -> CodexMarketplaceAddObservation | CodexRegistrationBlocked:
    try:
        candidate = CodexMarketplaceAddSucceeded.model_construct(
            request=request,
            confirmed=CodexMarketplaceAddConfirmed(
                target=CodexCommandTarget.MARKETPLACE_ADD,
                start_state=CodexCommandStartState.STARTED,
                already_added=False,
            ),
            observation=value,
        )
        rebuilt = revalidate_marketplace_add_result(candidate, request)
    except (AttributeError, TypeError, ValidationError, ValueError):
        return _blocked(CodexRegistrationBlockReason.INVALID_STATE)
    if type(rebuilt) is not CodexMarketplaceAddSucceeded or rebuilt.confirmed.already_added:
        return _blocked(CodexRegistrationBlockReason.INVALID_STATE)
    return rebuilt.observation


def _advance_fresh_preflight(
    state: CodexFreshPreflightPending,
    result: object,
) -> CodexRegistrationReduction:
    validated = revalidate_fresh_preflight_result(result, state.request)
    if isinstance(validated, CodexRegistrationPortValueRejected):
        return _blocked(CodexRegistrationBlockReason.FRESH_PREFLIGHT_INVALID)
    if isinstance(validated, CodexFreshPreflightRejected):
        return _blocked(CodexRegistrationBlockReason.FRESH_PREFLIGHT_REJECTED)
    if type(validated) is not CodexFreshPreflightAccepted:
        return _blocked(CodexRegistrationBlockReason.FRESH_PREFLIGHT_INVALID)
    return _marketplace_pending(state.request, state.journal)


def _advance_marketplace_add(
    state: CodexMarketplaceAddPending,
    result: object,
) -> CodexRegistrationReduction:
    validated = revalidate_marketplace_add_result(result, state.request)
    if isinstance(validated, CodexRegistrationPortValueRejected):
        return _compensate_untrusted_add(state.request, state.journal, CodexCommandTarget.MARKETPLACE_ADD, validated.reason)
    observation: CodexCommandObservation
    if isinstance(validated, CodexMarketplaceAddSucceeded):
        observation = validated.confirmed
    else:
        observation = validated.failure
    journal = _classify_add(observation, state.request, state.journal)
    if isinstance(journal, CodexRegistrationBlocked):
        return journal
    if isinstance(validated, CodexMarketplaceAddSucceeded):
        if validated.confirmed.already_added:
            return _blocked(CodexRegistrationBlockReason.MARKETPLACE_PREEXISTING)
        return _plugin_pending(state.request, journal, validated.observation)
    if isinstance(validated.failure, CodexPreStartFailure):
        return _blocked(CodexRegistrationBlockReason.MARKETPLACE_ADD_NOT_STARTED)
    return _compensation_required(state.request, journal)


def _advance_plugin_add(
    state: CodexPluginAddPending,
    result: object,
) -> CodexRegistrationReduction:
    validated = revalidate_plugin_add_result(result, state.request)
    if isinstance(validated, CodexRegistrationPortValueRejected):
        return _compensate_untrusted_add(state.request, state.journal, CodexCommandTarget.PLUGIN_ADD, validated.reason)
    observation: CodexCommandObservation
    if isinstance(validated, CodexPluginAddSucceeded):
        observation = validated.confirmed
    else:
        observation = validated.failure
    journal = _classify_add(observation, state.request, state.journal)
    if isinstance(journal, CodexRegistrationBlocked):
        return journal
    if isinstance(validated, CodexRegistrationCommandFailed):
        return _compensation_required(state.request, journal)
    return _proof_required(state, journal, validated.observation)


def _classify_add(
    observation: CodexCommandObservation,
    request: CodexRegistrationPortRequest,
    journal: CodexRegistrationAttemptJournal,
) -> CodexRegistrationAttemptJournal | CodexRegistrationBlocked:
    classified = classify_command_attempt(observation, journal, request.preflight, request.attempt_id)
    if isinstance(classified, CodexCommandClassificationRejected):
        return _blocked(CodexRegistrationBlockReason.CLASSIFICATION_INVALID)
    return classified


def _compensate_untrusted_add(
    request: CodexRegistrationPortRequest,
    journal: CodexRegistrationAttemptJournal,
    target: CodexCommandTarget,
    reason: CodexRegistrationPortValueRejectReason,
) -> CodexRegistrationReduction:
    failure_reason = (
        CodexStartedFailureReason.IDENTITY_MISMATCH
        if reason
        in (
            CodexRegistrationPortValueRejectReason.REQUEST_MISMATCH,
            CodexRegistrationPortValueRejectReason.TARGET_MISMATCH,
            CodexRegistrationPortValueRejectReason.VERSION_MISMATCH,
        )
        else CodexStartedFailureReason.MALFORMED_RESPONSE
    )
    synthetic = CodexStartedFailure(
        target=target,
        reason=failure_reason,
        start_state=CodexCommandStartState.STARTED,
    )
    classified = _classify_add(synthetic, request, journal)
    if isinstance(classified, CodexRegistrationBlocked):
        return classified
    return _compensation_required(request, classified)


def _compensation_required(
    request: CodexRegistrationPortRequest,
    journal: CodexRegistrationAttemptJournal,
) -> CodexRegistrationReduction:
    plan = build_compensation_plan(journal, request.preflight, request.attempt_id)
    if type(plan) is not CodexCompensationPlan:
        return _blocked(CodexRegistrationBlockReason.COMPENSATION_PLAN_INVALID)
    try:
        context_request, context_journal, context_plan = _rebuild_compensation_context(request, journal, plan)
        return CodexRegistrationCompensationRequired(
            request=context_request,
            journal=context_journal,
            plan=context_plan,
        )
    except (AttributeError, TypeError, ValidationError, ValueError):
        return _blocked(CodexRegistrationBlockReason.COMPENSATION_PLAN_INVALID)


def _rebuild_compensation_context(
    request_value: object,
    journal_value: object,
    plan_value: object,
) -> tuple[CodexRegistrationPortRequest, CodexRegistrationAttemptJournal, CodexCompensationPlan]:
    """Rebuild only one exact request, journal, and compensation plan context."""

    request = revalidate_registration_port_request(request_value)
    if isinstance(request, CodexRegistrationPortValueRejected):
        raise ValueError("compensation request is invalid")
    journal = _revalidate_pending_journal(journal_value, request)
    if isinstance(journal, CodexRegistrationBlocked) or not _journal_matches_request(journal, request):
        raise ValueError("compensation journal is invalid")
    rebuilt_plan = build_compensation_plan(journal, request.preflight, request.attempt_id)
    if type(rebuilt_plan) is not CodexCompensationPlan:
        raise ValueError("compensation plan is invalid")
    if type(plan_value) is not CodexCompensationPlan:
        raise ValueError("compensation plan is invalid")
    if not _plan_matches_rebuild(rebuilt_plan, plan_value):
        raise ValueError("compensation plan is invalid")
    return request, journal, rebuilt_plan


def _journal_matches_request(
    journal: CodexRegistrationAttemptJournal,
    request: CodexRegistrationPortRequest,
) -> bool:
    """Compare only rebuilt primitive request and journal fields."""

    try:
        if (
            type(journal) is not CodexRegistrationAttemptJournal
            or type(journal.request) is not type(request.preflight)
            or type(journal.attempt_id) is not type(request.attempt_id)
            or type(journal.marketplace_state) is not CodexAttemptEffectState
            or type(journal.plugin_state) is not CodexAttemptEffectState
        ):
            return False
        return _preflights_match(journal.request, request.preflight) and _attempts_match(
            journal.attempt_id,
            request.attempt_id,
        )
    except AttributeError:
        return False


def _preflights_match(left: CodexPreflightRequest, right: CodexPreflightRequest) -> bool:
    """Compare exact built-in fields only after concrete-type admission."""

    if type(left) is not type(right):
        return False
    try:
        left_installation = left.installation_id
        right_installation = right.installation_id
        left_root = left.root
        right_root = right.root
        left_marketplace = left.marketplace
        right_marketplace = right.marketplace
        left_plugin = left.plugin
        right_plugin = right.plugin
        left_source = left.marketplace_source
        right_source = right.marketplace_source
        if (
            type(left_installation) is not type(right_installation)
            or type(left_root) is not type(right_root)
            or type(left_marketplace) is not type(right_marketplace)
            or type(left_plugin) is not type(right_plugin)
            or type(left_source) is not type(right_source)
        ):
            return False
        left_values = (
            left_installation.value,
            left_root.value,
            left_marketplace.value,
            left_plugin.value,
            left_source.value,
        )
        right_values = (
            right_installation.value,
            right_root.value,
            right_marketplace.value,
            right_plugin.value,
            right_source.value,
        )
    except AttributeError:
        return False
    if not all(type(value) is str for value in (*left_values, *right_values)):
        return False
    return left_values == right_values


def _attempts_match(left: CodexRegistrationAttemptId, right: CodexRegistrationAttemptId) -> bool:
    """Compare validated attempt values without model equality."""

    if type(left) is not type(right):
        return False
    try:
        left_value = left.value
        right_value = right.value
    except AttributeError:
        return False
    return type(left_value) is str and type(right_value) is str and left_value == right_value


def _journals_match(
    left: CodexRegistrationAttemptJournal,
    right: CodexRegistrationAttemptJournal,
) -> bool:
    """Compare every rebuilt journal field without Pydantic equality or serialization."""

    try:
        if (
            type(left) is not CodexRegistrationAttemptJournal
            or type(right) is not CodexRegistrationAttemptJournal
            or type(left.marketplace_state) is not CodexAttemptEffectState
            or type(right.marketplace_state) is not CodexAttemptEffectState
            or type(left.plugin_state) is not CodexAttemptEffectState
            or type(right.plugin_state) is not CodexAttemptEffectState
        ):
            return False
        return (
            _preflights_match(left.request, right.request)
            and _attempts_match(left.attempt_id, right.attempt_id)
            and left.marketplace_state is right.marketplace_state
            and left.plugin_state is right.plugin_state
        )
    except AttributeError:
        return False


def _plan_identity_matches(
    left: CodexCompensationPlanIdentity,
    right: CodexCompensationPlanIdentity,
) -> bool:
    """Compare only exact fields in the immutable compensation identity."""

    try:
        if (
            type(left) is not CodexCompensationPlanIdentity
            or type(right) is not CodexCompensationPlanIdentity
            or type(left.marketplace_state) is not CodexAttemptEffectState
            or type(right.marketplace_state) is not CodexAttemptEffectState
            or type(left.plugin_state) is not CodexAttemptEffectState
            or type(right.plugin_state) is not CodexAttemptEffectState
        ):
            return False
        return (
            _preflights_match(left.request, right.request)
            and _attempts_match(left.attempt_id, right.attempt_id)
            and left.marketplace_state is right.marketplace_state
            and left.plugin_state is right.plugin_state
        )
    except AttributeError:
        return False


def _plan_matches_rebuild(
    rebuilt: CodexCompensationPlan,
    supplied: CodexCompensationPlan,
) -> bool:
    """Require every supplied plan field to equal the sole rebuilt plan."""

    try:
        if (
            type(rebuilt) is not CodexCompensationPlan
            or type(supplied) is not CodexCompensationPlan
            or type(rebuilt.status) is not str
            or type(supplied.status) is not str
            or type(rebuilt.steps) is not tuple
            or type(supplied.steps) is not tuple
            or type(rebuilt.journal) is not CodexRegistrationAttemptJournal
            or type(supplied.journal) is not CodexRegistrationAttemptJournal
            or type(rebuilt.identity) is not CodexCompensationPlanIdentity
            or type(supplied.identity) is not CodexCompensationPlanIdentity
        ):
            return False
        if len(rebuilt.steps) != len(supplied.steps):
            return False
        if any(
            type(rebuilt_step) is not type(supplied_step) or rebuilt_step is not supplied_step
            for rebuilt_step, supplied_step in zip(rebuilt.steps, supplied.steps, strict=True)
        ):
            return False
        return (
            rebuilt.status == supplied.status
            and _journals_match(rebuilt.journal, supplied.journal)
            and _preflights_match(rebuilt.request, supplied.request)
            and _attempts_match(rebuilt.attempt_id, supplied.attempt_id)
            and _plan_identity_matches(rebuilt.identity, supplied.identity)
        )
    except AttributeError:
        return False


def _proof_required(
    state: CodexPluginAddPending,
    journal: CodexRegistrationAttemptJournal,
    observation: CodexPluginAddObservation,
) -> CodexRegistrationReduction:
    try:
        exact_observation = CodexPluginAddObservation(
            plugin_id=CodexPluginId(value=state.request.expected_plugin_id.value),
            name=observation.name,
            marketplace_name=observation.marketplace_name,
            version=observation.version,
            installed_path=observation.installed_path,
            auth_policy=observation.auth_policy,
        )
        proof_request = CodexRegistrationProofRequest(
            preflight=state.request.preflight,
            version=state.request.expected_version,
            marketplace_observation=state.marketplace_observation,
            plugin_observation=exact_observation,
            source_locator=state.request.source_locator,
            installed_locator=state.request.installed_locator,
            digest=state.request.digest,
            expected_auth_policy=state.request.expected_auth_policy,
        )
    except (AttributeError, TypeError, ValidationError, ValueError):
        return _blocked(CodexRegistrationBlockReason.PROOF_REQUEST_INVALID)
    return CodexRegistrationProofRequired(journal=journal, proof_request=proof_request)


def _blocked(reason: CodexRegistrationBlockReason) -> CodexRegistrationBlocked:
    return CodexRegistrationBlocked(reason=reason)
