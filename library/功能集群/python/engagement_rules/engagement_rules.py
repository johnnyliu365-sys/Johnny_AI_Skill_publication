"""Pure configurable eligibility, progress and reward-permission rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias


@dataclass(frozen=True, slots=True)
class EngagementPolicyId:
    """A safe local identifier for one reusable engagement policy."""

    value: str

    def __post_init__(self) -> None:
        _require_safe_identifier(
            value=self.value,
            name="engagement policy identifier",
            maximum_length=64,
        )


@dataclass(frozen=True, slots=True)
class EventId:
    """A safe stable key used to prevent duplicate local rule evaluation."""

    value: str

    def __post_init__(self) -> None:
        _require_safe_identifier(
            value=self.value,
            name="engagement event identifier",
            maximum_length=128,
        )


@dataclass(frozen=True, slots=True)
class UnknownEventCode:
    """A typed safe code retained only to reject an unsupported input event."""

    value: str

    def __post_init__(self) -> None:
        _require_safe_identifier(
            value=self.value,
            name="unknown engagement event code",
            maximum_length=64,
        )


@dataclass(frozen=True, slots=True)
class QualificationRequirement:
    """The number of qualification events required before progress is allowed."""

    value: int

    def __post_init__(self) -> None:
        _require_positive_limit(
            value=self.value,
            name="qualification requirement",
        )


@dataclass(frozen=True, slots=True)
class ProgressTarget:
    """The number of progress events required before reward permission is allowed."""

    value: int

    def __post_init__(self) -> None:
        _require_positive_limit(value=self.value, name="progress target")


@dataclass(frozen=True, slots=True)
class RewardCap:
    """The maximum number of local reward permissions a policy may return."""

    value: int

    def __post_init__(self) -> None:
        _require_positive_limit(value=self.value, name="reward cap")


class EventKind(str, Enum):
    """Generic engagement event roles without health, member or point semantics."""

    QUALIFICATION = "qualification"
    PROGRESS = "progress"
    REWARD_REQUEST = "reward_request"


class EngagementAction(str, Enum):
    """Explainable accepted actions emitted by this pure local evaluator."""

    QUALIFICATION_RECORDED = "qualification_recorded"
    RECOMMENDATION_ELIGIBLE = "recommendation_eligible"
    PROGRESS_RECORDED = "progress_recorded"
    PROGRESS_TARGET_REACHED = "progress_target_reached"
    REWARD_PERMITTED = "reward_permitted"


class EngagementRejectionReason(str, Enum):
    """Finite fail-closed outcomes for unsupported or unsafe rule evaluation."""

    UNKNOWN_POLICY = "unknown_policy"
    UNKNOWN_EVENT = "unknown_event"
    STATE_POLICY_MISMATCH = "state_policy_mismatch"
    DUPLICATE_EVENT = "duplicate_event"
    NOT_RECOMMENDATION_ELIGIBLE = "not_recommendation_eligible"
    ALREADY_RECOMMENDATION_ELIGIBLE = "already_recommendation_eligible"
    INVALID_STATE = "invalid_state"
    PROGRESS_TARGET_REACHED = "progress_target_reached"
    PROGRESS_TARGET_NOT_REACHED = "progress_target_not_reached"
    REWARD_CAP_REACHED = "reward_cap_reached"


@dataclass(frozen=True, slots=True)
class EngagementPolicy:
    """A configurable local rule set with no user, account or reward payload fields."""

    policy_id: EngagementPolicyId
    qualification_requirement: QualificationRequirement
    progress_target: ProgressTarget
    reward_cap: RewardCap

    def __post_init__(self) -> None:
        if not isinstance(self.policy_id, EngagementPolicyId):
            raise TypeError("policy_id must be an EngagementPolicyId")
        if not isinstance(self.qualification_requirement, QualificationRequirement):
            raise TypeError("qualification_requirement must be a QualificationRequirement")
        if not isinstance(self.progress_target, ProgressTarget):
            raise TypeError("progress_target must be a ProgressTarget")
        if not isinstance(self.reward_cap, RewardCap):
            raise TypeError("reward_cap must be a RewardCap")


@dataclass(frozen=True, slots=True)
class KnownEngagementEvent:
    """One recognized local event that may be evaluated by a known policy."""

    event_id: EventId
    kind: EventKind

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, EventId):
            raise TypeError("event_id must be an EventId")
        if not isinstance(self.kind, EventKind):
            raise TypeError("kind must be an EventKind")


@dataclass(frozen=True, slots=True)
class UnknownEngagementEvent:
    """One typed but unsupported event that remains rejected without state changes."""

    event_id: EventId
    code: UnknownEventCode

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, EventId):
            raise TypeError("event_id must be an EventId")
        if not isinstance(self.code, UnknownEventCode):
            raise TypeError("code must be an UnknownEventCode")


EngagementInputEvent: TypeAlias = KnownEngagementEvent | UnknownEngagementEvent


@dataclass(frozen=True, slots=True)
class EngagementState:
    """An immutable local progress snapshot associated with exactly one policy ID."""

    policy_id: EngagementPolicyId
    qualification_count: int
    progress_count: int
    rewards_permitted: int
    processed_event_ids: frozenset[EventId]

    def __post_init__(self) -> None:
        if not isinstance(self.policy_id, EngagementPolicyId):
            raise TypeError("policy_id must be an EngagementPolicyId")
        _require_non_negative_count(self.qualification_count, "qualification_count")
        _require_non_negative_count(self.progress_count, "progress_count")
        _require_non_negative_count(self.rewards_permitted, "rewards_permitted")
        if not isinstance(self.processed_event_ids, frozenset):
            raise TypeError("processed_event_ids must be a frozenset")
        _require_event_ids(self.processed_event_ids)

    @classmethod
    def initial(cls, policy: EngagementPolicy) -> EngagementState:
        """Create a zeroed state for one explicit policy without implied identity."""
        if not isinstance(policy, EngagementPolicy):
            raise TypeError("policy must be an EngagementPolicy")
        no_event_ids: frozenset[EventId] = frozenset()
        return cls(
            policy_id=policy.policy_id,
            qualification_count=0,
            progress_count=0,
            rewards_permitted=0,
            processed_event_ids=no_event_ids,
        )

    def has_processed(self, event_id: EventId) -> bool:
        """Check whether an accepted event has already changed this snapshot."""
        if not isinstance(event_id, EventId):
            raise TypeError("event_id must be an EventId")
        return event_id in self.processed_event_ids

    def recorded(
        self,
        event_id: EventId,
        qualification_count: int,
        progress_count: int,
        rewards_permitted: int,
    ) -> EngagementState:
        """Return the next state after exactly one accepted, non-duplicate event."""
        if not isinstance(event_id, EventId):
            raise TypeError("event_id must be an EventId")
        if self.has_processed(event_id):
            raise ValueError("accepted event identifiers must not be duplicated")
        return EngagementState(
            policy_id=self.policy_id,
            qualification_count=qualification_count,
            progress_count=progress_count,
            rewards_permitted=rewards_permitted,
            processed_event_ids=self.processed_event_ids | frozenset((event_id,)),
        )


@dataclass(frozen=True, slots=True)
class EngagementEvaluationAccepted:
    """A local rule action with its next immutable state snapshot."""

    state: EngagementState
    action: EngagementAction

    def __post_init__(self) -> None:
        if not isinstance(self.state, EngagementState):
            raise TypeError("state must be an EngagementState")
        if not isinstance(self.action, EngagementAction):
            raise TypeError("action must be an EngagementAction")


@dataclass(frozen=True, slots=True)
class EngagementEvaluationRejected:
    """A fail-closed result that preserves the current immutable state exactly."""

    state: EngagementState
    reason: EngagementRejectionReason

    def __post_init__(self) -> None:
        if not isinstance(self.state, EngagementState):
            raise TypeError("state must be an EngagementState")
        if not isinstance(self.reason, EngagementRejectionReason):
            raise TypeError("reason must be an EngagementRejectionReason")


EngagementEvaluation: TypeAlias = (
    EngagementEvaluationAccepted | EngagementEvaluationRejected
)


@dataclass(frozen=True, slots=True)
class EngagementPolicyCatalog:
    """An immutable catalog that resolves known policies before evaluation."""

    policies: tuple[EngagementPolicy, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.policies, tuple):
            raise TypeError("policies must be a tuple")
        _require_unique_policies(self.policies)

    def evaluate(
        self,
        policy_id: EngagementPolicyId,
        state: EngagementState,
        event: EngagementInputEvent,
    ) -> EngagementEvaluation:
        """Evaluate only known policies and typed event inputs, otherwise fail closed."""
        if not isinstance(policy_id, EngagementPolicyId):
            raise TypeError("policy_id must be an EngagementPolicyId")
        if not isinstance(state, EngagementState):
            raise TypeError("state must be an EngagementState")
        if not isinstance(event, (KnownEngagementEvent, UnknownEngagementEvent)):
            raise TypeError(
                "event must be a KnownEngagementEvent or UnknownEngagementEvent"
            )
        policy = self._find_policy(policy_id)
        if policy is None:
            return EngagementEvaluationRejected(
                state=state,
                reason=EngagementRejectionReason.UNKNOWN_POLICY,
            )
        return evaluate_engagement_event(policy=policy, state=state, event=event)

    def _find_policy(self, policy_id: EngagementPolicyId) -> EngagementPolicy | None:
        policy: EngagementPolicy
        for policy in self.policies:
            if policy.policy_id == policy_id:
                return policy
        return None


def evaluate_engagement_event(
    policy: EngagementPolicy,
    state: EngagementState,
    event: EngagementInputEvent,
) -> EngagementEvaluation:
    """Apply a single typed event to one matching policy state without side effects."""
    if not isinstance(policy, EngagementPolicy):
        raise TypeError("policy must be an EngagementPolicy")
    if not isinstance(state, EngagementState):
        raise TypeError("state must be an EngagementState")
    if not isinstance(event, (KnownEngagementEvent, UnknownEngagementEvent)):
        raise TypeError("event must be a KnownEngagementEvent or UnknownEngagementEvent")
    if state.policy_id != policy.policy_id:
        return EngagementEvaluationRejected(
            state=state,
            reason=EngagementRejectionReason.STATE_POLICY_MISMATCH,
        )
    if not _state_satisfies_policy_bounds(policy=policy, state=state):
        return EngagementEvaluationRejected(
            state=state,
            reason=EngagementRejectionReason.INVALID_STATE,
        )
    if isinstance(event, UnknownEngagementEvent):
        return EngagementEvaluationRejected(
            state=state,
            reason=EngagementRejectionReason.UNKNOWN_EVENT,
        )
    if state.has_processed(event.event_id):
        return EngagementEvaluationRejected(
            state=state,
            reason=EngagementRejectionReason.DUPLICATE_EVENT,
        )
    if event.kind is EventKind.QUALIFICATION:
        return _evaluate_qualification(policy=policy, state=state, event=event)
    if event.kind is EventKind.PROGRESS:
        return _evaluate_progress(policy=policy, state=state, event=event)
    return _evaluate_reward_request(policy=policy, state=state, event=event)


def _evaluate_qualification(
    policy: EngagementPolicy,
    state: EngagementState,
    event: KnownEngagementEvent,
) -> EngagementEvaluation:
    if _is_recommendation_eligible(policy=policy, state=state):
        return EngagementEvaluationRejected(
            state=state,
            reason=EngagementRejectionReason.ALREADY_RECOMMENDATION_ELIGIBLE,
        )
    next_count = state.qualification_count + 1
    next_state = state.recorded(
        event_id=event.event_id,
        qualification_count=next_count,
        progress_count=state.progress_count,
        rewards_permitted=state.rewards_permitted,
    )
    action = (
        EngagementAction.RECOMMENDATION_ELIGIBLE
        if _is_recommendation_eligible(policy=policy, state=next_state)
        else EngagementAction.QUALIFICATION_RECORDED
    )
    return EngagementEvaluationAccepted(state=next_state, action=action)


def _evaluate_progress(
    policy: EngagementPolicy,
    state: EngagementState,
    event: KnownEngagementEvent,
) -> EngagementEvaluation:
    if not _is_recommendation_eligible(policy=policy, state=state):
        return EngagementEvaluationRejected(
            state=state,
            reason=EngagementRejectionReason.NOT_RECOMMENDATION_ELIGIBLE,
        )
    if state.progress_count >= policy.progress_target.value:
        return EngagementEvaluationRejected(
            state=state,
            reason=EngagementRejectionReason.PROGRESS_TARGET_REACHED,
        )
    next_count = state.progress_count + 1
    next_state = state.recorded(
        event_id=event.event_id,
        qualification_count=state.qualification_count,
        progress_count=next_count,
        rewards_permitted=state.rewards_permitted,
    )
    action = (
        EngagementAction.PROGRESS_TARGET_REACHED
        if next_count == policy.progress_target.value
        else EngagementAction.PROGRESS_RECORDED
    )
    return EngagementEvaluationAccepted(state=next_state, action=action)


def _evaluate_reward_request(
    policy: EngagementPolicy,
    state: EngagementState,
    event: KnownEngagementEvent,
) -> EngagementEvaluation:
    if not _is_recommendation_eligible(policy=policy, state=state):
        return EngagementEvaluationRejected(
            state=state,
            reason=EngagementRejectionReason.NOT_RECOMMENDATION_ELIGIBLE,
        )
    if state.progress_count < policy.progress_target.value:
        return EngagementEvaluationRejected(
            state=state,
            reason=EngagementRejectionReason.PROGRESS_TARGET_NOT_REACHED,
        )
    if state.rewards_permitted >= policy.reward_cap.value:
        return EngagementEvaluationRejected(
            state=state,
            reason=EngagementRejectionReason.REWARD_CAP_REACHED,
        )
    next_state = state.recorded(
        event_id=event.event_id,
        qualification_count=state.qualification_count,
        progress_count=state.progress_count,
        rewards_permitted=state.rewards_permitted + 1,
    )
    return EngagementEvaluationAccepted(
        state=next_state,
        action=EngagementAction.REWARD_PERMITTED,
    )


def _is_recommendation_eligible(
    policy: EngagementPolicy,
    state: EngagementState,
) -> bool:
    return state.qualification_count >= policy.qualification_requirement.value


def _state_satisfies_policy_bounds(
    policy: EngagementPolicy,
    state: EngagementState,
) -> bool:
    if state.qualification_count > policy.qualification_requirement.value:
        return False
    if state.progress_count > policy.progress_target.value:
        return False
    if state.rewards_permitted > policy.reward_cap.value:
        return False
    if not _is_recommendation_eligible(policy=policy, state=state):
        return state.progress_count == 0 and state.rewards_permitted == 0
    if state.progress_count < policy.progress_target.value:
        return state.rewards_permitted == 0
    return True


def _require_safe_identifier(value: str, name: str, maximum_length: int) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value or len(value) > maximum_length:
        raise ValueError(f"{name} must contain 1 to {maximum_length} characters")
    safe_characters = "abcdefghijklmnopqrstuvwxyz0123456789-_"
    if any(character not in safe_characters for character in value):
        raise ValueError(
            f"{name} must use lowercase letters, digits, hyphen or underscore only"
        )


def _require_positive_limit(value: int, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    if value < 1 or value > 10_000:
        raise ValueError(f"{name} must be between 1 and 10000")


def _require_non_negative_count(value: int, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must not be negative")


def _require_event_ids(event_ids: frozenset[EventId]) -> None:
    event_id: EventId
    for event_id in event_ids:
        if not isinstance(event_id, EventId):
            raise TypeError("processed_event_ids must contain EventId values")


def _require_unique_policies(policies: tuple[EngagementPolicy, ...]) -> None:
    seen_policy_ids: tuple[EngagementPolicyId, ...] = ()
    policy: EngagementPolicy
    for policy in policies:
        if not isinstance(policy, EngagementPolicy):
            raise TypeError("policies must contain EngagementPolicy values")
        if policy.policy_id in seen_policy_ids:
            raise ValueError("engagement policy identifiers must be unique")
        seen_policy_ids += (policy.policy_id,)
