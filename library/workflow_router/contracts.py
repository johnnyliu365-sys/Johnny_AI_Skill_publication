"""Strongly typed contracts for the reusable workflow router."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


NonBlankText = Annotated[str, Field(min_length=1)]
PositiveTokenBudget = Annotated[int, Field(gt=0)]
OpaqueMetadataId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{2,127}$")]
ProjectId = Annotated[str, Field(pattern=r"^prj_[0-9a-f]{16}$")]
WorktreeFingerprint = Annotated[str, Field(pattern=r"^worktree-[a-z0-9]+-[0-9]{2}$")]
BranchFingerprint = Annotated[str, Field(pattern=r"^branch-[a-z0-9]+-[0-9]{2}$")]
RevisionDigest = Annotated[str, Field(pattern=r"^rev-[0-9a-f]{16,64}$")]
EvidenceDigest = Annotated[str, Field(pattern=r"^sha256_[0-9a-f]{64}$")]
CommitDigest = Annotated[str, Field(pattern=r"^git_[0-9a-f]{12,64}$")]
ReviewedCommitReference = Annotated[str, Field(pattern=r"^[0-9a-f]{7,64}$")]
RequirementId = Annotated[str, Field(pattern=r"^PRD-[0-9]{8}-[0-9]{3}$")]
RequirementChangeId = Annotated[str, Field(pattern=r"^CHG-[0-9]{8}-[0-9]{3}$")]
RequirementArchiveId = Annotated[str, Field(pattern=r"^ARCH-REQ-[0-9]{8}-[0-9]{3}$")]


def _is_all_zero(value: str, prefix: str) -> bool:
    """Identify reserved all-zero metadata after a validated fixed prefix."""

    suffix = value[len(prefix) :]
    return bool(suffix) and all(character == "0" for character in suffix)


def _agent_context_metadata_is_safe(references: tuple[OpaqueMetadataId, ...]) -> bool:
    """Keep lease identifiers opaque and free of structural locators."""

    forbidden_delimiters = (
        "://",
        "\\",
        "/",
    )
    return not any(
        marker in reference.casefold()
        for reference in references
        for marker in forbidden_delimiters
    )


def _readiness_metadata_is_safe(references: tuple[OpaqueMetadataId, ...]) -> bool:
    """Keep readiness identifiers opaque and free of content or locator markers."""

    forbidden_markers = ("://", "\\", "/", "prompt", "body", "source", "secret")
    return not any(
        marker in reference.casefold()
        for reference in references
        for marker in forbidden_markers
    )


class RouterModel(BaseModel):
    """Immutable, strict base model for values that cross router boundaries."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, str_strip_whitespace=True)


class ProcessStage(str, Enum):
    """The finite workflow stages the router may address."""

    INTAKE = "intake"
    WAYFINDER = "wayfinder"
    ARCHITECTURE = "architecture"
    GRILL = "grill"
    CONTEXT = "context"
    SPEC = "spec"
    TICKETS = "tickets"
    IMPLEMENT = "implement"
    SMOKE_TEST = "smoke_test"
    REVIEW = "review"
    HANDOFF = "handoff"
    BLOCKED = "blocked"
    STOPPED = "stopped"


class DeliveryStage(str, Enum):
    """A project's delivery maturity, defined by its own workflow profile."""

    POC = "poc"
    MVP = "mvp"
    COMMERCIAL = "commercial"


class ModelRole(str, Enum):
    """The four finite model roles that may participate in the router."""

    ARCHITECTURE_OWNER = "architecture_owner"
    SUPERVISOR_REVIEWER = "supervisor_reviewer"
    IMPLEMENTATION_OWNER = "implementation_owner"
    RESEARCH_HELPER = "research_helper"


class RoleActivityState(str, Enum):
    """The finite lifecycle state of one declared model role."""

    ACTIVE = "active"
    SLEEPING = "sleeping"
    WAKE_REQUIRED = "wake_required"


class SpecificationReadinessDecision(str, Enum):
    """The finite outcomes of specification readiness admission."""

    READY_FOR_SUPERVISION = "ready_for_supervision"
    ARCHITECTURE_OWNER_REQUIRED = "architecture_owner_required"
    OWNER_APPROVAL_REQUIRED = "owner_approval_required"


class SpecificationClosureKind(str, Enum):
    """The nine finite closure dimensions required before supervision."""

    PUBLIC_CONTRACTS = "public_contracts"
    FINITE_STATES = "finite_states"
    ERROR_MEANINGS = "error_meanings"
    OWNERSHIP_DEPENDENCY_EFFECT_BOUNDARIES = "ownership_dependency_effect_boundaries"
    ROLLBACK_FORWARD_FIX = "rollback_forward_fix"
    ACCEPTANCE_CRITERIA = "acceptance_criteria"
    DELIVERY_PROFILE = "delivery_profile"
    SECURITY_XSS = "security_xss"
    UI_SOURCE_CLASSIFICATION = "ui_source_classification"


class SpecificationWakeReason(str, Enum):
    """The finite reasons that wake or retain the architecture owner."""

    SPEC_AMBIGUOUS = "spec_ambiguous"
    SPEC_CONTRADICTORY = "spec_contradictory"
    PUBLIC_CONTRACT_UNDEFINED = "public_contract_undefined"
    ACCEPTANCE_UNPROVABLE = "acceptance_unprovable"
    ARCHITECTURE_CONFLICT = "architecture_conflict"
    CROSS_TICKET_DESIGN_CONFLICT = "cross_ticket_design_conflict"
    REQUIREMENT_CHANGED = "requirement_changed"
    NEW_EXTERNAL_PRIVILEGED_BOUNDARY = "new_external_privileged_boundary"
    HIGH_ASSURANCE_TRIGGER = "high_assurance_trigger"
    MODEL_CAPABILITY_INSUFFICIENT = "model_capability_insufficient"
    CLOSURE_INCOMPLETE = "closure_incomplete"
    OPEN_DESIGN_DECISION = "open_design_decision"
    SUPERVISOR_CAPABILITY_UNAVAILABLE = "supervisor_capability_unavailable"


class RouterEventKind(str, Enum):
    """Only events in this closed set may drive a router transition."""

    INTAKE = "intake"
    WAYFINDER_GO = "wayfinder_go"
    WAYFINDER_NO_GO = "wayfinder_no_go"
    WAYFINDER_INFO_REQUIRED = "wayfinder_info_required"
    OWNER_INPUT_PROVIDED = "owner_input_provided"
    ACTION_COMPLETED = "action_completed"
    VALIDATION_PASSED = "validation_passed"
    VALIDATION_FAILED = "validation_failed"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_DENIED = "approval_denied"
    REQUIREMENT_CHANGED = "requirement_changed"
    CONTEXT_REFERENCE_CLOSED = "context_reference_closed"
    EXTERNAL_DECISION_REQUIRED = "external_decision_required"
    TICKET_DISPATCH_REQUIRED = "ticket_dispatch_required"
    IMPLEMENTATION_DISPATCH_CONFIRMED = "implementation_dispatch_confirmed"
    IMPLEMENTATION_RETURNED = "implementation_returned"
    INTEGRATION_COMPLETED = "integration_completed"
    AUDIT_COMPLETED = "audit_completed"


class CollaborationTopology(str, Enum):
    """The only supported role-isolated collaboration topologies."""

    ONE_IMPLEMENTATION_AGENT = "one_implementation_agent"
    TWO_COLLABORATING_AGENTS = "two_collaborating_agents"


class TicketDispatchConfirmation(str, Enum):
    """The ticket-scoped human dispatch response."""

    NEGATIVE = "negative"
    POSITIVE = "positive"


class TicketDispatchState(str, Enum):
    """The finite lifecycle of a dispatched ticket lane."""

    REQUIRED = "required"
    CONFIRMED = "confirmed"


class TicketProposalState(str, Enum):
    """The opened-ticket lifecycle before and after dispatch confirmation."""

    PLANNED = "planned"
    IN_PROGRESS = "in_progress"


class TicketEvent(str, Enum):
    """Events emitted by the typed ticket dispatch lane."""

    TICKET_DISPATCH_REQUIRED = "ticket_dispatch_required"
    IMPLEMENTATION_DISPATCH_CONFIRMED = "implementation_dispatch_confirmed"


class LaneKind(str, Enum):
    """The two independent state lanes created by a confirmed dispatch."""

    PLANNING = "planning"
    TICKET = "ticket"


class AuthorityState(str, Enum):
    """The current human authorization state for the requested transition."""

    APPROVED = "approved"
    PENDING = "pending"
    DENIED = "denied"
    NOT_REQUIRED = "not_required"


class RouterOutcome(str, Enum):
    """The finite results that a router may emit."""

    ADVANCE = "advance"
    RETRY = "retry"
    SUSPEND = "suspend"
    STOP = "stop"


class ContinuationDirective(str, Enum):
    """The sole safe disposition after a Router decision."""

    AUTO_CONTINUE = "auto_continue"
    WAIT_FOR_HUMAN = "wait_for_human"
    HALT = "halt"


class HumanWaitReason(str, Enum):
    """The finite human decisions that may produce a non-error wait."""

    SPECIFICATION_APPROVAL_REQUIRED = "specification_approval_required"
    TICKET_APPROVAL_REQUIRED = "ticket_approval_required"
    IMPLEMENTATION_OWNER_ASSIGNMENT_REQUIRED = "implementation_owner_assignment_required"
    TICKET_DISPATCH_CONFIRMATION_REQUIRED = "ticket_dispatch_confirmation_required"
    INTEGRATION_AUDIT_REQUIRED = "integration_audit_required"
    WAYFINDER_INPUT_GAP = "wayfinder_input_gap"


class CompletionActionKind(str, Enum):
    """The completed action classes that may be recorded as metadata-only evidence."""

    DOCUMENTATION = "documentation"
    IMPLEMENTATION = "implementation"
    REVIEW = "review"
    HANDOFF = "handoff"


class TicketScope(str, Enum):
    """Whether a ticket changes a formal UI boundary."""

    FRONTEND = "frontend"
    NON_FRONTEND = "non_frontend"


class ImplementationReturnStatus(str, Enum):
    """The finite results an implementation owner may return to the control plane."""

    COMPLETED = "completed"
    BLOCKED = "blocked"
    CHANGE_DETECTED = "change_detected"


class ReturnContractKind(str, Enum):
    """The finite return families a routed action may produce."""

    ROUTER_EVENT = "router_event"
    IMPLEMENTATION_RETURN = "implementation_return"
    NO_RETURN = "no_return"


class SharedContextOperation(str, Enum):
    """The finite operations admitted by the shared-Context lifecycle gate."""

    CREATE_DRAFT = "create_draft"
    REVISE_DRAFT = "revise_draft"
    SEAL = "seal"
    READ_REFERENCE = "read_reference"


class SharedContextLifecycle(str, Enum):
    """The finite stored lifecycle states of the shared Context."""

    ABSENT = "absent"
    ARCHITECTURE_DRAFT = "architecture_draft"
    SEALED = "sealed"


class SharedContextActorRole(str, Enum):
    """The finite roles that may request shared-Context access."""

    ARCHITECTURE_OWNER = "architecture_owner"
    SUPERVISOR_REVIEWER = "supervisor_reviewer"
    IMPLEMENTATION_OWNER = "implementation_owner"
    RESEARCH_HELPER = "research_helper"


class SharedContextMutationDecision(str, Enum):
    """The finite outcomes of shared-Context lifecycle admission."""

    ALLOW = "allow"
    REQUIRE_CHANGE_CONTROL = "require_change_control"
    FORBID_ROLE_OR_STAGE = "forbid_role_or_stage"
    STALE_REVISION = "stale_revision"


class AgentContextKind(str, Enum):
    """The only Context kind admitted by the implementation-owner lease gate."""

    IMPLEMENTATION_TICKET = "implementation_ticket"


class AgentContextActorRole(str, Enum):
    """The only actor role that may own an implementation Context lease."""

    IMPLEMENTATION_OWNER = "implementation_owner"


class AgentContextLifecycle(str, Enum):
    """The finite lifecycle of one ticket-scoped Agent Context lease."""

    ACTIVE = "active"
    CLOSED = "closed"
    INVALIDATED = "invalidated"


class AgentContextOperation(str, Enum):
    """The five finite operations admitted by the lease lifecycle gate."""

    OPEN = "open"
    RESUME = "resume"
    REBIND_CORRECTION = "rebind_correction"
    SWITCH_TICKET = "switch_ticket"
    CLOSE = "close"


class AgentContextUpstreamState(str, Enum):
    """The upstream fact state that precedes operation admission."""

    CURRENT = "current"
    MISSING = "missing"
    REQUIREMENT_CHANGED = "requirement_changed"


class AgentContextDecisionKind(str, Enum):
    """The finite outcomes of Agent Context lease admission."""

    ALLOW = "allow"
    AGENT_CONTEXT_BINDING_MISMATCH = "agent_context_binding_mismatch"
    AGENT_CONTEXT_STALE = "agent_context_stale"
    UPSTREAM_DECISION_REQUIRED = "upstream_decision_required"
    REQUIREMENT_CHANGED = "requirement_changed"


class AgentContextLease(RouterModel):
    """Immutable metadata for one implementation owner's ticket Context view."""

    lease_ref: OpaqueMetadataId
    project_id: ProjectId
    context_kind: AgentContextKind
    lifecycle: AgentContextLifecycle
    actor_role: AgentContextActorRole
    actor_capability_ref: OpaqueMetadataId
    artifact_path_refs: tuple[OpaqueMetadataId, ...] = Field(min_length=1)
    ticket_ref: OpaqueMetadataId
    ticket_revision: RevisionDigest
    receipt_ref: OpaqueMetadataId
    owner_ref: OpaqueMetadataId
    worktree_ref: WorktreeFingerprint
    branch_ref: BranchFingerprint
    baseline_revision: RevisionDigest
    control_baseline_ref: ReviewedCommitReference
    side_context_id: OpaqueMetadataId
    expected_return_ref: OpaqueMetadataId
    invalidation_refs: tuple[OpaqueMetadataId, ...] = ()

    @model_validator(mode="after")
    def metadata_identity_is_exact(self) -> AgentContextLease:
        """Reject duplicate leaves, reserved revisions and invalid lifecycle ownership."""

        metadata_refs = (
            self.lease_ref,
            self.actor_capability_ref,
            *self.artifact_path_refs,
            self.ticket_ref,
            self.receipt_ref,
            self.owner_ref,
            self.side_context_id,
            self.expected_return_ref,
            *self.invalidation_refs,
        )
        if not _agent_context_metadata_is_safe(metadata_refs):
            raise ValueError("Agent Context identifiers must remain metadata-only")
        if len(self.artifact_path_refs) != len(set(self.artifact_path_refs)):
            raise ValueError("Agent Context artifact references must be unique")
        if len(self.invalidation_refs) != len(set(self.invalidation_refs)):
            raise ValueError("Agent Context invalidation references must be unique")
        if _is_all_zero(self.ticket_revision, "rev-"):
            raise ValueError("ticket revisions must identify real ticket content")
        if _is_all_zero(self.baseline_revision, "rev-"):
            raise ValueError("baseline revisions must identify real source content")
        if not self.control_baseline_ref.strip("0"):
            raise ValueError("control baselines must identify a real reviewed commit")
        if self.actor_capability_ref != self.owner_ref:
            raise ValueError("actor capability must equal the implementation owner")
        if (
            self.lifecycle is AgentContextLifecycle.ACTIVE
            and self.side_context_id in self.invalidation_refs
        ):
            raise ValueError("an active lease cannot invalidate its own side Context")
        return self


class AgentContextTransitionRequest(RouterModel):
    """Strict operation-shaped request for one pure lease transition."""

    request_ref: OpaqueMetadataId
    operation: AgentContextOperation
    upstream_state: AgentContextUpstreamState
    expected_current_lease_ref: OpaqueMetadataId | None
    expected_current_side_context_id: OpaqueMetadataId | None
    candidate_lease: AgentContextLease | None

    @model_validator(mode="after")
    def operation_shape_is_exact(self) -> AgentContextTransitionRequest:
        """Require the exact null and candidate shape for each finite operation."""

        expected_refs = tuple(
            reference
            for reference in (
                self.request_ref,
                self.expected_current_lease_ref,
                self.expected_current_side_context_id,
            )
            if reference is not None
        )
        if not _agent_context_metadata_is_safe(expected_refs):
            raise ValueError("Agent Context request identifiers must remain metadata-only")
        if self.operation is AgentContextOperation.OPEN:
            if (
                self.expected_current_lease_ref is not None
                or self.expected_current_side_context_id is not None
                or self.candidate_lease is None
            ):
                raise ValueError("open requests require no current binding and one candidate")
        elif self.operation in (
            AgentContextOperation.RESUME,
            AgentContextOperation.REBIND_CORRECTION,
            AgentContextOperation.SWITCH_TICKET,
        ):
            if (
                self.expected_current_lease_ref is None
                or self.expected_current_side_context_id is None
                or self.candidate_lease is None
            ):
                raise ValueError("replacement requests require both current bindings and a candidate")
        elif self.operation is AgentContextOperation.CLOSE:
            if (
                self.expected_current_lease_ref is None
                or self.expected_current_side_context_id is None
                or self.candidate_lease is not None
            ):
                raise ValueError("close requests require both current bindings and no candidate")
        if (
            self.candidate_lease is not None
            and self.candidate_lease.lifecycle is not AgentContextLifecycle.ACTIVE
        ):
            raise ValueError("transition candidates must be active leases")
        return self


class AgentContextTransitionDecision(RouterModel):
    """Strict metadata result for one admitted or rejected lease transition."""

    request_ref: OpaqueMetadataId
    operation: AgentContextOperation
    decision: AgentContextDecisionKind
    prior_lease_result: AgentContextLease | None
    active_lease: AgentContextLease | None

    @model_validator(mode="after")
    def active_result_is_usable(self) -> AgentContextTransitionDecision:
        """Ensure each finite decision exposes only its exact lifecycle result shape."""

        if not _agent_context_metadata_is_safe((self.request_ref,)):
            raise ValueError("Agent Context decision identifiers must remain metadata-only")
        if self.decision is not AgentContextDecisionKind.ALLOW:
            if self.active_lease is not None:
                raise ValueError("rejected Agent Context results cannot expose an active lease")
            return self
        if self.operation is AgentContextOperation.OPEN:
            if (
                self.prior_lease_result is not None
                or self.active_lease is None
                or self.active_lease.lifecycle is not AgentContextLifecycle.ACTIVE
            ):
                raise ValueError("open results require only one active lease")
        elif self.operation is AgentContextOperation.RESUME:
            if (
                self.prior_lease_result is None
                or self.active_lease is None
                or self.prior_lease_result.lifecycle is not AgentContextLifecycle.ACTIVE
                or self.active_lease.lifecycle is not AgentContextLifecycle.ACTIVE
                or self.prior_lease_result != self.active_lease
            ):
                raise ValueError("resume results require the same active lease")
        elif self.operation is AgentContextOperation.REBIND_CORRECTION:
            if (
                self.prior_lease_result is None
                or self.prior_lease_result.lifecycle is not AgentContextLifecycle.INVALIDATED
                or self.active_lease is None
                or self.active_lease.lifecycle is not AgentContextLifecycle.ACTIVE
            ):
                raise ValueError("correction results require an invalidated prior and active replacement")
        elif self.operation is AgentContextOperation.SWITCH_TICKET:
            if (
                self.prior_lease_result is None
                or self.prior_lease_result.lifecycle is not AgentContextLifecycle.CLOSED
                or self.active_lease is None
                or self.active_lease.lifecycle is not AgentContextLifecycle.ACTIVE
            ):
                raise ValueError("switch results require a closed prior and active replacement")
        elif self.operation is AgentContextOperation.CLOSE:
            if (
                self.prior_lease_result is None
                or self.prior_lease_result.lifecycle is not AgentContextLifecycle.CLOSED
                or self.active_lease is not None
            ):
                raise ValueError("close results require only a closed prior lease")
        return self


class ArtifactTreeFamily(str, Enum):
    """The finite workflow artifact families routed through bounded trees."""

    REQUIREMENT_CHANGE = "requirement_change"
    SHARED_CONTEXT = "shared_context"
    AGENT_CONTEXT = "agent_context"
    SPECIFICATION = "specification"
    TICKET = "ticket"
    REVIEW = "review"
    PROGRESS_EVIDENCE = "progress_evidence"
    ADR_SECURITY = "adr_security"
    ARCHIVE_LIBRARY = "archive_library"
    REUSABLE_MODULE = "reusable_module"


class ArtifactTreeNodeKind(str, Enum):
    """The finite topology roles of one artifact-tree node."""

    ROOT_INDEX = "root_index"
    PARTITION_INDEX = "partition_index"
    LEAF = "leaf"


class ArtifactTreeLifecycle(str, Enum):
    """The lifecycle metadata carried by an artifact-tree node or edge."""

    ACTIVE = "active"
    CLOSED = "closed"
    ARCHIVED = "archived"


class ArtifactTreeDecisionKind(str, Enum):
    """The finite outcomes of exact artifact-tree resolution."""

    RESOLVED = "resolved"
    ARTIFACT_TREE_INVALID = "artifact_tree_invalid"
    ARTIFACT_PATH_NOT_FOUND = "artifact_path_not_found"


class ArtifactTreeInvalidReason(str, Enum):
    """The finite fail-closed reasons for an artifact-tree request."""

    REQUEST_BINDING_MISMATCH = "request_binding_mismatch"
    DUPLICATE_NODE = "duplicate_node"
    DUPLICATE_CHILD = "duplicate_child"
    DUPLICATE_PARENT = "duplicate_parent"
    CYCLE = "cycle"
    DANGLING_PATH_NODE = "dangling_path_node"
    FAMILY_MISMATCH = "family_mismatch"
    KIND_TRANSITION = "kind_transition"
    EDGE_METADATA_MISMATCH = "edge_metadata_mismatch"
    PATH_SEGMENT_MISSING = "path_segment_missing"


class ArtifactTreeChildRef(RouterModel):
    """Metadata for one direct child edge in an artifact-tree index."""

    child_ref: OpaqueMetadataId
    child_kind: ArtifactTreeNodeKind
    child_revision: RevisionDigest
    child_digest: EvidenceDigest
    child_lifecycle: ArtifactTreeLifecycle

    @model_validator(mode="after")
    def metadata_is_not_reserved(self) -> ArtifactTreeChildRef:
        """Reject reserved all-zero revision and digest metadata."""

        if _is_all_zero(self.child_revision, "rev-"):
            raise ValueError("artifact child revisions must identify real content")
        if _is_all_zero(self.child_digest, "sha256_"):
            raise ValueError("artifact child digests must identify real content")
        return self


class ArtifactTreeNode(RouterModel):
    """Metadata-only node with direct-child edges and no copied artifact body."""

    node_ref: OpaqueMetadataId
    family: ArtifactTreeFamily
    node_kind: ArtifactTreeNodeKind
    revision: RevisionDigest
    content_digest: EvidenceDigest
    lifecycle: ArtifactTreeLifecycle
    child_refs: tuple[ArtifactTreeChildRef, ...] = ()

    @model_validator(mode="after")
    def metadata_is_exact(self) -> ArtifactTreeNode:
        """Reject reserved node metadata and children on a leaf."""

        if _is_all_zero(self.revision, "rev-"):
            raise ValueError("artifact node revisions must identify real content")
        if _is_all_zero(self.content_digest, "sha256_"):
            raise ValueError("artifact node digests must identify real content")
        if self.node_kind is ArtifactTreeNodeKind.LEAF and self.child_refs:
            raise ValueError("artifact leaves cannot contain direct children")
        return self


class ArtifactTreeResolutionRequest(RouterModel):
    """One caller-selected metadata path through an artifact tree."""

    request_ref: OpaqueMetadataId
    family: ArtifactTreeFamily
    root_ref: OpaqueMetadataId
    explicit_path_refs: tuple[OpaqueMetadataId, ...] = Field(min_length=3)
    expected_leaf_ref: OpaqueMetadataId
    path_nodes: tuple[ArtifactTreeNode, ...] = Field(min_length=3)


class ArtifactTreeResolutionDecision(RouterModel):
    """The exact finite result of artifact-tree path admission."""

    request_ref: OpaqueMetadataId
    family: ArtifactTreeFamily
    decision: ArtifactTreeDecisionKind
    invalid_reason: ArtifactTreeInvalidReason | None
    resolved_leaf_ref: OpaqueMetadataId | None

    @model_validator(mode="after")
    def result_shape_is_exact(self) -> ArtifactTreeResolutionDecision:
        """Keep decision, reason and resolved-leaf fields finite and coherent."""

        if self.decision is ArtifactTreeDecisionKind.RESOLVED:
            if self.invalid_reason is not None or self.resolved_leaf_ref is None:
                raise ValueError("resolved decisions require only an exact leaf")
        elif self.decision is ArtifactTreeDecisionKind.ARTIFACT_TREE_INVALID:
            if (
                self.invalid_reason is None
                or self.invalid_reason is ArtifactTreeInvalidReason.PATH_SEGMENT_MISSING
                or self.resolved_leaf_ref is not None
            ):
                raise ValueError("invalid tree decisions require a non-path failure reason")
        elif self.decision is ArtifactTreeDecisionKind.ARTIFACT_PATH_NOT_FOUND:
            if (
                self.invalid_reason is not ArtifactTreeInvalidReason.PATH_SEGMENT_MISSING
                or self.resolved_leaf_ref is not None
            ):
                raise ValueError("missing-path decisions require only PATH_SEGMENT_MISSING")
        return self


class LibrarySelectionKind(str, Enum):
    """The two bounded library families selectable by the Router."""

    ARCHIVE = "archive"
    REUSABLE_MODULE = "reusable_module"


class LibrarySelectionDecisionKind(str, Enum):
    """The finite outcome of one caller-selected library path."""

    SELECTED = "selected"
    LIBRARY_SELECTION_INVALID = "library_selection_invalid"


class LibrarySelectionInvalidReason(str, Enum):
    """The finite fail-closed reasons for one library selection."""

    REQUEST_BINDING_MISMATCH = "request_binding_mismatch"
    FAMILY_MISMATCH = "family_mismatch"
    PATH_INVALID = "path_invalid"
    LEAF_LIFECYCLE_MISMATCH = "leaf_lifecycle_mismatch"
    LEAF_METADATA_MISMATCH = "leaf_metadata_mismatch"


class LibrarySelectionRecord(RouterModel):
    """Metadata-only identity and lifecycle for one selectable library leaf."""

    selection_ref: OpaqueMetadataId
    kind: LibrarySelectionKind
    root_ref: OpaqueMetadataId
    partition_ref: OpaqueMetadataId
    leaf_ref: OpaqueMetadataId
    leaf_lifecycle: ArtifactTreeLifecycle
    leaf_digest: EvidenceDigest

    @model_validator(mode="after")
    def leaf_digest_is_not_reserved(self) -> LibrarySelectionRecord:
        """Reject the reserved all-zero digest sentinel."""

        if _is_all_zero(self.leaf_digest, "sha256_"):
            raise ValueError("library selection leaves must identify real content")
        return self


class LibrarySelectionRequest(RouterModel):
    """One exact caller-supplied three-node library path."""

    request_ref: OpaqueMetadataId
    selection: LibrarySelectionRecord
    path: ArtifactTreeResolutionRequest

    @model_validator(mode="after")
    def path_is_exactly_bound(self) -> LibrarySelectionRequest:
        """Bind the supplied path identity to the selected record."""

        expected_refs = (
            self.selection.root_ref,
            self.selection.partition_ref,
            self.selection.leaf_ref,
        )
        supplied_node_refs = tuple(node.node_ref for node in self.path.path_nodes)
        if (
            len(self.path.explicit_path_refs) != 3
            or len(self.path.path_nodes) != 3
            or self.path.explicit_path_refs != expected_refs
            or supplied_node_refs != expected_refs
            or self.path.root_ref != self.selection.root_ref
            or self.path.expected_leaf_ref != self.selection.leaf_ref
        ):
            raise ValueError("library selection requests require one exact three-node path")
        return self


class LibrarySelectionDecision(RouterModel):
    """The exact finite result of one library selection admission."""

    request_ref: OpaqueMetadataId
    selection_ref: OpaqueMetadataId
    decision: LibrarySelectionDecisionKind
    invalid_reason: LibrarySelectionInvalidReason | None
    selected_leaf_ref: OpaqueMetadataId | None

    @model_validator(mode="after")
    def result_shape_is_exact(self) -> LibrarySelectionDecision:
        """Keep decision, reason and selected leaf fields coherent."""

        if self.decision is LibrarySelectionDecisionKind.SELECTED:
            if self.invalid_reason is not None or self.selected_leaf_ref is None:
                raise ValueError("selected results require only one selected leaf")
        elif self.invalid_reason is None or self.selected_leaf_ref is not None:
            raise ValueError("invalid results require one finite reason and no leaf")
        return self


class RequirementLifecycle(str, Enum):
    """The two lifecycle states of one requirement lineage record."""

    ACTIVE = "active"
    ARCHIVED = "archived"


class RequirementLineageDecisionKind(str, Enum):
    """The finite outcomes of requirement-lineage validation."""

    ACTIVE_PAIR_VALID = "active_pair_valid"
    RETIREMENT_VALID = "retirement_valid"
    REQUIREMENT_LINEAGE_INVALID = "requirement_lineage_invalid"


class RequirementLineageInvalidReason(str, Enum):
    """The finite fail-closed reasons for one requirement lineage request."""

    REQUEST_BINDING_MISMATCH = "request_binding_mismatch"
    IDENTIFIER_PAIR_MISMATCH = "identifier_pair_mismatch"
    ACTIVE_PATH_INVALID = "active_path_invalid"
    ACTIVE_LEAF_MISMATCH = "active_leaf_mismatch"
    RETIRED_PATH_STILL_ACTIVE = "retired_path_still_active"
    ARCHIVE_PATH_INVALID = "archive_path_invalid"
    ARCHIVE_BUNDLE_MISMATCH = "archive_bundle_mismatch"
    REPLACEMENT_PAIR_MISMATCH = "replacement_pair_mismatch"


def _lineage_metadata_is_safe(references: tuple[OpaqueMetadataId, ...]) -> bool:
    """Keep lineage references opaque without rejecting portable semantic IDs."""

    return all(
        "://" not in reference and "\\" not in reference and "/" not in reference
        for reference in references
    )


class RequirementArchiveBundle(RouterModel):
    """Immutable metadata binding a retired pair to one archive leaf."""

    archive_id: RequirementArchiveId
    archive_leaf_ref: OpaqueMetadataId
    retired_prd_id: RequirementId
    retired_change_id: RequirementChangeId
    retired_leaf_ref: OpaqueMetadataId
    last_active_revision: RevisionDigest
    retirement_reason_ref: OpaqueMetadataId
    replacement_prd_id: RequirementId | None
    replacement_change_id: RequirementChangeId | None
    historical_source_commit: CommitDigest
    content_digest: EvidenceDigest

    @model_validator(mode="after")
    def metadata_shape_is_exact(self) -> RequirementArchiveBundle:
        """Reject raw-looking references, reserved evidence and partial replacements."""

        references = (
            self.archive_leaf_ref,
            self.retired_leaf_ref,
            self.retirement_reason_ref,
        )
        if not _lineage_metadata_is_safe(references):
            raise ValueError("requirement archive references must remain metadata-only")
        if _is_all_zero(self.last_active_revision, "rev-"):
            raise ValueError("archive revisions must identify real retired content")
        if _is_all_zero(self.historical_source_commit, "git_"):
            raise ValueError("archive source commits must identify real history")
        if _is_all_zero(self.content_digest, "sha256_"):
            raise ValueError("archive digests must identify real content")
        if (self.replacement_prd_id is None) != (self.replacement_change_id is None):
            raise ValueError("replacement identifiers must be supplied as a pair")
        return self


class RequirementLineageRecord(RouterModel):
    """The lifecycle and exact leaf metadata for one PRD/CHG pair."""

    lineage_ref: OpaqueMetadataId
    prd_id: RequirementId
    change_id: RequirementChangeId
    lifecycle: RequirementLifecycle
    active_leaf_ref: OpaqueMetadataId | None
    archive_id: RequirementArchiveId | None
    archive_leaf_ref: OpaqueMetadataId | None
    revision: RevisionDigest
    content_digest: EvidenceDigest

    @model_validator(mode="after")
    def lifecycle_shape_is_exact(self) -> RequirementLineageRecord:
        """Require active and archived records to expose disjoint leaf metadata."""

        if not _lineage_metadata_is_safe(
            tuple(
                reference
                for reference in (
                    self.lineage_ref,
                    self.active_leaf_ref,
                    self.archive_leaf_ref,
                )
                if reference is not None
            )
        ):
            raise ValueError("requirement lineage references must remain metadata-only")
        if _is_all_zero(self.revision, "rev-"):
            raise ValueError("lineage revisions must identify real content")
        if _is_all_zero(self.content_digest, "sha256_"):
            raise ValueError("lineage digests must identify real content")
        if self.lifecycle is RequirementLifecycle.ACTIVE:
            if (
                self.active_leaf_ref is None
                or self.archive_id is not None
                or self.archive_leaf_ref is not None
            ):
                raise ValueError("active lineages require only an active leaf")
        elif (
            self.active_leaf_ref is not None
            or self.archive_id is None
            or self.archive_leaf_ref is None
        ):
            raise ValueError("archived lineages require only archive metadata")
        return self


class RequirementLineageValidationRequest(RouterModel):
    """One caller-selected active or retirement lineage branch."""

    request_ref: OpaqueMetadataId
    lineage: RequirementLineageRecord
    prd_root_ref: OpaqueMetadataId
    change_root_ref: OpaqueMetadataId
    prd_active_path: ArtifactTreeResolutionRequest
    change_active_path: ArtifactTreeResolutionRequest
    archive_root_ref: OpaqueMetadataId | None
    archive_path: ArtifactTreeResolutionRequest | None
    archive_bundle: RequirementArchiveBundle | None

    @model_validator(mode="after")
    def lifecycle_shape_is_exact(self) -> RequirementLineageValidationRequest:
        """Keep archive request fields aligned with the lineage lifecycle."""

        references = tuple(
            reference
            for reference in (self.request_ref, self.prd_root_ref, self.change_root_ref)
            if reference is not None
        )
        if not _lineage_metadata_is_safe(references):
            raise ValueError("lineage request references must remain metadata-only")
        archive_fields = (self.archive_root_ref, self.archive_path, self.archive_bundle)
        if self.lineage.lifecycle is RequirementLifecycle.ACTIVE:
            if any(field is not None for field in archive_fields):
                raise ValueError("active lineage requests cannot carry archive fields")
        elif any(field is None for field in archive_fields):
            raise ValueError("archived lineage requests require all archive fields")
        return self


class RequirementLineageValidationDecision(RouterModel):
    """The exact finite result of one requirement-lineage admission."""

    request_ref: OpaqueMetadataId
    lineage_ref: OpaqueMetadataId
    decision: RequirementLineageDecisionKind
    invalid_reason: RequirementLineageInvalidReason | None
    resolved_lineage_leaf_ref: OpaqueMetadataId | None

    @model_validator(mode="after")
    def result_shape_is_exact(self) -> RequirementLineageValidationDecision:
        """Keep success and failure results disjoint and metadata-only."""

        if not _lineage_metadata_is_safe((self.request_ref, self.lineage_ref)):
            raise ValueError("lineage decision references must remain metadata-only")
        if self.decision is RequirementLineageDecisionKind.REQUIREMENT_LINEAGE_INVALID:
            if self.invalid_reason is None or self.resolved_lineage_leaf_ref is not None:
                raise ValueError("invalid lineage results require only a finite reason")
        elif self.invalid_reason is not None or self.resolved_lineage_leaf_ref is None:
            raise ValueError("valid lineage results require only an exact leaf")
        return self


class SkillReference(RouterModel):
    """Versioned metadata identifying a later-resolved skill policy."""

    reference_id: OpaqueMetadataId
    source_revision: RevisionDigest
    content_digest: EvidenceDigest

    @model_validator(mode="after")
    def reference_id_is_metadata_only(self) -> SkillReference:
        """Reject locator and sensitive markers before a registry resolves the reference."""

        normalized = self.reference_id.casefold()
        forbidden_markers = ("://", "\\", "/", "prompt", "secret")
        if any(marker in normalized for marker in forbidden_markers):
            raise ValueError("skill reference IDs are metadata-only")
        if _is_all_zero(self.source_revision, "rev-"):
            raise ValueError("skill reference revisions must identify real policy content")
        if _is_all_zero(self.content_digest, "sha256_"):
            raise ValueError("skill reference digests must identify real policy content")
        return self


class ExpectedReturnContract(RouterModel):
    """Finite return family and event/status set expected from a selected skill."""

    contract_id: OpaqueMetadataId
    contract_revision: RevisionDigest
    return_kind: ReturnContractKind
    router_events: tuple[RouterEventKind, ...]
    implementation_statuses: tuple[ImplementationReturnStatus, ...]

    @model_validator(mode="after")
    def return_family_is_finite_and_consistent(self) -> ExpectedReturnContract:
        """Keep each return family disjoint, non-empty where required, and duplicate-free."""

        if _is_all_zero(self.contract_revision, "rev-"):
            raise ValueError("return contract revisions must identify real policy content")
        if len(self.router_events) != len(set(self.router_events)):
            raise ValueError("router events must be unique")
        if len(self.implementation_statuses) != len(set(self.implementation_statuses)):
            raise ValueError("implementation statuses must be unique")
        if self.return_kind is ReturnContractKind.ROUTER_EVENT:
            if not self.router_events or self.implementation_statuses:
                raise ValueError("router-event contracts require only non-empty router events")
        elif self.return_kind is ReturnContractKind.IMPLEMENTATION_RETURN:
            if not self.implementation_statuses or self.router_events:
                raise ValueError(
                    "implementation-return contracts require only non-empty implementation statuses"
                )
        elif self.router_events or self.implementation_statuses:
            raise ValueError("no-return contracts require empty event and status tuples")
        return self


class SharedContextContentManifest(RouterModel):
    """Metadata-only content identity for one shared-Context revision."""

    revision: RevisionDigest
    content_digest: EvidenceDigest
    stable_fact_refs: tuple[OpaqueMetadataId, ...] = ()
    invariant_boundary_refs: tuple[OpaqueMetadataId, ...] = ()
    artifact_index_refs: tuple[OpaqueMetadataId, ...] = ()

    @model_validator(mode="after")
    def references_are_unique_metadata(self) -> SharedContextContentManifest:
        """Reject reserved digest values and non-metadata reference markers."""

        if _is_all_zero(self.revision, "rev-"):
            raise ValueError("shared Context revisions must identify real content")
        if _is_all_zero(self.content_digest, "sha256_"):
            raise ValueError("shared Context digests must identify real content")
        references = (
            self.stable_fact_refs
            + self.invariant_boundary_refs
            + self.artifact_index_refs
        )
        if not references:
            raise ValueError("shared Context manifests require one metadata reference")
        if len(references) != len(set(references)):
            raise ValueError("shared Context references must be unique")
        forbidden_markers = (
            "://",
            "\\",
            "/",
            "prompt",
            "secret",
        )
        if any(
            marker in reference.casefold()
            for reference in references
            for marker in forbidden_markers
        ):
            raise ValueError("shared Context references must remain metadata-only")
        return self


class SharedContextState(RouterModel):
    """The validated metadata state of one shared Context lifecycle."""

    context_ref: OpaqueMetadataId
    lifecycle: SharedContextLifecycle
    revision: RevisionDigest | None
    content_digest: EvidenceDigest | None

    @model_validator(mode="after")
    def lifecycle_matches_content_identity(self) -> SharedContextState:
        """Keep absent state empty and every present state fully identified."""

        if self.lifecycle is SharedContextLifecycle.ABSENT:
            if self.revision is not None or self.content_digest is not None:
                raise ValueError("absent shared Context state cannot carry content identity")
            return self
        if self.revision is None or self.content_digest is None:
            raise ValueError("present shared Context state requires complete content identity")
        if _is_all_zero(self.revision, "rev-"):
            raise ValueError("shared Context revisions must identify real content")
        if _is_all_zero(self.content_digest, "sha256_"):
            raise ValueError("shared Context digests must identify real content")
        return self


class SharedContextAccessRequest(RouterModel):
    """A validated metadata-only request at the shared-Context lifecycle boundary."""

    request_ref: OpaqueMetadataId
    context_ref: OpaqueMetadataId
    operation: SharedContextOperation
    process_stage: ProcessStage
    actor_role: SharedContextActorRole
    actor_capability_ref: OpaqueMetadataId
    expected_current_revision: RevisionDigest | None
    candidate_manifest: SharedContextContentManifest | None
    change_authority_state: AuthorityState
    approved_change_ref: OpaqueMetadataId | None

    @model_validator(mode="after")
    def operation_shape_is_exact(self) -> SharedContextAccessRequest:
        """Require only the fields appropriate to the selected finite operation."""

        if self.expected_current_revision is not None and _is_all_zero(
            self.expected_current_revision, "rev-"
        ):
            raise ValueError("expected shared Context revisions must identify real content")
        if self.operation is SharedContextOperation.CREATE_DRAFT:
            if (
                self.expected_current_revision is not None
                or self.candidate_manifest is None
                or self.change_authority_state is not AuthorityState.NOT_REQUIRED
                or self.approved_change_ref is not None
            ):
                raise ValueError("create requests require an absent prior and one candidate")
        elif self.operation is SharedContextOperation.REVISE_DRAFT:
            if self.expected_current_revision is None or self.candidate_manifest is None:
                raise ValueError("revise requests require a prior revision and one candidate")
        elif self.operation in (
            SharedContextOperation.SEAL,
            SharedContextOperation.READ_REFERENCE,
        ):
            if (
                self.expected_current_revision is None
                or self.candidate_manifest is not None
                or self.change_authority_state is not AuthorityState.NOT_REQUIRED
                or self.approved_change_ref is not None
            ):
                raise ValueError("seal and read requests require only an expected revision")
        return self


class SharedContextAccessDecision(RouterModel):
    """The finite metadata-only result of shared-Context access admission."""

    request_ref: OpaqueMetadataId
    context_ref: OpaqueMetadataId
    operation: SharedContextOperation
    decision: SharedContextMutationDecision
    resulting_state: SharedContextState


class ArtifactKind(str, Enum):
    """Kinds of official sources and products that may be referenced."""

    PROJECT_GOAL = "project_goal"
    WAYFINDER_OUTPUT = "wayfinder_output"
    WAYFINDER_INFO_REQUEST = "wayfinder_info_request"
    ARCHITECTURE = "architecture"
    GRILL = "grill"
    CONTEXT = "context"
    SPEC = "spec"
    TICKET = "ticket"
    CHANGE = "change"
    SECURITY_POLICY = "security_policy"


class BlockerCode(str, Enum):
    """Reasons that force a fail-closed router decision."""

    AUTHORITY_REQUIRED = "authority_required"
    DELIVERY_STAGE_MISMATCH = "delivery_stage_mismatch"
    MISSING_REQUIRED_SOURCE = "missing_required_source"
    AMBIGUOUS_REQUIRED_SOURCE = "ambiguous_required_source"
    NO_DECLARED_TRANSITION = "no_declared_transition"
    SOURCE_UNAVAILABLE = "source_unavailable"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    INVALID_COMPLETION_EVIDENCE = "invalid_completion_evidence"
    IMPLEMENTATION_RETURN_BLOCKED = "implementation_return_blocked"
    IMPLEMENTATION_HANDOFF_REQUIRED = "implementation_handoff_required"
    IMPLEMENTATION_HANDOFF_UNDECLARED = "implementation_handoff_undeclared"
    TOPOLOGY_REQUIRED = "topology_required"
    DISPATCH_RECEIPT_REQUIRED = "dispatch_receipt_required"
    INVALID_DISPATCH_RECEIPT = "invalid_dispatch_receipt"
    LEGACY_TICKET_APPROVAL_BLOCKED = "legacy_ticket_approval_blocked"
    TICKET_PROPOSAL_REQUIRED = "ticket_proposal_required"
    INVALID_TICKET_PROPOSAL = "invalid_ticket_proposal"
    PENDING_DISPATCH_REQUIRED = "pending_dispatch_required"
    INVALID_PENDING_DISPATCH = "invalid_pending_dispatch"


class ReferenceStatus(str, Enum):
    """Lifecycle of a metadata-only Context reference edge."""

    OPEN = "open"
    CLOSED = "closed"
    INVALIDATED = "invalidated"


class ArtifactRef(RouterModel):
    """A versioned pointer to one official source or workflow artifact."""

    kind: ArtifactKind
    identifier: NonBlankText
    uri: NonBlankText
    revision: NonBlankText

    @property
    def logical_key(self) -> tuple[ArtifactKind, str, str]:
        """Return the identity that remains stable across revisions."""

        return (self.kind, self.identifier, self.uri)


class TicketDispatchReceipt(RouterModel):
    """Metadata-only proof that one approved ticket was delivered to its owner."""

    ticket_reference: OpaqueMetadataId
    implementation_owner_id: OpaqueMetadataId
    handoff_reference: OpaqueMetadataId
    expected_main_revision: RevisionDigest
    correlation_id: NonBlankText
    dispatch_question_id: OpaqueMetadataId
    worktree_fingerprint: WorktreeFingerprint
    branch_fingerprint: BranchFingerprint

    @model_validator(mode="after")
    def correlation_is_metadata_only(self) -> TicketDispatchReceipt:
        """Reject locators and sensitive labels at the dispatch boundary."""

        lowered = self.correlation_id.lower()
        if any(marker in lowered for marker in ("://", "\\", "/", "prompt", "secret")):
            raise ValueError("correlation_id must be metadata-only")
        return self

    @property
    def ticket_ref(self) -> str:
        """Expose the spec terminology without storing a second field."""

        return self.ticket_reference

    @property
    def implementation_owner(self) -> str:
        """Expose the spec terminology without storing a second field."""

        return self.implementation_owner_id

    @property
    def handoff_ref(self) -> str:
        """Expose the spec terminology without storing a second field."""

        return self.handoff_reference


class TicketProposal(RouterModel):
    """A selected ticket opened in progress before its single dispatch question."""

    ticket_reference: OpaqueMetadataId
    state: TicketProposalState
    implementation_owner_id: OpaqueMetadataId
    dispatch_question_id: OpaqueMetadataId | None = None
    proposal_revision: RevisionDigest

    @model_validator(mode="after")
    def question_matches_open_state(self) -> TicketProposal:
        """Require exactly one question identifier only after the proposal is opened."""

        if self.state is TicketProposalState.PLANNED and self.dispatch_question_id is not None:
            raise ValueError("planned ticket proposals cannot carry a dispatch question")
        if self.state is TicketProposalState.IN_PROGRESS and self.dispatch_question_id is None:
            raise ValueError("opened ticket proposals require one dispatch question")
        return self

    def open(self, *, dispatch_question_id: OpaqueMetadataId) -> TicketProposal:
        """Open one planned proposal and emit its single named dispatch question."""

        if self.state is not TicketProposalState.PLANNED:
            raise ValueError("only planned ticket proposals may be opened")
        return TicketProposal(
            ticket_reference=self.ticket_reference,
            state=TicketProposalState.IN_PROGRESS,
            implementation_owner_id=self.implementation_owner_id,
            dispatch_question_id=dispatch_question_id,
            proposal_revision=self.proposal_revision,
        )


class PendingDispatchDescriptor(RouterModel):
    """Metadata-only authorization state created by one opened dispatch question."""

    ticket_reference: OpaqueMetadataId
    proposal_revision: RevisionDigest
    expected_main_revision: RevisionDigest
    dispatch_question_id: OpaqueMetadataId
    implementation_owner_id: OpaqueMetadataId
    reviewed_handoff_reference: OpaqueMetadataId
    event_correlation_id: NonBlankText
    ticket_docs_commit: ReviewedCommitReference | None = None
    handoff_docs_commit: ReviewedCommitReference | None = None

    @property
    def ticket_ref(self) -> str:
        """Expose the specification terminology without duplicating state."""

        return self.ticket_reference

    @property
    def reviewed_handoff_ref(self) -> str:
        """Expose the reviewed handoff reference as an opaque metadata ID."""

        return self.reviewed_handoff_reference


class HandoffConsumerFingerprint(RouterModel):
    """Opaque consumer identity suitable for handoff metadata, never a local path or prompt."""

    agent_profile_id: OpaqueMetadataId
    profile_version: OpaqueMetadataId
    worktree_fingerprint: OpaqueMetadataId
    execution_fingerprint: OpaqueMetadataId


class HandoffArtifactReference(RouterModel):
    """An opaque source/revision/span mapping without URI, path, or source text."""

    artifact_id: OpaqueMetadataId
    revision_digest: RevisionDigest
    source_span_id: OpaqueMetadataId
    side_context_id: OpaqueMetadataId
    consumer_fingerprint: HandoffConsumerFingerprint


class CompletionEvidence(RouterModel):
    """Typed completion metadata; a commit digest is evidence and never a route decision."""

    completion_id: OpaqueMetadataId
    action_kind: CompletionActionKind
    artifact_references: tuple[HandoffArtifactReference, ...] = Field(min_length=1)
    verification_references: tuple[OpaqueMetadataId, ...] = Field(min_length=1)
    evidence_digest: EvidenceDigest
    commit_digest: CommitDigest | None = None
    emitted_event: RouterEventKind = RouterEventKind.ACTION_COMPLETED

    @model_validator(mode="after")
    def emits_only_completion(self) -> CompletionEvidence:
        """Prevent a completed action from smuggling an unrelated workflow event."""

        if self.emitted_event is not RouterEventKind.ACTION_COMPLETED:
            raise ValueError("completion evidence must emit action_completed")
        return self


class FrontendCompositionContract(RouterModel):
    """The required, explicit UI composition and dependency-injection handoff surface."""

    component_boundaries: NonBlankText
    composition_root_reference: OpaqueMetadataId
    dependency_scope: NonBlankText
    injected_interfaces: tuple[OpaqueMetadataId, ...] = Field(min_length=1)
    production_bindings: NonBlankText
    test_doubles: NonBlankText
    state_acceptance: NonBlankText


class ImplementationHandoff(RouterModel):
    """Approved implementation input with opaque references and separated responsibilities."""

    handoff_reference: OpaqueMetadataId
    ticket_reference: OpaqueMetadataId
    approved_spec_reference: OpaqueMetadataId
    expected_main_revision: RevisionDigest
    context_references: tuple[HandoffArtifactReference, ...] = Field(min_length=1)
    acceptance_references: tuple[OpaqueMetadataId, ...] = Field(min_length=1)
    tdd_references: tuple[OpaqueMetadataId, ...] = Field(min_length=1)
    scope: TicketScope
    frontend_composition: FrontendCompositionContract | None = None
    non_frontend_reason: NonBlankText | None = None
    control_owner_id: OpaqueMetadataId
    implementation_owner_id: OpaqueMetadataId
    reviewer_id: OpaqueMetadataId
    ticket_docs_commit: ReviewedCommitReference | None = None
    handoff_docs_commit: ReviewedCommitReference | None = None

    @model_validator(mode="after")
    def enforces_role_separation_and_frontend_contract(self) -> ImplementationHandoff:
        """Reject owner collisions and incomplete frontend/non-frontend declarations."""

        if self.control_owner_id == self.implementation_owner_id:
            raise ValueError("control_owner_id and implementation_owner_id must be different")
        if self.reviewer_id == self.implementation_owner_id:
            raise ValueError("reviewer_id and implementation_owner_id must be different")
        if self.scope is TicketScope.FRONTEND:
            if self.frontend_composition is None or self.non_frontend_reason is not None:
                raise ValueError("frontend handoffs require composition data and no non-frontend reason")
        elif self.frontend_composition is not None or self.non_frontend_reason is None:
            raise ValueError("non-frontend handoffs require an N/A reason and no frontend composition")
        return self

    @property
    def handoff_ref(self) -> str:
        """Expose the specification terminology without storing a second field."""

        return self.handoff_reference


class ImplementationReturn(RouterModel):
    """Metadata-only return from an implementation owner; changes re-enter Grill."""

    ticket_reference: OpaqueMetadataId
    status: ImplementationReturnStatus
    evidence_references: tuple[OpaqueMetadataId, ...] = Field(min_length=1)
    verification_references: tuple[OpaqueMetadataId, ...] = Field(min_length=1)
    evidence_digest: EvidenceDigest
    emitted_event: RouterEventKind

    @model_validator(mode="after")
    def status_matches_the_only_legal_return_event(self) -> ImplementationReturn:
        """Keep scope changes on the requirement-change route rather than silent patching."""

        if self.status is ImplementationReturnStatus.CHANGE_DETECTED:
            if self.emitted_event is not RouterEventKind.REQUIREMENT_CHANGED:
                raise ValueError("change_detected must emit requirement_changed")
        elif self.emitted_event not in (
            RouterEventKind.ACTION_COMPLETED,
            RouterEventKind.IMPLEMENTATION_RETURNED,
        ):
            raise ValueError("completed and blocked returns must emit action_completed")
        return self


class CapabilityRef(RouterModel):
    """An allowlisted capability, not an authority grant."""

    capability_id: NonBlankText
    version: NonBlankText
    agent_profile: NonBlankText

    @model_validator(mode="after")
    def capability_id_is_not_a_descriptive_profile(self) -> CapabilityRef:
        """Keep an authority-bearing opaque capability separate from its description."""

        if self.capability_id == self.agent_profile:
            raise ValueError("capability ID must not equal an agent profile")
        return self


class ModelRoleAssignment(RouterModel):
    """One profile-bound model role and its finite metadata evidence."""

    project_profile_ref: OpaqueMetadataId
    role: ModelRole
    model_ref: OpaqueMetadataId
    capability_refs: tuple[OpaqueMetadataId, ...] = Field(min_length=1)
    activity_state: RoleActivityState
    evidence_refs: tuple[OpaqueMetadataId, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def metadata_identity_is_exact(self) -> ModelRoleAssignment:
        """Reject duplicated, colliding or content-shaped role metadata."""

        all_references = (
            self.project_profile_ref,
            self.model_ref,
            *self.capability_refs,
            *self.evidence_refs,
        )
        if not _readiness_metadata_is_safe(all_references):
            raise ValueError("model role references must remain opaque metadata")
        if len(self.capability_refs) != len(set(self.capability_refs)):
            raise ValueError("model role capabilities must be unique")
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("model role evidence must be unique")
        if set(self.capability_refs).intersection(self.evidence_refs):
            raise ValueError("model role capabilities and evidence must be disjoint")
        if self.model_ref == self.project_profile_ref:
            raise ValueError("model and profile references must be distinct")
        if self.model_ref in self.capability_refs or self.model_ref in self.evidence_refs:
            raise ValueError("model and capability/evidence references must be distinct")
        if self.project_profile_ref in self.capability_refs or self.project_profile_ref in self.evidence_refs:
            raise ValueError("profile and capability/evidence references must be distinct")
        return self


class SpecificationClosureEvidence(RouterModel):
    """One metadata proof for a closed specification dimension."""

    kind: SpecificationClosureKind
    evidence_ref: OpaqueMetadataId

    @model_validator(mode="after")
    def metadata_is_opaque(self) -> SpecificationClosureEvidence:
        """Reject content-shaped closure evidence references."""

        if not _readiness_metadata_is_safe((self.evidence_ref,)):
            raise ValueError("closure evidence must remain opaque metadata")
        return self


class SpecificationReadinessBlocker(RouterModel):
    """One finite blocker that requires an architecture-owner wake."""

    reason: SpecificationWakeReason
    evidence_ref: OpaqueMetadataId

    @model_validator(mode="after")
    def metadata_is_opaque(self) -> SpecificationReadinessBlocker:
        """Reject content-shaped blocker evidence references."""

        if not _readiness_metadata_is_safe((self.evidence_ref,)):
            raise ValueError("blocker evidence must remain opaque metadata")
        return self


class SpecificationReadinessRequest(RouterModel):
    """The exact metadata request submitted to the readiness gate."""

    project_profile_ref: OpaqueMetadataId
    project_profile_version: NonBlankText
    specification_ref: OpaqueMetadataId
    specification_revision: RevisionDigest
    owner_approval_ref: OpaqueMetadataId | None
    closure_evidence: tuple[SpecificationClosureEvidence, ...]
    open_design_decision_refs: tuple[OpaqueMetadataId, ...]
    blockers: tuple[SpecificationReadinessBlocker, ...]

    @model_validator(mode="after")
    def metadata_and_collection_shape_is_exact(self) -> SpecificationReadinessRequest:
        """Reject duplicate finite facts and every non-metadata identifier."""

        references = (
            self.project_profile_ref,
            self.specification_ref,
            self.owner_approval_ref,
            *tuple(evidence.evidence_ref for evidence in self.closure_evidence),
            *self.open_design_decision_refs,
            *tuple(blocker.evidence_ref for blocker in self.blockers),
        )
        if not _readiness_metadata_is_safe(tuple(reference for reference in references if reference is not None)):
            raise ValueError("readiness request identifiers must remain opaque metadata")
        if _is_all_zero(self.specification_revision, "rev-"):
            raise ValueError("specification revisions must identify real content")
        closure_kinds = tuple(evidence.kind for evidence in self.closure_evidence)
        if len(closure_kinds) != len(set(closure_kinds)):
            raise ValueError("closure kinds must be unique")
        blocker_reasons = tuple(blocker.reason for blocker in self.blockers)
        if len(blocker_reasons) != len(set(blocker_reasons)):
            raise ValueError("blocker reasons must be unique")
        if len(self.open_design_decision_refs) != len(set(self.open_design_decision_refs)):
            raise ValueError("open design decisions must be unique")
        return self


class SpecificationReadinessAssessment(RouterModel):
    """The finite, metadata-only result of one readiness admission."""

    project_profile_ref: OpaqueMetadataId
    project_profile_version: NonBlankText
    specification_ref: OpaqueMetadataId
    specification_revision: RevisionDigest
    decision: SpecificationReadinessDecision
    wake_reason: SpecificationWakeReason | None

    @model_validator(mode="after")
    def decision_shape_is_exact(self) -> SpecificationReadinessAssessment:
        """Keep owner, architecture and ready results disjoint."""

        references = (
            self.project_profile_ref,
            self.specification_ref,
        )
        if not _readiness_metadata_is_safe(references):
            raise ValueError("readiness assessment identifiers must remain opaque metadata")
        if _is_all_zero(self.specification_revision, "rev-"):
            raise ValueError("assessment revisions must identify real content")
        if self.decision is SpecificationReadinessDecision.ARCHITECTURE_OWNER_REQUIRED:
            if self.wake_reason is None:
                raise ValueError("architecture-owner results require a wake reason")
        elif self.wake_reason is not None:
            raise ValueError("owner and ready results cannot carry a wake reason")
        return self


class CollaborationTopologyPlan(RouterModel):
    """A finite topology and its named capabilities, never a host-thread grant."""

    topology: CollaborationTopology
    control_plane: CapabilityRef
    implementation_owner: CapabilityRef
    reviewer: CapabilityRef
    host_thread_references: tuple[OpaqueMetadataId, ...] = ()

    @model_validator(mode="after")
    def roles_are_distinct(self) -> CollaborationTopologyPlan:
        """Prevent the implementation capability from colliding with either reviewer role."""

        if self.implementation_owner.capability_id in (
            self.control_plane.capability_id,
            self.reviewer.capability_id,
        ):
            raise ValueError("implementation capability must be role-isolated")
        return self


class RouterEvent(RouterModel):
    """A unique, validated request to re-evaluate the workflow."""

    event_id: NonBlankText
    kind: RouterEventKind
    completion_evidence: CompletionEvidence | None = None
    implementation_return: ImplementationReturn | None = None
    implementation_handoff: ImplementationHandoff | None = None
    dispatch_confirmation: TicketDispatchConfirmation | None = None
    dispatch_receipt: TicketDispatchReceipt | None = None
    lane_kind: LaneKind | None = None
    lane_id: OpaqueMetadataId | None = None
    ticket_proposal: TicketProposal | None = None

    @model_validator(mode="after")
    def completion_metadata_matches_event(self) -> RouterEvent:
        """Allow legacy action events while rejecting completion evidence on unrelated events."""

        if self.completion_evidence is not None and self.kind is not RouterEventKind.ACTION_COMPLETED:
            raise ValueError("completion_evidence is valid only for action_completed")
        if self.completion_evidence is not None and self.implementation_return is not None:
            raise ValueError("completion_evidence and implementation_return cannot share an event")
        if self.implementation_handoff is not None:
            if self.completion_evidence is not None or self.implementation_return is not None:
                raise ValueError("implementation_handoff cannot share an event with completion or return")
            if self.kind not in (
                RouterEventKind.APPROVAL_GRANTED,
                RouterEventKind.TICKET_DISPATCH_REQUIRED,
            ):
                raise ValueError("implementation_handoff requires a ticket dispatch lifecycle event")
        if self.implementation_return is not None and self.implementation_return.emitted_event is not self.kind:
            raise ValueError("implementation_return event must match router event kind")
        if self.dispatch_confirmation is not None or self.dispatch_receipt is not None:
            if self.kind not in (
                RouterEventKind.TICKET_DISPATCH_REQUIRED,
                RouterEventKind.IMPLEMENTATION_DISPATCH_CONFIRMED,
            ):
                raise ValueError("dispatch metadata requires a ticket dispatch event")
        if (
            self.dispatch_receipt is not None
            and self.kind is not RouterEventKind.IMPLEMENTATION_DISPATCH_CONFIRMED
        ):
            raise ValueError("dispatch receipts require confirmed dispatch")
        if self.ticket_proposal is not None and self.kind is not RouterEventKind.TICKET_DISPATCH_REQUIRED:
            raise ValueError("ticket proposals require a dispatch-required event")
        if self.lane_kind is None and self.lane_id is not None:
            raise ValueError("lane_id requires lane_kind")
        if self.lane_kind is not None and self.lane_id is None:
            raise ValueError("lane_kind requires lane_id")
        return self


class RouterState(RouterModel):
    """The compact state required for one deterministic routing decision."""

    project_id: NonBlankText
    stage: ProcessStage
    authority_state: AuthorityState
    delivery_stage: DeliveryStage
    artifact_refs: tuple[ArtifactRef, ...]
    topology: CollaborationTopology | None = None
    collaboration_plan: CollaborationTopologyPlan | None = None
    pending_dispatch: PendingDispatchDescriptor | None = None


class PlanningLaneState(RouterModel):
    """Independent planning-lane state created by a confirmed ticket dispatch."""

    project_id: NonBlankText
    stage: ProcessStage
    topology: CollaborationTopology
    artifact_refs: tuple[ArtifactRef, ...]
    active_ticket_refs: tuple[OpaqueMetadataId, ...]
    context_view_id: OpaqueMetadataId
    side_context_id: OpaqueMetadataId
    event_id: OpaqueMetadataId
    safety_ceiling: PositiveTokenBudget


class TicketLaneState(RouterModel):
    """Independent ticket-execution state with no mutable planning-lane handle."""

    ticket_id: OpaqueMetadataId
    dispatch_state: TicketDispatchState
    execution_stage: ProcessStage
    expected_main_revision: RevisionDigest
    source_grants: tuple[ArtifactKind, ...]
    context_view_id: OpaqueMetadataId
    side_context_id: OpaqueMetadataId
    event_id: OpaqueMetadataId
    worktree_fingerprint: WorktreeFingerprint
    branch_fingerprint: BranchFingerprint
    safety_ceiling: PositiveTokenBudget
    implementation_capability: CapabilityRef
    reviewer: CapabilityRef


class CollaborationDispatchPlan(RouterModel):
    """The immutable pair of planning and ticket lanes from one receipt."""

    receipt: TicketDispatchReceipt
    planning_lane: PlanningLaneState
    ticket_lane: TicketLaneState

    @model_validator(mode="after")
    def has_one_exact_named_ticket_lane(self) -> CollaborationDispatchPlan:
        """Bind the receipt to named actor identities, never descriptive profiles."""

        if (
            self.receipt.ticket_reference != self.ticket_lane.ticket_id
            or self.receipt.expected_main_revision != self.ticket_lane.expected_main_revision
            or self.receipt.worktree_fingerprint != self.ticket_lane.worktree_fingerprint
            or self.receipt.branch_fingerprint != self.ticket_lane.branch_fingerprint
            or self.receipt.implementation_owner_id
            != self.ticket_lane.implementation_capability.capability_id
            or self.receipt.ticket_reference not in self.planning_lane.active_ticket_refs
        ):
            raise ValueError("dispatch receipt must bind one exact named ticket lane")
        return self

    def with_planning_progress(
        self,
        *,
        stage: ProcessStage,
        event_id: OpaqueMetadataId,
    ) -> CollaborationDispatchPlan:
        """Advance only the planning descriptor while preserving ticket execution state."""

        return self.model_copy(
            update={
                "planning_lane": self.planning_lane.model_copy(
                    update={"stage": stage, "event_id": event_id}
                )
            }
        )


class RouterBlocker(RouterModel):
    """A typed explanation for a fail-closed decision."""

    code: BlockerCode
    detail: NonBlankText


class ConsumerFingerprint(RouterModel):
    """Identifies the agent/worktree execution that consumed a Context span."""

    agent_profile: NonBlankText
    profile_version: NonBlankText
    worktree_id: NonBlankText
    execution_id: NonBlankText


class ContextReference(RouterModel):
    """One metadata-only, one-time reference from source Context to a target artifact."""

    source_context: ArtifactRef
    source_revision: NonBlankText
    source_span: NonBlankText
    side_context_id: NonBlankText
    consumer_fingerprint: ConsumerFingerprint
    target_artifact: ArtifactRef
    status: ReferenceStatus = ReferenceStatus.OPEN

    @model_validator(mode="after")
    def revision_matches_source(self) -> ContextReference:
        """Prevent a reference from claiming a revision different from its source."""

        if self.source_revision != self.source_context.revision:
            raise ValueError("source_revision must match source_context.revision")
        return self


class ContextView(RouterModel):
    """A persistent descriptor for a temporary Context packet; it contains no raw text."""

    view_id: NonBlankText
    purpose: NonBlankText
    references: tuple[ContextReference, ...]
    token_budget: PositiveTokenBudget
    invalidation_events: tuple[RouterEventKind, ...]


class RouterDecision(RouterModel):
    """The only legal output of the pure router engine."""

    skill_reference: SkillReference
    expected_return: ExpectedReturnContract
    outcome: RouterOutcome
    continuation: ContinuationDirective
    next_stage: ProcessStage | None
    required_sources: tuple[ArtifactRef, ...]
    context_view: ContextView | None = None
    eligible_capabilities: tuple[CapabilityRef, ...]
    blockers: tuple[RouterBlocker, ...] = ()
    wait_reason: HumanWaitReason | None = None
    dispatch_plan: CollaborationDispatchPlan | None = None
    ticket_lane_capabilities: tuple[CapabilityRef, ...] = ()
    ticket_proposal: TicketProposal | None = None
    pending_dispatch: PendingDispatchDescriptor | None = None

    @model_validator(mode="after")
    def decision_shape_is_consistent(self) -> RouterDecision:
        """Ensure advance and fail-closed outcomes cannot be represented ambiguously."""

        if self.outcome in (RouterOutcome.ADVANCE, RouterOutcome.RETRY) and self.next_stage is None:
            raise ValueError("advancing and retry decisions require next_stage")
        if (
            self.outcome is RouterOutcome.ADVANCE
            and self.continuation is not ContinuationDirective.AUTO_CONTINUE
        ):
            raise ValueError("advance decisions must auto-continue")
        if (
            self.outcome is RouterOutcome.RETRY
            and self.continuation is not ContinuationDirective.AUTO_CONTINUE
        ):
            raise ValueError("retry decisions must auto-continue")
        if self.outcome is RouterOutcome.SUSPEND and self.next_stage is not None:
            raise ValueError("suspend decisions must not invent a next_stage")
        if (
            self.outcome is RouterOutcome.SUSPEND
            and self.continuation is ContinuationDirective.AUTO_CONTINUE
        ):
            raise ValueError("suspend decisions must wait or halt")
        if self.outcome is RouterOutcome.STOP and self.next_stage is not ProcessStage.STOPPED:
            raise ValueError("stop decisions must target stopped")
        if self.outcome is RouterOutcome.STOP and self.continuation is not ContinuationDirective.HALT:
            raise ValueError("stop decisions must halt")
        if self.continuation is ContinuationDirective.WAIT_FOR_HUMAN:
            if self.outcome is not RouterOutcome.SUSPEND or self.wait_reason is None:
                raise ValueError("human waits require a suspended decision and a precise wait reason")
            if self.required_sources or self.eligible_capabilities or self.context_view is not None:
                raise ValueError("human waits cannot grant Context or capabilities")
            if self.dispatch_plan is not None:
                raise ValueError("human waits cannot grant dispatch plans")
            if self.ticket_lane_capabilities:
                raise ValueError("human waits cannot grant ticket-lane capabilities")
            if self.pending_dispatch is not None and self.ticket_proposal is None:
                raise ValueError("pending dispatch state requires its opened ticket proposal")
            if (
                self.pending_dispatch is not None
                and self.ticket_proposal is not None
                and (
                    self.pending_dispatch.ticket_reference != self.ticket_proposal.ticket_reference
                    or self.pending_dispatch.proposal_revision != self.ticket_proposal.proposal_revision
                    or self.pending_dispatch.dispatch_question_id != self.ticket_proposal.dispatch_question_id
                    or self.pending_dispatch.implementation_owner_id
                    != self.ticket_proposal.implementation_owner_id
                )
            ):
                raise ValueError("pending dispatch state must match its opened ticket proposal")
        elif self.ticket_proposal is not None or self.pending_dispatch is not None:
            raise ValueError("automatic or halted decisions cannot carry pending dispatch state")
        elif self.wait_reason is not None:
            raise ValueError("only human waits may declare a wait reason")
        if self.continuation is ContinuationDirective.HALT and self.dispatch_plan is not None:
            raise ValueError("halted decisions cannot grant dispatch plans")
        if self.continuation is ContinuationDirective.HALT and self.ticket_lane_capabilities:
            raise ValueError("halted decisions cannot grant ticket-lane capabilities")
        if self.continuation is ContinuationDirective.HALT and self.ticket_proposal is not None:
            raise ValueError("halted decisions cannot carry an opened proposal")
        return self


class SourceSnippet(RouterModel):
    """Raw source text returned by a source adapter; never store this in shared state."""

    source: ArtifactRef
    span: NonBlankText
    text: NonBlankText


@dataclass(frozen=True, slots=True)
class ContextPacket:
    """Ephemeral raw Context held only by the consuming Agent/worktree."""

    snippets: tuple[SourceSnippet, ...]


@dataclass(frozen=True, slots=True)
class ResolvedContext:
    """Pair a durable descriptor with an ephemeral raw packet."""

    view: ContextView
    packet: ContextPacket


class WayfinderInputField(str, Enum):
    """The closed set of Wayfinder inputs a gap request may name."""

    PRODUCT_TARGET_USERS = "product_target_users"
    PRODUCT_CORE_PROBLEM = "product_core_problem"
    PRODUCT_VALUE_PROPOSITION = "product_value_proposition"
    PRODUCT_MVP_SCOPE = "product_mvp_scope"
    PRODUCT_OUT_OF_SCOPE = "product_out_of_scope"
    SLICE_SET_INCOMPLETE = "slice_set_incomplete"
    SLICE_ACTOR = "slice_actor"
    SLICE_USER_GOAL = "slice_user_goal"
    SLICE_BOUNDARY = "slice_boundary"
    SLICE_ACTIONS = "slice_actions"
    SLICE_OUTCOMES = "slice_outcomes"
    SLICE_STATES = "slice_states"
    CAPABILITY_USE_CASES = "capability_use_cases"
    CAPABILITY_DOMAIN_RULES = "capability_domain_rules"
    CAPABILITY_CONTRACTS = "capability_contracts"
    CAPABILITY_AUTHZ_FAILURE = "capability_authz_failure"
    DATA_PIPELINE = "data_pipeline"
    DATA_OWNERSHIP = "data_ownership"
    BUSINESS_MODEL = "business_model"
    BUSINESS_VALIDATION = "business_validation"
    BUSINESS_METRICS = "business_metrics"
    BUSINESS_STOP_CONDITIONS = "business_stop_conditions"
    TECH_LIMITS = "tech_limits"
    COST_CEILING = "cost_ceiling"
    RISK_MITIGATION = "risk_mitigation"


class WayfinderBlockKind(str, Enum):
    """What a Wayfinder input gap blocks: an output field or a strict veto check."""

    OUTPUT_FIELD = "output_field"
    STRICT_VETO = "strict_veto"


class WayfinderInputGap(RouterModel):
    """One enumerated missing input; every question must name what it unblocks."""

    field: WayfinderInputField
    feature_id: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    block_kind: WayfinderBlockKind
    block_reference: Annotated[str, Field(min_length=1, max_length=120)]
    question: Annotated[str, Field(min_length=1, max_length=300)]


class WayfinderInfoRequest(RouterModel):
    """One bounded, complete Wayfinder gap round; the type forbids a third round.

    Convergence rules carried by this contract:
    1. each round lists every currently blocking gap at once;
    2. an answered field is never asked again (monotonic shrink);
    3. the round counter is closed at two, so exhaustion forces a terminal
       GO / NO-GO with explicit assumptions or INSUFFICIENT_INPUT;
    4. every question names the exact output field or strict-veto item it
       unblocks, so curiosity questions are untypable.
    """

    round_number: Literal[1, 2]
    gaps: tuple[WayfinderInputGap, ...] = Field(min_length=1)
    answered_fields: tuple[WayfinderInputField, ...] = ()

    @model_validator(mode="after")
    def rounds_shrink_and_never_reask(self) -> WayfinderInfoRequest:
        if self.round_number == 1 and self.answered_fields:
            raise ValueError("the first round has no previously answered fields")
        if self.round_number == 2 and not self.answered_fields:
            raise ValueError("a second round must name the fields already answered")
        answered = set(self.answered_fields)
        if any(gap.field in answered for gap in self.gaps):
            raise ValueError("an answered field must not be asked again")
        identities = tuple((gap.field, gap.feature_id) for gap in self.gaps)
        if len(set(identities)) != len(identities):
            raise ValueError("each round lists one gap per field and feature")
        return self


class IntakeMode(str, Enum):
    """How a project enters the workflow; each mode scopes Wayfinder differently."""

    GREENFIELD = "greenfield"
    TAKEOVER = "takeover"
    DELTA = "delta"


class ProductKind(str, Enum):
    """The observable product shape a goal targets; slices adapt to it."""

    USER_FACING = "user_facing"
    SERVICE = "service"
    LIBRARY = "library"
    CLI = "cli"
    CONTROL_PLANE = "control_plane"


class NormalizedGoal(RouterModel):
    """The typed INTAKE output; Wayfinder accepts no other goal authority.

    `baseline_reference` binds TAKEOVER/DELTA to one existing repository
    identity as `<opaque-repo-id>@<commit>`; paths and URIs are untypable.
    """

    schema_version: Literal["1"] = "1"
    intake_mode: IntakeMode
    product_kind: ProductKind
    goal_statement: Annotated[str, Field(min_length=1, max_length=500)]
    known_constraints: tuple[
        Annotated[str, Field(min_length=1, max_length=300)], ...
    ] = ()
    evidence_refs: tuple[OpaqueMetadataId, ...] = ()
    baseline_reference: (
        Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9.-]{0,80}@[0-9a-f]{7,64}$")]
        | None
    ) = None
    delta_scope: tuple[
        Annotated[str, Field(min_length=1, max_length=200)], ...
    ] = ()
    workload: "WorkloadAssessment | None" = None

    @model_validator(mode="after")
    def mode_shape_is_exact(self) -> NormalizedGoal:
        if self.intake_mode is IntakeMode.GREENFIELD:
            if self.baseline_reference is not None or self.delta_scope:
                raise ValueError(
                    "a greenfield goal has no existing baseline or delta scope"
                )
        else:
            if self.baseline_reference is None:
                raise ValueError(
                    "takeover and delta goals require the existing baseline reference"
                )
            if self.intake_mode is IntakeMode.DELTA and not self.delta_scope:
                raise ValueError("a delta goal names its affected scope")
            if self.intake_mode is IntakeMode.TAKEOVER and self.delta_scope:
                raise ValueError("delta_scope is valid only for delta goals")
        return self


class ChangeSurface(str, Enum):
    """How much of the target the goal touches."""

    SINGLE_FILE = "single_file"
    SINGLE_COMPONENT = "single_component"
    MULTI_COMPONENT = "multi_component"
    CROSS_BOUNDARY = "cross_boundary"


class UncertaintyLevel(str, Enum):
    """How well-established the required solution pattern is."""

    ESTABLISHED_PATTERN = "established_pattern"
    KNOWN_DOMAIN = "known_domain"
    NOVEL = "novel"


class RecoveryDifficulty(str, Enum):
    """How hard a wrong outcome is to undo."""

    REVERSIBLE = "reversible"
    RECOVERABLE = "recoverable"
    IRREVERSIBLE = "irreversible"


class SecuritySurface(str, Enum):
    """The security exposure the change can reach."""

    NONE = "none"
    UNTRUSTED_INPUT = "untrusted_input"
    PRIVILEGED = "privileged"


class ExternalEffectSurface(str, Enum):
    """The widest external effect the change can produce."""

    NONE = "none"
    LOCAL_HOST = "local_host"
    NETWORK_OR_RELEASE = "network_or_release"


class WorkflowIntensity(str, Enum):
    """The finite workflow shapes; ordering is COMPACT < STANDARD < HIGH_ASSURANCE."""

    COMPACT = "compact"
    STANDARD = "standard"
    HIGH_ASSURANCE = "high_assurance"


class WorkloadAssessment(RouterModel):
    """Evidence-backed complexity signals; intensity is derived, never asserted."""

    change_surface: ChangeSurface
    uncertainty: UncertaintyLevel
    recovery: RecoveryDifficulty
    security_surface: SecuritySurface
    external_effects: ExternalEffectSurface
    evidence_refs: tuple[OpaqueMetadataId, ...] = Field(min_length=1)


_INTENSITY_RANK: dict[WorkflowIntensity, int] = {
    WorkflowIntensity.COMPACT: 0,
    WorkflowIntensity.STANDARD: 1,
    WorkflowIntensity.HIGH_ASSURANCE: 2,
}

_SIGNAL_FLOORS: dict[Enum, WorkflowIntensity] = {
    ChangeSurface.SINGLE_FILE: WorkflowIntensity.COMPACT,
    ChangeSurface.SINGLE_COMPONENT: WorkflowIntensity.COMPACT,
    ChangeSurface.MULTI_COMPONENT: WorkflowIntensity.STANDARD,
    ChangeSurface.CROSS_BOUNDARY: WorkflowIntensity.HIGH_ASSURANCE,
    UncertaintyLevel.ESTABLISHED_PATTERN: WorkflowIntensity.COMPACT,
    UncertaintyLevel.KNOWN_DOMAIN: WorkflowIntensity.STANDARD,
    UncertaintyLevel.NOVEL: WorkflowIntensity.HIGH_ASSURANCE,
    RecoveryDifficulty.REVERSIBLE: WorkflowIntensity.COMPACT,
    RecoveryDifficulty.RECOVERABLE: WorkflowIntensity.STANDARD,
    RecoveryDifficulty.IRREVERSIBLE: WorkflowIntensity.HIGH_ASSURANCE,
    SecuritySurface.NONE: WorkflowIntensity.COMPACT,
    SecuritySurface.UNTRUSTED_INPUT: WorkflowIntensity.STANDARD,
    SecuritySurface.PRIVILEGED: WorkflowIntensity.HIGH_ASSURANCE,
    ExternalEffectSurface.NONE: WorkflowIntensity.COMPACT,
    ExternalEffectSurface.LOCAL_HOST: WorkflowIntensity.STANDARD,
    ExternalEffectSurface.NETWORK_OR_RELEASE: WorkflowIntensity.HIGH_ASSURANCE,
}


def derive_workflow_intensity(assessment: WorkloadAssessment) -> WorkflowIntensity:
    """Return the deterministic maximum floor of every committed signal.

    Intensity can only be derived from a validated assessment; there is no
    override input, so a lower intensity can never be claimed directly.
    """

    trusted = WorkloadAssessment.model_validate(
        assessment.model_dump()
        if isinstance(assessment, WorkloadAssessment)
        else assessment
    )
    floors = (
        _SIGNAL_FLOORS[trusted.change_surface],
        _SIGNAL_FLOORS[trusted.uncertainty],
        _SIGNAL_FLOORS[trusted.recovery],
        _SIGNAL_FLOORS[trusted.security_surface],
        _SIGNAL_FLOORS[trusted.external_effects],
    )
    return max(floors, key=lambda intensity: _INTENSITY_RANK[intensity])


NormalizedGoal.model_rebuild()


class ChangeClass(str, Enum):
    """The declared nature of one change; test exemption is typed, never judged."""

    PRODUCTION_BEHAVIOR = "production_behavior"
    DOCS_ONLY = "docs_only"
    COMMENT_ONLY = "comment_only"
    SCHEMA_VALIDATED_CONFIG = "schema_validated_config"
    TYPE_CHECKED_RENAME = "type_checked_rename"


TEST_EXEMPT_CHANGE_CLASSES: frozenset[ChangeClass] = frozenset(
    {
        ChangeClass.DOCS_ONLY,
        ChangeClass.COMMENT_ONLY,
        ChangeClass.SCHEMA_VALIDATED_CONFIG,
        ChangeClass.TYPE_CHECKED_RENAME,
    }
)


def is_test_exempt(change_class: ChangeClass) -> bool:
    """Fail closed: anything but an exact exempt class member requires tests."""

    if type(change_class) is not ChangeClass:
        return False
    return change_class in TEST_EXEMPT_CHANGE_CLASSES
