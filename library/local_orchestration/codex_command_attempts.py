"""Pure command-attempt classification for one future Codex registration transaction."""

from __future__ import annotations

from enum import Enum
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, ValidationError

from .codex_registration_contracts import (
    CodexAttemptEffectState,
    CodexRegistrationAttemptId,
    CodexRegistrationAttemptJournal,
    CodexRegistrationRejectReason,
    CodexRegistrationRejected,
    revalidate_current_attempt_journal,
)
from .host_contracts import CodexPreflightRequest


class _StrictModel(BaseModel):
    """Freeze and strictly validate every classifier boundary value."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, revalidate_instances="always")


class CodexCommandTarget(str, Enum):
    """The two finite Codex mutation targets that a later ticket may execute."""

    MARKETPLACE_ADD = "MARKETPLACE_ADD"
    PLUGIN_ADD = "PLUGIN_ADD"


class CodexCommandStartState(str, Enum):
    """Whether the child command is proved absent or has started/ambiguous effects."""

    NOT_STARTED = "NOT_STARTED"
    STARTED = "STARTED"


class CodexPreStartFailureReason(str, Enum):
    INVALID_REQUEST = "INVALID_REQUEST"
    REQUEST_MISMATCH = "REQUEST_MISMATCH"
    EXECUTABLE_UNAVAILABLE = "EXECUTABLE_UNAVAILABLE"
    ACCESS_DENIED = "ACCESS_DENIED"
    GENERIC_LAUNCH_FAILURE = "GENERIC_LAUNCH_FAILURE"


class CodexStartedFailureReason(str, Enum):
    TIMEOUT_AFTER_START = "TIMEOUT_AFTER_START"
    NONZERO_EXIT = "NONZERO_EXIT"
    WAIT_FAILED_AFTER_START = "WAIT_FAILED_AFTER_START"
    TERMINATION_FAILED = "TERMINATION_FAILED"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"


class CodexPreStartFailure(_StrictModel):
    """One declared pre-start failure with no possible host effect."""

    target: CodexCommandTarget
    reason: CodexPreStartFailureReason
    start_state: Literal[CodexCommandStartState.NOT_STARTED]


class CodexStartedFailure(_StrictModel):
    """One declared started/ambiguous failure with only limited cleanup authority."""

    target: CodexCommandTarget
    reason: CodexStartedFailureReason
    start_state: Literal[CodexCommandStartState.STARTED]


class CodexMarketplaceAddConfirmed(_StrictModel):
    """A strict marketplace confirmation, distinct from a plugin confirmation."""

    target: Literal[CodexCommandTarget.MARKETPLACE_ADD]
    start_state: Literal[CodexCommandStartState.STARTED]
    already_added: bool


class CodexPluginAddConfirmed(_StrictModel):
    """A strict plugin confirmation with no caller-manufactured final authority."""

    target: Literal[CodexCommandTarget.PLUGIN_ADD]
    start_state: Literal[CodexCommandStartState.STARTED]


CodexCommandObservation: TypeAlias = (
    CodexPreStartFailure | CodexStartedFailure | CodexMarketplaceAddConfirmed | CodexPluginAddConfirmed
)


class CodexCommandClassificationRejectReason(str, Enum):
    INVALID_OBSERVATION = "INVALID_OBSERVATION"
    INVALID_SEQUENCE = "INVALID_SEQUENCE"
    JOURNAL_INVALID = "JOURNAL_INVALID"
    JOURNAL_REQUEST_MISMATCH = "JOURNAL_REQUEST_MISMATCH"
    JOURNAL_ATTEMPT_MISMATCH = "JOURNAL_ATTEMPT_MISMATCH"


class CodexCommandClassificationRejected(_StrictModel):
    """A finite classification failure without raw command or exception data."""

    status: Literal["CLASSIFICATION_BLOCKED"] = "CLASSIFICATION_BLOCKED"
    reason: CodexCommandClassificationRejectReason


CodexCommandClassificationResult: TypeAlias = CodexRegistrationAttemptJournal | CodexCommandClassificationRejected


def classify_command_attempt(
    observation: CodexCommandObservation,
    journal: CodexRegistrationAttemptJournal,
    request: CodexPreflightRequest,
    attempt_id: CodexRegistrationAttemptId,
) -> CodexCommandClassificationResult:
    """Classify one declared result without executing or proving a host command."""

    validated_journal = revalidate_current_attempt_journal(journal, request, attempt_id)
    if isinstance(validated_journal, CodexRegistrationRejected):
        return _journal_rejection(validated_journal.reason)
    validated_observation = _revalidate_observation(observation)
    if isinstance(validated_observation, CodexCommandClassificationRejected):
        return validated_observation
    if not _is_admitted(validated_observation.target, validated_journal):
        return CodexCommandClassificationRejected(reason=CodexCommandClassificationRejectReason.INVALID_SEQUENCE)
    return _transition(validated_observation, validated_journal)


def _journal_rejection(reason: CodexRegistrationRejectReason) -> CodexCommandClassificationRejected:
    if reason is CodexRegistrationRejectReason.JOURNAL_REQUEST_MISMATCH:
        return CodexCommandClassificationRejected(
            reason=CodexCommandClassificationRejectReason.JOURNAL_REQUEST_MISMATCH
        )
    if reason is CodexRegistrationRejectReason.JOURNAL_ATTEMPT_MISMATCH:
        return CodexCommandClassificationRejected(
            reason=CodexCommandClassificationRejectReason.JOURNAL_ATTEMPT_MISMATCH
        )
    return CodexCommandClassificationRejected(reason=CodexCommandClassificationRejectReason.JOURNAL_INVALID)


def _pre_start_fields_are_exact(observation: CodexPreStartFailure) -> bool:
    return (
        type(observation.target) is CodexCommandTarget
        and type(observation.reason) is CodexPreStartFailureReason
        and observation.start_state is CodexCommandStartState.NOT_STARTED
    )


def _started_failure_fields_are_exact(observation: CodexStartedFailure) -> bool:
    return (
        type(observation.target) is CodexCommandTarget
        and type(observation.reason) is CodexStartedFailureReason
        and observation.start_state is CodexCommandStartState.STARTED
    )


def _marketplace_confirmation_fields_are_exact(observation: CodexMarketplaceAddConfirmed) -> bool:
    return (
        observation.target is CodexCommandTarget.MARKETPLACE_ADD
        and observation.start_state is CodexCommandStartState.STARTED
        and type(observation.already_added) is bool
    )


def _plugin_confirmation_fields_are_exact(observation: CodexPluginAddConfirmed) -> bool:
    return (
        observation.target is CodexCommandTarget.PLUGIN_ADD
        and observation.start_state is CodexCommandStartState.STARTED
    )


def _revalidate_observation(
    observation: CodexCommandObservation,
) -> CodexCommandObservation | CodexCommandClassificationRejected:
    try:
        if isinstance(observation, CodexPreStartFailure):
            if not _pre_start_fields_are_exact(observation):
                return CodexCommandClassificationRejected(
                    reason=CodexCommandClassificationRejectReason.INVALID_OBSERVATION
                )
            return CodexPreStartFailure.model_validate(
                {
                    "target": observation.target,
                    "reason": observation.reason,
                    "start_state": observation.start_state,
                }
            )
        if isinstance(observation, CodexStartedFailure):
            if not _started_failure_fields_are_exact(observation):
                return CodexCommandClassificationRejected(
                    reason=CodexCommandClassificationRejectReason.INVALID_OBSERVATION
                )
            return CodexStartedFailure.model_validate(
                {
                    "target": observation.target,
                    "reason": observation.reason,
                    "start_state": observation.start_state,
                }
            )
        if isinstance(observation, CodexMarketplaceAddConfirmed):
            if not _marketplace_confirmation_fields_are_exact(observation):
                return CodexCommandClassificationRejected(
                    reason=CodexCommandClassificationRejectReason.INVALID_OBSERVATION
                )
            return CodexMarketplaceAddConfirmed.model_validate(
                {
                    "target": observation.target,
                    "start_state": observation.start_state,
                    "already_added": observation.already_added,
                }
            )
        if isinstance(observation, CodexPluginAddConfirmed):
            if not _plugin_confirmation_fields_are_exact(observation):
                return CodexCommandClassificationRejected(
                    reason=CodexCommandClassificationRejectReason.INVALID_OBSERVATION
                )
            return CodexPluginAddConfirmed.model_validate(
                {
                    "target": observation.target,
                    "start_state": observation.start_state,
                }
            )
    except (AttributeError, TypeError, ValidationError, ValueError):
        return CodexCommandClassificationRejected(reason=CodexCommandClassificationRejectReason.INVALID_OBSERVATION)
    return CodexCommandClassificationRejected(reason=CodexCommandClassificationRejectReason.INVALID_OBSERVATION)


def _is_admitted(target: CodexCommandTarget, journal: CodexRegistrationAttemptJournal) -> bool:
    state_pair = (journal.marketplace_state, journal.plugin_state)
    if target is CodexCommandTarget.MARKETPLACE_ADD:
        return state_pair == (CodexAttemptEffectState.NOT_ATTEMPTED, CodexAttemptEffectState.NOT_ATTEMPTED)
    return state_pair == (CodexAttemptEffectState.OWNED, CodexAttemptEffectState.NOT_ATTEMPTED)


def _transition(
    observation: CodexCommandObservation,
    journal: CodexRegistrationAttemptJournal,
) -> CodexRegistrationAttemptJournal:
    if isinstance(observation, CodexPreStartFailure):
        return journal
    if isinstance(observation, CodexStartedFailure):
        if observation.target is CodexCommandTarget.MARKETPLACE_ADD:
            return _journal_with_states(
                journal,
                CodexAttemptEffectState.MAY_EXIST,
                CodexAttemptEffectState.NOT_ATTEMPTED,
            )
        return _journal_with_states(
            journal,
            CodexAttemptEffectState.OWNED,
            CodexAttemptEffectState.MAY_EXIST,
        )
    if isinstance(observation, CodexMarketplaceAddConfirmed):
        if observation.already_added:
            return _journal_with_states(
                journal,
                CodexAttemptEffectState.PREEXISTING,
                CodexAttemptEffectState.NOT_ATTEMPTED,
            )
        return _journal_with_states(
            journal,
            CodexAttemptEffectState.OWNED,
            CodexAttemptEffectState.NOT_ATTEMPTED,
        )
    return _journal_with_states(
        journal,
        CodexAttemptEffectState.OWNED,
        CodexAttemptEffectState.OWNED,
    )


def _journal_with_states(
    journal: CodexRegistrationAttemptJournal,
    marketplace_state: CodexAttemptEffectState,
    plugin_state: CodexAttemptEffectState,
) -> CodexRegistrationAttemptJournal:
    return CodexRegistrationAttemptJournal(
        request=journal.request,
        attempt_id=journal.attempt_id,
        marketplace_state=marketplace_state,
        plugin_state=plugin_state,
    )
