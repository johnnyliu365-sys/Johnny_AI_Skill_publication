"""Pure, provider-neutral routing over canonicalized executor profiles."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Self, TypeAlias

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError, model_validator

from library.workflow_router.contracts import ModelRole


_OPAQUE_PATTERN = r"^[a-z][a-z0-9-]{2,127}$"

ProfileId: TypeAlias = Annotated[str, Field(pattern=_OPAQUE_PATTERN)]
ProviderId: TypeAlias = Annotated[str, Field(pattern=_OPAQUE_PATTERN)]
ModelId: TypeAlias = Annotated[str, Field(pattern=_OPAQUE_PATTERN)]
TicketRef: TypeAlias = Annotated[str, Field(pattern=_OPAQUE_PATTERN)]
ClosureRevision: TypeAlias = Annotated[str, Field(pattern=_OPAQUE_PATTERN)]
CapabilityEvidenceRef: TypeAlias = Annotated[str, Field(pattern=_OPAQUE_PATTERN)]
NoFurtherDecompositionEvidenceRef: TypeAlias = Annotated[
    str, Field(pattern=_OPAQUE_PATTERN)
]
CapabilityGapEvidenceRef: TypeAlias = Annotated[str, Field(pattern=_OPAQUE_PATTERN)]
IndependentVerificationEvidenceRef: TypeAlias = Annotated[
    str, Field(pattern=_OPAQUE_PATTERN)
]
OwnerDecisionRef: TypeAlias = Annotated[str, Field(pattern=_OPAQUE_PATTERN)]
OverrideReason: TypeAlias = Annotated[str, Field(min_length=1)]


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        revalidate_instances="always",
        strict=True,
        str_strip_whitespace=True,
    )


class RoutingPurpose(str, Enum):
    PROJECT_INITIAL_REVIEW = "PROJECT_INITIAL_REVIEW"
    REQUIREMENT_CHANGE_COMPLEX_DECISION_REVIEW = (
        "REQUIREMENT_CHANGE_COMPLEX_DECISION_REVIEW"
    )
    TICKET_OPENING = "TICKET_OPENING"
    INDEPENDENT_TICKET_REVIEW = "INDEPENDENT_TICKET_REVIEW"
    IMPLEMENTATION = "IMPLEMENTATION"


class ProfileAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class VerifiedCapabilityRank(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class AssessmentProvenance(str, Enum):
    INDEPENDENTLY_VERIFIED = "INDEPENDENTLY_VERIFIED"
    SELF_ASSERTED = "SELF_ASSERTED"
    UNVERIFIED = "UNVERIFIED"


class AssessmentFreshness(str, Enum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class EffortTier(str, Enum):
    LOW = "LOW"
    STANDARD = "STANDARD"
    HIGH = "HIGH"
    XHIGH = "XHIGH"


class AttemptState(str, Enum):
    INITIAL = "INITIAL"
    FAILED_ONCE = "FAILED_ONCE"
    BOUNDED_FAILURE = "BOUNDED_FAILURE"


class ResolutionStatus(str, Enum):
    SELECTED = "SELECTED"
    ROUTE_NOT_FOUND = "ROUTE_NOT_FOUND"
    ROUTE_AMBIGUOUS = "ROUTE_AMBIGUOUS"
    PROFILE_NOT_FOUND = "PROFILE_NOT_FOUND"
    PROFILE_UNAVAILABLE = "PROFILE_UNAVAILABLE"
    ROUTING_TABLE_INVALID = "ROUTING_TABLE_INVALID"
    PROFILE_REGISTRY_INVALID = "PROFILE_REGISTRY_INVALID"
    HARD_TICKET_ASSESSMENT_MISSING = "HARD_TICKET_ASSESSMENT_MISSING"
    HARD_TICKET_ASSESSMENT_INVALID = "HARD_TICKET_ASSESSMENT_INVALID"
    REVIEWER_CAPABILITY_INSUFFICIENT = "REVIEWER_CAPABILITY_INSUFFICIENT"
    OVERRIDE_RECORD_MISSING = "OVERRIDE_RECORD_MISSING"
    OVERRIDE_PROFILE_INVALID = "OVERRIDE_PROFILE_INVALID"
    MODEL_CAPABILITY_INSUFFICIENT = "MODEL_CAPABILITY_INSUFFICIENT"
    ARCHITECTURE_OWNER_REQUIRED = "ARCHITECTURE_OWNER_REQUIRED"


class ExecutorProfileRef(_StrictModel):
    value: ProfileId


class ExecutorProfile(_StrictModel):
    ref: ExecutorProfileRef
    provider: ProviderId
    model: ModelId
    effort: EffortTier
    verified_capability_rank: VerifiedCapabilityRank
    availability: ProfileAvailability
    availability_evidence: CapabilityEvidenceRef


class RoutingKey(_StrictModel):
    role: ModelRole
    purpose: RoutingPurpose


class RoutingEntry(_StrictModel):
    key: RoutingKey
    profile_ref: ExecutorProfileRef = Field(
        validation_alias=AliasChoices("profile_ref", "profile")
    )


RouteEntry: TypeAlias = RoutingEntry


class AssessmentVerification(_StrictModel):
    provenance: AssessmentProvenance
    freshness: AssessmentFreshness
    verified_ticket: TicketRef
    verified_closure_revision: ClosureRevision
    verification_record: IndependentVerificationEvidenceRef | None = None


class HardTicketAssessment(_StrictModel):
    ticket: TicketRef
    closure_revision: ClosureRevision
    no_further_decomposition: NoFurtherDecompositionEvidenceRef
    exceeds_standard_implementation: CapabilityGapEvidenceRef
    verification: AssessmentVerification


class ReviewBinding(_StrictModel):
    implementation_profile: ExecutorProfileRef
    reviewer_profile: ExecutorProfileRef
    ticket: TicketRef
    closure_revision: ClosureRevision


class OwnerOverrideRecord(_StrictModel):
    decision: OwnerDecisionRef
    selected_profile: ExecutorProfileRef
    reason: OverrideReason


class RouteRequest(_StrictModel):
    key: RoutingKey
    ticket: TicketRef
    closure_revision: ClosureRevision
    hard_ticket_assessment: HardTicketAssessment | None = None
    owner_override: OwnerOverrideRecord | None = None
    owner_override_requested: bool = False
    attempt_state: AttemptState = AttemptState.INITIAL
    failed_cycle_count: int = Field(default=0, ge=0, le=2)

    @model_validator(mode="after")
    def attempt_state_is_consistent(self) -> Self:
        expected = {
            AttemptState.INITIAL: 0,
            AttemptState.FAILED_ONCE: 1,
            AttemptState.BOUNDED_FAILURE: 2,
        }[self.attempt_state]
        if self.failed_cycle_count not in (0, expected):
            raise ValueError("attempt state and failed cycle count conflict")
        return self


class ExecutorRoutingTable(_StrictModel):
    routes: tuple[RoutingEntry, ...] = Field(
        default=(), validation_alias=AliasChoices("routes", "entries")
    )

    @model_validator(mode="after")
    def route_keys_are_unique(self) -> Self:
        keys = tuple((entry.key.role, entry.key.purpose) for entry in self.routes)
        if len(keys) != len(set(keys)):
            raise ValueError("routing keys must be unique")
        return self


class ExecutorProfileRegistry(_StrictModel):
    profiles: tuple[ExecutorProfile, ...] = Field(
        default=(), validation_alias=AliasChoices("profiles", "entries")
    )

    @model_validator(mode="after")
    def profile_references_are_unique(self) -> Self:
        references = tuple(profile.ref.value for profile in self.profiles)
        if len(references) != len(set(references)):
            raise ValueError("profile references must be unique")
        return self


class NamedRejection(_StrictModel):
    status: ResolutionStatus


class RouteResolution(_StrictModel):
    status: ResolutionStatus
    selected_profile: ExecutorProfileRef | None = None
    review_binding: ReviewBinding | None = None
    rejection: NamedRejection | None = None

    @model_validator(mode="after")
    def success_and_rejection_are_exclusive(self) -> Self:
        if self.status is ResolutionStatus.SELECTED:
            if self.selected_profile is None or self.rejection is not None:
                raise ValueError("selected resolution requires exactly one profile")
        elif (
            self.selected_profile is not None
            or self.review_binding is not None
            or self.rejection is None
        ):
            raise ValueError("rejected resolution cannot select a profile")
        if self.rejection is not None and self.rejection.status is not self.status:
            raise ValueError("rejection status must match resolution status")
        return self


_RANK_ORDER: dict[VerifiedCapabilityRank, int] = {
    VerifiedCapabilityRank.TIER_1: 1,
    VerifiedCapabilityRank.TIER_2: 2,
    VerifiedCapabilityRank.TIER_3: 3,
}


class ExecutorRoutingResolver:
    """Resolve one route from injected, already-normalized domain data."""

    def __init__(
        self,
        routing_table: ExecutorRoutingTable,
        profile_registry: ExecutorProfileRegistry,
    ) -> None:
        self._routing_table = routing_table
        self._profile_registry = profile_registry

    def resolve(self, request: RouteRequest) -> RouteResolution:
        routing_table = self._canonical_table()
        if routing_table is None:
            return self._reject(ResolutionStatus.ROUTING_TABLE_INVALID)

        profile_registry = self._canonical_registry()
        if profile_registry is None:
            return self._reject(ResolutionStatus.PROFILE_REGISTRY_INVALID)

        canonical_request = self._canonical_request(request)
        if canonical_request is None:
            try:
                assessment_present = request.hard_ticket_assessment is not None
            except AttributeError:
                assessment_present = False
            if assessment_present:
                return self._reject(ResolutionStatus.HARD_TICKET_ASSESSMENT_INVALID)
            return self._reject(ResolutionStatus.ROUTE_NOT_FOUND)

        cycle_result = self._resolve_attempt_state(canonical_request)
        if cycle_result is not None:
            return cycle_result

        route_result = self._find_route(routing_table, canonical_request.key)
        if route_result is None:
            return self._reject(ResolutionStatus.ROUTE_NOT_FOUND)
        if len(route_result) != 1:
            return self._reject(ResolutionStatus.ROUTE_AMBIGUOUS)

        base_profile = self._find_profile(profile_registry, route_result[0].profile_ref)
        if base_profile is None:
            return self._reject(ResolutionStatus.PROFILE_NOT_FOUND)
        if base_profile.availability is not ProfileAvailability.AVAILABLE:
            return self._reject(ResolutionStatus.PROFILE_UNAVAILABLE)

        selected_profile = base_profile
        if canonical_request.owner_override is not None:
            override_profile = self._find_profile(
                profile_registry, canonical_request.owner_override.selected_profile
            )
            if override_profile is None:
                return self._reject(ResolutionStatus.OVERRIDE_PROFILE_INVALID)
            if override_profile.availability is not ProfileAvailability.AVAILABLE:
                return self._reject(ResolutionStatus.OVERRIDE_PROFILE_INVALID)
            selected_profile = override_profile
        elif canonical_request.owner_override_requested:
            return self._reject(ResolutionStatus.OVERRIDE_RECORD_MISSING)

        if canonical_request.key.purpose is not RoutingPurpose.IMPLEMENTATION:
            return self._selected(selected_profile.ref)

        assessment_required = (
            base_profile.verified_capability_rank is VerifiedCapabilityRank.TIER_3
            or selected_profile.verified_capability_rank is VerifiedCapabilityRank.TIER_3
        )
        assessment_result = self._validate_assessment(
            canonical_request, assessment_required
        )
        if assessment_result is not None:
            return assessment_result

        reviewer_route_result = self._find_route(
            routing_table,
            RoutingKey(
                role=ModelRole.SUPERVISOR_REVIEWER,
                purpose=RoutingPurpose.INDEPENDENT_TICKET_REVIEW,
            ),
        )
        if reviewer_route_result is None:
            return self._reject(ResolutionStatus.ROUTE_NOT_FOUND)
        if len(reviewer_route_result) != 1:
            return self._reject(ResolutionStatus.ROUTE_AMBIGUOUS)
        reviewer = self._find_profile(profile_registry, reviewer_route_result[0].profile_ref)
        if reviewer is None:
            return self._reject(ResolutionStatus.PROFILE_NOT_FOUND)
        if reviewer.availability is not ProfileAvailability.AVAILABLE:
            return self._reject(ResolutionStatus.PROFILE_UNAVAILABLE)
        if _RANK_ORDER[reviewer.verified_capability_rank] < _RANK_ORDER[
            selected_profile.verified_capability_rank
        ]:
            return self._reject(ResolutionStatus.REVIEWER_CAPABILITY_INSUFFICIENT)

        binding = ReviewBinding(
            implementation_profile=selected_profile.ref,
            reviewer_profile=reviewer.ref,
            ticket=canonical_request.ticket,
            closure_revision=canonical_request.closure_revision,
        )
        return self._selected(selected_profile.ref, binding)

    def _canonical_table(self) -> ExecutorRoutingTable | None:
        try:
            return ExecutorRoutingTable.model_validate(self._routing_table)
        except (ValidationError, TypeError, ValueError, AttributeError):
            return None

    def _canonical_registry(self) -> ExecutorProfileRegistry | None:
        try:
            return ExecutorProfileRegistry.model_validate(self._profile_registry)
        except (ValidationError, TypeError, ValueError, AttributeError):
            return None

    @staticmethod
    def _canonical_request(request: RouteRequest) -> RouteRequest | None:
        try:
            return RouteRequest.model_validate(request)
        except (ValidationError, TypeError, ValueError, AttributeError):
            return None

    @staticmethod
    def _resolve_attempt_state(request: RouteRequest) -> RouteResolution | None:
        if request.attempt_state is AttemptState.BOUNDED_FAILURE or request.failed_cycle_count >= 2:
            return ExecutorRoutingResolver._reject(
                ResolutionStatus.ARCHITECTURE_OWNER_REQUIRED
            )
        if request.attempt_state is AttemptState.FAILED_ONCE or request.failed_cycle_count == 1:
            return ExecutorRoutingResolver._reject(
                ResolutionStatus.MODEL_CAPABILITY_INSUFFICIENT
            )
        return None

    @staticmethod
    def _find_route(
        routing_table: ExecutorRoutingTable, key: RoutingKey
    ) -> tuple[RoutingEntry, ...] | None:
        matches = tuple(entry for entry in routing_table.routes if entry.key == key)
        return matches or None

    @staticmethod
    def _find_profile(
        profile_registry: ExecutorProfileRegistry, reference: ExecutorProfileRef
    ) -> ExecutorProfile | None:
        matches = tuple(
            profile
            for profile in profile_registry.profiles
            if profile.ref == reference
        )
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _validate_assessment(
        request: RouteRequest, required: bool
    ) -> RouteResolution | None:
        assessment = request.hard_ticket_assessment
        if required and assessment is None:
            return ExecutorRoutingResolver._reject(
                ResolutionStatus.HARD_TICKET_ASSESSMENT_MISSING
            )
        if assessment is None:
            return None

        verification = assessment.verification
        if (
            assessment.ticket != request.ticket
            or assessment.closure_revision != request.closure_revision
            or verification.provenance is not AssessmentProvenance.INDEPENDENTLY_VERIFIED
            or verification.freshness is not AssessmentFreshness.CURRENT
            or verification.verified_ticket != request.ticket
            or verification.verified_closure_revision != request.closure_revision
            or verification.verification_record is None
            or verification.verification_record
            in (
                assessment.no_further_decomposition,
                assessment.exceeds_standard_implementation,
            )
        ):
            return ExecutorRoutingResolver._reject(
                ResolutionStatus.HARD_TICKET_ASSESSMENT_INVALID
            )
        return None

    @staticmethod
    def _selected(
        profile: ExecutorProfileRef, binding: ReviewBinding | None = None
    ) -> RouteResolution:
        return RouteResolution(
            status=ResolutionStatus.SELECTED,
            selected_profile=profile,
            review_binding=binding,
        )

    @staticmethod
    def _reject(status: ResolutionStatus) -> RouteResolution:
        return RouteResolution(
            status=status,
            rejection=NamedRejection(status=status),
        )


__all__ = [
    "AssessmentFreshness",
    "AssessmentProvenance",
    "AssessmentVerification",
    "AttemptState",
    "CapabilityEvidenceRef",
    "CapabilityGapEvidenceRef",
    "ClosureRevision",
    "EffortTier",
    "ExecutorProfile",
    "ExecutorProfileRef",
    "ExecutorProfileRegistry",
    "ExecutorRoutingResolver",
    "ExecutorRoutingTable",
    "HardTicketAssessment",
    "IndependentVerificationEvidenceRef",
    "ModelId",
    "ModelRole",
    "NamedRejection",
    "NoFurtherDecompositionEvidenceRef",
    "OverrideReason",
    "OwnerDecisionRef",
    "OwnerOverrideRecord",
    "ProfileAvailability",
    "ProfileId",
    "ProviderId",
    "ResolutionStatus",
    "ReviewBinding",
    "RouteEntry",
    "RouteRequest",
    "RouteResolution",
    "RoutingEntry",
    "RoutingKey",
    "RoutingPurpose",
    "TicketRef",
    "VerifiedCapabilityRank",
]
