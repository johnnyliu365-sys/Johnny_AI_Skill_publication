"""Strong metadata contracts for receipt-bound implementation handoffs."""

from __future__ import annotations

from enum import Enum
from hashlib import sha256
import json
from pathlib import PurePosixPath
from typing import Annotated, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .contracts import (
    BranchFingerprint,
    EvidenceDigest,
    OpaqueMetadataId,
    ProjectId,
    ReviewedCommitReference,
    RevisionDigest,
    WorktreeFingerprint,
)


class _StrictModel(BaseModel):
    """Immutable, extra-free values crossing the supervision boundary."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
        revalidate_instances="always",
    )


SchemaRevision: TypeAlias = Annotated[
    str,
    Field(pattern=r"^[a-z][a-z0-9-]{2,95}-v[1-9][0-9]*$"),
]
CompatibilityRevision: TypeAlias = Annotated[
    str,
    Field(pattern=r"^compatibility-v[1-9][0-9]*$"),
]
ArtifactReference: TypeAlias = Annotated[
    str,
    Field(pattern=r"^doc/handoffs/[A-Za-z0-9._/-]{1,220}$"),
]
HandoffId: TypeAlias = OpaqueMetadataId
HandoffReference: TypeAlias = OpaqueMetadataId
SpecReference: TypeAlias = OpaqueMetadataId
TicketReference: TypeAlias = OpaqueMetadataId
ReceiptReference: TypeAlias = OpaqueMetadataId
RoleReference: TypeAlias = OpaqueMetadataId
TaskReference: TypeAlias = OpaqueMetadataId
CorrelationId: TypeAlias = OpaqueMetadataId
EvidenceReference: TypeAlias = OpaqueMetadataId
ArtifactId: TypeAlias = OpaqueMetadataId
ProtocolId: TypeAlias = OpaqueMetadataId
CapabilityReference: TypeAlias = OpaqueMetadataId
ContentDigest: TypeAlias = EvidenceDigest
CommitId: TypeAlias = ReviewedCommitReference


class ImplementationTerminalKind(str, Enum):
    """Finite implementation outcomes that may seal a handoff leaf."""

    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    CHANGE_DETECTED = "CHANGE_DETECTED"


class ArtifactKind(str, Enum):
    """Finite nodes in the target-owned handoff index tree."""

    PARTITION_INDEX = "PARTITION_INDEX"
    FEATURE_INDEX = "FEATURE_INDEX"
    TICKET_INDEX = "TICKET_INDEX"
    HANDOFF_LEAF = "HANDOFF_LEAF"


class ArtifactLifecycle(str, Enum):
    """Finite lifecycle of one indexed handoff artifact."""

    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


class ObservedControlPlaneState(str, Enum):
    """Historical, non-authoritative control-plane observation."""

    ATTACHED = "ATTACHED"
    DETACHING = "DETACHING"
    DETACHED = "DETACHED"
    ADOPTING = "ADOPTING"


class HandoffValidationStatus(str, Enum):
    """Finite trusted handoff validation result."""

    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class HandoffValidationFailure(str, Enum):
    """Sanitized failure meanings; untrusted leaf text never escapes."""

    INVALID_CONTRACT = "INVALID_CONTRACT"
    PROJECT_MISMATCH = "PROJECT_MISMATCH"
    SPEC_MISMATCH = "SPEC_MISMATCH"
    TICKET_MISMATCH = "TICKET_MISMATCH"
    RECEIPT_MISMATCH = "RECEIPT_MISMATCH"
    SOURCE_ROLE_MISMATCH = "SOURCE_ROLE_MISMATCH"
    SOURCE_TASK_MISMATCH = "SOURCE_TASK_MISMATCH"
    TARGET_ROLE_MISMATCH = "TARGET_ROLE_MISMATCH"
    TARGET_TASK_MISMATCH = "TARGET_TASK_MISMATCH"
    WORKTREE_MISMATCH = "WORKTREE_MISMATCH"
    BRANCH_MISMATCH = "BRANCH_MISMATCH"
    BASELINE_MISMATCH = "BASELINE_MISMATCH"
    CORRELATION_MISMATCH = "CORRELATION_MISMATCH"
    RESULT_ANCESTRY_INVALID = "RESULT_ANCESTRY_INVALID"
    HANDOFF_ANCESTRY_INVALID = "HANDOFF_ANCESTRY_INVALID"
    RESERVED_PATH_NOT_CHANGED = "RESERVED_PATH_NOT_CHANGED"
    REPLAY = "REPLAY"


class HandoffLeafBody(_StrictModel):
    """Digestable handoff body written by one implementation owner."""

    handoff_id: HandoffId
    schema_revision: SchemaRevision
    project_id: ProjectId
    spec_ref: SpecReference
    spec_revision: RevisionDigest
    ticket_ref: TicketReference
    ticket_revision: RevisionDigest
    router_receipt_ref: ReceiptReference
    source_role_ref: RoleReference
    source_task_ref: TaskReference
    target_role_ref: RoleReference
    target_task_ref: TaskReference | None
    worktree_ref: WorktreeFingerprint
    branch_ref: BranchFingerprint
    baseline_commit: CommitId
    result_commit: CommitId
    terminal_kind: ImplementationTerminalKind
    previous_handoff_ref: HandoffReference | None
    supersedes_ref: HandoffReference | None
    evidence_refs: tuple[EvidenceReference, ...] = Field(min_length=1)
    correlation_id: CorrelationId

    @model_validator(mode="after")
    def provenance_shape_is_finite(self) -> Self:
        if self.source_role_ref == self.target_role_ref:
            raise ValueError("source and target roles must differ")
        if self.baseline_commit == self.result_commit:
            raise ValueError("result commit must differ from baseline")
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("evidence references must be unique")
        if self.handoff_id in (self.previous_handoff_ref, self.supersedes_ref):
            raise ValueError("handoff correction references cannot point to self")
        if self.supersedes_ref is not None and self.previous_handoff_ref is None:
            raise ValueError("a superseding handoff must retain its previous handoff edge")
        return self


def derive_handoff_content_digest(body: HandoffLeafBody) -> ContentDigest:
    """Hash a canonical body without accepting caller-selected serialization."""

    canonical = json.dumps(
        body.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256_" + sha256(canonical).hexdigest()


class HandoffLeaf(HandoffLeafBody):
    """Sealed terminal handoff whose digest covers every body field."""

    content_digest: ContentDigest

    @model_validator(mode="after")
    def content_digest_is_exact(self) -> Self:
        body = HandoffLeafBody.model_validate(
            self.model_dump(exclude={"content_digest"}),
            strict=True,
        )
        if self.content_digest != derive_handoff_content_digest(body):
            raise ValueError("handoff content digest does not match its canonical body")
        return self


def seal_handoff_leaf(body: HandoffLeafBody) -> HandoffLeaf:
    """Create a sealed leaf only from a fully revalidated body."""

    validated = HandoffLeafBody.model_validate(body, strict=True)
    return HandoffLeaf(
        **validated.model_dump(),
        content_digest=derive_handoff_content_digest(validated),
    )


class HandoffChildRef(_StrictModel):
    """One direct-child index edge with no copied child body."""

    child_id: ArtifactId
    child_kind: ArtifactKind
    revision: RevisionDigest
    content_digest: ContentDigest
    lifecycle: ArtifactLifecycle
    target_ref: ArtifactReference

    @model_validator(mode="after")
    def target_ref_is_canonical(self) -> Self:
        path = PurePosixPath(self.target_ref)
        if ".." in path.parts or "." in path.parts:
            raise ValueError("artifact references must be normalized")
        if self.child_kind is ArtifactKind.HANDOFF_LEAF:
            if path.suffix != ".json" or path.name == "index.json":
                raise ValueError("handoff leaves must identify one JSON leaf")
        elif path.name != "index.json":
            raise ValueError("index child kinds must identify an index.json")
        return self


def _is_direct_child(index_ref: ArtifactReference, child: HandoffChildRef) -> bool:
    index_parent = PurePosixPath(index_ref).parent
    child_path = PurePosixPath(child.target_ref)
    try:
        relative = child_path.relative_to(index_parent)
    except ValueError:
        return False
    if child.child_kind is ArtifactKind.HANDOFF_LEAF:
        return len(relative.parts) == 1
    return len(relative.parts) == 2 and relative.parts[-1] == "index.json"


class HandoffIndex(_StrictModel):
    """One tree index containing direct children only."""

    index_id: ArtifactId
    index_ref: ArtifactReference
    revision: RevisionDigest
    direct_child_refs: tuple[HandoffChildRef, ...]

    @model_validator(mode="after")
    def children_are_unique_and_direct(self) -> Self:
        if PurePosixPath(self.index_ref).name != "index.json":
            raise ValueError("handoff index reference must end with index.json")
        child_ids = tuple(child.child_id for child in self.direct_child_refs)
        child_targets = tuple(child.target_ref for child in self.direct_child_refs)
        if len(child_ids) != len(set(child_ids)):
            raise ValueError("direct child identifiers must be unique")
        if len(child_targets) != len(set(child_targets)):
            raise ValueError("direct child targets must be unique")
        if not all(_is_direct_child(self.index_ref, child) for child in self.direct_child_refs):
            raise ValueError("indexes may contain direct children only")
        return self


class HandoffRootManifest(_StrictModel):
    """Plugin-neutral target-owned adoption and provenance manifest."""

    project_id: ProjectId
    handoff_protocol_id: ProtocolId
    schema_revision: SchemaRevision
    minimum_compatible_revision: CompatibilityRevision
    manifest_revision: RevisionDigest
    direct_child_refs: tuple[HandoffChildRef, ...]
    active_leaf_refs: tuple[HandoffChildRef, ...]
    minimum_adoption_capabilities: tuple[CapabilityReference, ...] = Field(min_length=1)
    last_observed_control_plane_state: ObservedControlPlaneState
    last_observation_revision: RevisionDigest
    last_non_replayable_receipt_ref: ReceiptReference | None

    @model_validator(mode="after")
    def manifest_is_metadata_only(self) -> Self:
        direct_ids = tuple(child.child_id for child in self.direct_child_refs)
        active_ids = tuple(child.child_id for child in self.active_leaf_refs)
        capabilities = self.minimum_adoption_capabilities
        if len(direct_ids) != len(set(direct_ids)):
            raise ValueError("manifest direct children must be unique")
        if len(active_ids) != len(set(active_ids)):
            raise ValueError("manifest active leaf identifiers must be unique")
        if len(capabilities) != len(set(capabilities)):
            raise ValueError("minimum adoption capabilities must be unique")
        if not all(
            child.child_kind is ArtifactKind.HANDOFF_LEAF
            for child in self.active_leaf_refs
        ):
            raise ValueError("active leaf references must identify handoff leaves")
        if not all(
            child.child_kind is ArtifactKind.PARTITION_INDEX
            and _is_direct_child("doc/handoffs/index.json", child)
            for child in self.direct_child_refs
        ):
            raise ValueError("root manifest direct children must be partition indexes")
        serialized_metadata = "|".join(
            (
                self.handoff_protocol_id,
                *capabilities,
                *(child.target_ref for child in self.direct_child_refs),
                *(child.target_ref for child in self.active_leaf_refs),
            )
        ).casefold()
        if any(marker in serialized_metadata for marker in ("johnny", "prompt", "secret", "://", "\\")):
            raise ValueError("root manifest must remain plugin-neutral metadata")
        return self


class HandoffAdmissionContext(_StrictModel):
    """Trusted exact bindings and Git ancestry observations for one leaf."""

    project_id: ProjectId
    spec_ref: SpecReference
    spec_revision: RevisionDigest
    ticket_ref: TicketReference
    ticket_revision: RevisionDigest
    router_receipt_ref: ReceiptReference
    source_role_ref: RoleReference
    source_task_ref: TaskReference
    target_role_ref: RoleReference
    target_task_ref: TaskReference | None
    worktree_ref: WorktreeFingerprint
    branch_ref: BranchFingerprint
    baseline_commit: CommitId
    correlation_id: CorrelationId
    observed_handoff_commit: CommitId
    result_descends_from_baseline: bool
    handoff_descends_from_result: bool
    reserved_path_changed: bool
    consumed_handoff_ids: tuple[HandoffId, ...]

    @model_validator(mode="after")
    def consumed_ids_are_unique(self) -> Self:
        if len(self.consumed_handoff_ids) != len(set(self.consumed_handoff_ids)):
            raise ValueError("consumed handoff identifiers must be unique")
        return self


class HandoffValidationResult(_StrictModel):
    """Exactly one trusted leaf or one sanitized rejection."""

    status: HandoffValidationStatus
    leaf: HandoffLeaf | None = None
    failure: HandoffValidationFailure | None = None

    @model_validator(mode="after")
    def exact_leaf_or_failure(self) -> Self:
        if self.status is HandoffValidationStatus.ACCEPTED:
            if self.leaf is None or self.failure is not None:
                raise ValueError("accepted validation requires one leaf and no failure")
            return self
        if self.leaf is not None or self.failure is None:
            raise ValueError("rejected validation requires one failure and no leaf")
        return self


def _rejected(failure: HandoffValidationFailure) -> HandoffValidationResult:
    return HandoffValidationResult(
        status=HandoffValidationStatus.REJECTED,
        failure=failure,
    )


def validate_handoff_leaf(
    leaf: HandoffLeaf,
    context: HandoffAdmissionContext,
) -> HandoffValidationResult:
    """Revalidate and compare every receipt-bound leaf field fail-closed."""

    if type(leaf) is not HandoffLeaf or type(context) is not HandoffAdmissionContext:
        return _rejected(HandoffValidationFailure.INVALID_CONTRACT)
    try:
        validated_leaf = HandoffLeaf.model_validate(leaf, strict=True)
        trusted = HandoffAdmissionContext.model_validate(context, strict=True)
    except ValidationError:
        return _rejected(HandoffValidationFailure.INVALID_CONTRACT)

    comparisons = (
        (validated_leaf.project_id == trusted.project_id, HandoffValidationFailure.PROJECT_MISMATCH),
        (
            validated_leaf.spec_ref == trusted.spec_ref
            and validated_leaf.spec_revision == trusted.spec_revision,
            HandoffValidationFailure.SPEC_MISMATCH,
        ),
        (
            validated_leaf.ticket_ref == trusted.ticket_ref
            and validated_leaf.ticket_revision == trusted.ticket_revision,
            HandoffValidationFailure.TICKET_MISMATCH,
        ),
        (
            validated_leaf.router_receipt_ref == trusted.router_receipt_ref,
            HandoffValidationFailure.RECEIPT_MISMATCH,
        ),
        (
            validated_leaf.source_role_ref == trusted.source_role_ref,
            HandoffValidationFailure.SOURCE_ROLE_MISMATCH,
        ),
        (
            validated_leaf.source_task_ref == trusted.source_task_ref,
            HandoffValidationFailure.SOURCE_TASK_MISMATCH,
        ),
        (
            validated_leaf.target_role_ref == trusted.target_role_ref,
            HandoffValidationFailure.TARGET_ROLE_MISMATCH,
        ),
        (
            validated_leaf.target_task_ref == trusted.target_task_ref,
            HandoffValidationFailure.TARGET_TASK_MISMATCH,
        ),
        (
            validated_leaf.worktree_ref == trusted.worktree_ref,
            HandoffValidationFailure.WORKTREE_MISMATCH,
        ),
        (
            validated_leaf.branch_ref == trusted.branch_ref,
            HandoffValidationFailure.BRANCH_MISMATCH,
        ),
        (
            validated_leaf.baseline_commit == trusted.baseline_commit,
            HandoffValidationFailure.BASELINE_MISMATCH,
        ),
        (
            validated_leaf.correlation_id == trusted.correlation_id,
            HandoffValidationFailure.CORRELATION_MISMATCH,
        ),
        (
            trusted.result_descends_from_baseline,
            HandoffValidationFailure.RESULT_ANCESTRY_INVALID,
        ),
        (
            trusted.handoff_descends_from_result,
            HandoffValidationFailure.HANDOFF_ANCESTRY_INVALID,
        ),
        (
            trusted.reserved_path_changed,
            HandoffValidationFailure.RESERVED_PATH_NOT_CHANGED,
        ),
        (
            validated_leaf.handoff_id not in trusted.consumed_handoff_ids,
            HandoffValidationFailure.REPLAY,
        ),
    )
    for accepted, failure in comparisons:
        if not accepted:
            return _rejected(failure)
    return HandoffValidationResult(
        status=HandoffValidationStatus.ACCEPTED,
        leaf=validated_leaf,
    )


def validate_handoff_leaf_json(
    payload: str,
    context: HandoffAdmissionContext,
) -> HandoffValidationResult:
    """Normalize dynamic JSON into a strong leaf before trusted validation."""

    if type(payload) is not str:
        return _rejected(HandoffValidationFailure.INVALID_CONTRACT)
    try:
        leaf = HandoffLeaf.model_validate_json(payload, strict=True)
    except ValidationError:
        return _rejected(HandoffValidationFailure.INVALID_CONTRACT)
    return validate_handoff_leaf(leaf, context)


__all__ = [
    "ArtifactKind",
    "ArtifactLifecycle",
    "ArtifactReference",
    "CapabilityReference",
    "CompatibilityRevision",
    "ContentDigest",
    "HandoffAdmissionContext",
    "HandoffChildRef",
    "HandoffId",
    "HandoffIndex",
    "HandoffLeaf",
    "HandoffLeafBody",
    "HandoffRootManifest",
    "HandoffValidationFailure",
    "HandoffValidationResult",
    "HandoffValidationStatus",
    "ImplementationTerminalKind",
    "ObservedControlPlaneState",
    "SchemaRevision",
    "derive_handoff_content_digest",
    "seal_handoff_leaf",
    "validate_handoff_leaf",
    "validate_handoff_leaf_json",
]
