"""Strong contracts for bounded target-owned document transactions."""

from __future__ import annotations

from enum import Enum
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Annotated, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import EvidenceDigest, ProjectId, ReviewedCommitReference
from .role_supervision_contracts import (
    CompatibilityRevision,
    HandoffLeaf,
    ObservedControlPlaneState,
    ProtocolId,
    SchemaRevision,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=False,
        revalidate_instances="always",
    )


TargetRelativePath: TypeAlias = Annotated[
    str,
    Field(
        pattern=(
            r"^(?:README\.md|PRD\.md|CONTEXT\.md|ProjectSchedule\.md|"
            r"doc/[A-Za-z0-9._/-]{1,220}|modules/[A-Za-z0-9._/-]{1,220})$"
        )
    ),
]
ContentDigest: TypeAlias = EvidenceDigest
FeatureSlug: TypeAlias = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{1,63}$")]
TicketSlug: TypeAlias = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{2,95}$")]
Year: TypeAlias = Annotated[int, Field(ge=2000, le=9999)]


class ArtifactDocumentKind(str, Enum):
    ROOT_README = "ROOT_README"
    REQUIREMENT = "REQUIREMENT"
    REQUIREMENT_CHANGE = "REQUIREMENT_CHANGE"
    CONTEXT = "CONTEXT"
    GRILL_CONTEXT = "GRILL_CONTEXT"
    SPECIFICATION = "SPECIFICATION"
    TICKET = "TICKET"
    IMPLEMENTATION_EVIDENCE = "IMPLEMENTATION_EVIDENCE"
    REVIEW = "REVIEW"
    HANDOFF_README = "HANDOFF_README"
    HANDOFF_INDEX = "HANDOFF_INDEX"
    HANDOFF_LEAF = "HANDOFF_LEAF"


class DocumentMutationMode(str, Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"


class DocumentWriteStatus(str, Enum):
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class DocumentWriteFailure(str, Enum):
    BASELINE_MISMATCH = "BASELINE_MISMATCH"
    PATH_STATE_MISMATCH = "PATH_STATE_MISMATCH"
    PATH_ESCAPE = "PATH_ESCAPE"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


def derive_document_digest(content: str) -> ContentDigest:
    if type(content) is not str:
        raise TypeError("document content must be exact text")
    canonical = content.replace("\r\n", "\n").replace("\r", "\n")
    return "sha256_" + sha256(canonical.encode("utf-8")).hexdigest()


class TargetDocumentMutation(_StrictModel):
    """One exact create/update with compare-and-swap content identity."""

    path: TargetRelativePath
    artifact_kind: ArtifactDocumentKind
    mode: DocumentMutationMode
    expected_current_digest: ContentDigest | None
    content: str = Field(min_length=1)
    content_digest: ContentDigest
    sealed: bool

    @model_validator(mode="after")
    def mutation_is_safe_and_exact(self) -> Self:
        path = PurePosixPath(self.path)
        if path.is_absolute() or ".." in path.parts or "." in path.parts:
            raise ValueError("target document path must be normalized and relative")
        lowered_parts = tuple(part.casefold() for part in path.parts)
        if any(
            part in (".git", ".codex", ".codex-plugin", ".claude-plugin")
            for part in lowered_parts
        ):
            raise ValueError("target transaction cannot write control-plane paths")
        if self.content_digest != derive_document_digest(self.content):
            raise ValueError("document digest must match exact UTF-8 content")
        if "\r" in self.content:
            raise ValueError("document mutations must use canonical LF newlines")
        if self.mode is DocumentMutationMode.CREATE:
            if self.expected_current_digest is not None:
                raise ValueError("create mutation requires an absent target")
        elif self.expected_current_digest is None:
            raise ValueError("update mutation requires an exact current digest")
        if self.sealed and self.mode is not DocumentMutationMode.CREATE:
            raise ValueError("sealed artifacts can only be created")
        if self.artifact_kind is ArtifactDocumentKind.HANDOFF_LEAF and not self.sealed:
            raise ValueError("handoff leaves must be sealed")
        return self


class TargetDocumentPlan(_StrictModel):
    """One project/baseline transaction over a finite explicit path set."""

    project_id: ProjectId
    baseline_commit: ReviewedCommitReference
    mutations: tuple[TargetDocumentMutation, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def paths_are_unique(self) -> Self:
        paths = tuple(mutation.path for mutation in self.mutations)
        if len(paths) != len(set(paths)):
            raise ValueError("one target document plan cannot repeat a path")
        return self


class DocumentWriteResult(_StrictModel):
    status: DocumentWriteStatus
    written_paths: tuple[TargetRelativePath, ...] = ()
    written_digests: tuple[ContentDigest, ...] = ()
    failure: DocumentWriteFailure | None = None

    @model_validator(mode="after")
    def exact_result_shape(self) -> Self:
        if self.status is DocumentWriteStatus.APPLIED:
            if (
                not self.written_paths
                or len(self.written_paths) != len(self.written_digests)
                or self.failure is not None
            ):
                raise ValueError("applied transaction requires exact written identities")
        elif self.written_paths or self.written_digests or self.failure is None:
            raise ValueError("rejected transaction returns only one failure")
        return self


class HandoffTreeBootstrapRequest(_StrictModel):
    """Inputs for a plugin-neutral project-owned handoff tree."""

    project_id: ProjectId
    baseline_commit: ReviewedCommitReference
    year: Year
    feature_slug: FeatureSlug
    ticket_slug: TicketSlug
    leaf: HandoffLeaf
    root_readme_content: str = Field(min_length=1)
    root_readme_digest: ContentDigest
    spec_path: TargetRelativePath
    protocol_id: ProtocolId
    schema_revision: SchemaRevision
    compatibility_revision: CompatibilityRevision
    minimum_adoption_capabilities: tuple[str, ...] = Field(min_length=1)
    control_plane_state: ObservedControlPlaneState

    @model_validator(mode="after")
    def bootstrap_bindings_are_exact(self) -> Self:
        if self.leaf.project_id != self.project_id:
            raise ValueError("handoff leaf must belong to the bootstrap project")
        if self.root_readme_digest != derive_document_digest(self.root_readme_content):
            raise ValueError("root README digest must match its exact current content")
        if not self.spec_path.startswith("modules/spec/"):
            raise ValueError("handoff README must link one target-owned SPEC")
        if len(self.minimum_adoption_capabilities) != len(
            set(self.minimum_adoption_capabilities)
        ):
            raise ValueError("minimum adoption capabilities must be unique")
        for capability in self.minimum_adoption_capabilities:
            if (
                not capability
                or capability != capability.strip()
                or any(marker in capability.casefold() for marker in ("/", "\\", "://", "plugin"))
            ):
                raise ValueError("adoption capabilities must be opaque plugin-neutral IDs")
        return self


__all__ = [
    "ArtifactDocumentKind",
    "ContentDigest",
    "DocumentMutationMode",
    "DocumentWriteFailure",
    "DocumentWriteResult",
    "DocumentWriteStatus",
    "HandoffTreeBootstrapRequest",
    "TargetDocumentMutation",
    "TargetDocumentPlan",
    "TargetRelativePath",
    "derive_document_digest",
]
