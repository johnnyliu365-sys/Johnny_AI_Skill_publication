"""Metadata-only policy reads and Router-owned fixed dispatch responses.

The policy source is an ephemeral boundary.  It may provide a typed metadata
record, but document text is never accepted by, returned from, or stored in a
Router model.  Dispatch text is rendered only from a live plan retained by the
same :class:`PrivateRouterClient` that received the pending dispatch.
"""

from __future__ import annotations

from enum import Enum
from typing import Protocol

from pydantic import TypeAdapter, ValidationError, model_validator

from .contracts import (
    EvidenceDigest,
    NonBlankText,
    OpaqueMetadataId,
    PendingDispatchDescriptor,
    ProjectId,
    RevisionDigest,
    ReviewedCommitReference,
    RouterModel,
)

CommitReference = ReviewedCommitReference
_PROJECT_ID_ADAPTER = TypeAdapter(ProjectId)


def _validated_project_id(value: object) -> ProjectId | None:
    """Normalize one untrusted project identity or fail closed before lookup."""

    try:
        return _PROJECT_ID_ADAPTER.validate_python(value, strict=True)
    except ValidationError:
        return None


class PolicyReadOutcome(str, Enum):
    """Finite outcome of an ephemeral policy metadata read."""

    LOADED = "loaded"
    HALT = "halt"


class PolicyReadError(str, Enum):
    """Stable errors that never echo source or exception detail."""

    SOURCE_UNAVAILABLE = "source_unavailable"
    SOURCE_FAILURE = "source_failure"
    INVALID_DOCUMENT = "invalid_document"


class PolicyDocumentMetadata(RouterModel):
    """The only policy information allowed to cross the source boundary."""

    source_id: OpaqueMetadataId
    revision: RevisionDigest
    evidence_digest: EvidenceDigest


class PolicyDocumentSource(Protocol):
    """Ephemeral source port; implementations must return typed metadata."""

    def read(self) -> object:
        """Read a document transiently without returning its text to the Router."""


class PolicyDocumentResult(RouterModel):
    """Metadata-only result; deliberately has no text or arbitrary detail field."""

    outcome: PolicyReadOutcome
    metadata: PolicyDocumentMetadata | None = None
    error: PolicyReadError | None = None

    @model_validator(mode="after")
    def result_shape_is_unambiguous(self) -> PolicyDocumentResult:
        """Require a metadata record on success and a stable error on halt."""

        if self.outcome is PolicyReadOutcome.LOADED:
            if self.metadata is None or self.error is not None:
                raise ValueError("loaded policy result requires metadata only")
        elif self.metadata is not None or self.error is None:
            raise ValueError("halted policy result requires one stable error")
        return self


def read_policy_document(source: PolicyDocumentSource | None) -> PolicyDocumentResult:
    """Read only allowlisted policy metadata and fail closed for every other value."""

    if source is None:
        return PolicyDocumentResult(
            outcome=PolicyReadOutcome.HALT,
            error=PolicyReadError.SOURCE_UNAVAILABLE,
        )
    try:
        result = source.read()
    except Exception:
        return PolicyDocumentResult(
            outcome=PolicyReadOutcome.HALT,
            error=PolicyReadError.SOURCE_FAILURE,
        )
    if not isinstance(result, PolicyDocumentMetadata):
        return PolicyDocumentResult(
            outcome=PolicyReadOutcome.HALT,
            error=PolicyReadError.INVALID_DOCUMENT,
        )
    return PolicyDocumentResult(outcome=PolicyReadOutcome.LOADED, metadata=result)


class RenderOutcome(str, Enum):
    """Finite formatter outcomes."""

    RENDERED = "rendered"
    HALT = "halt"


class RenderError(str, Enum):
    """Stable response errors with no free-form detail."""

    UNTRUSTED_RESPONSE = "untrusted_response"
    INVALID_RESPONSE = "invalid_response"
    ARTIFACT_MISMATCH = "artifact_mismatch"
    FORMATTER_FAILURE = "formatter_failure"
    FORMATTER_OUTPUT_INVALID = "formatter_output_invalid"


class CommittedDispatchArtifacts(RouterModel):
    """Metadata references for the reviewed ticket and handoff documents."""

    ticket_docs_commit: CommitReference
    ticket_reference: OpaqueMetadataId
    handoff_docs_commit: CommitReference
    handoff_reference: OpaqueMetadataId


class ApprovedDispatchArtifact(RouterModel):
    """One reviewed ticket/handoff artifact set authorized by the control plane."""

    project_id: ProjectId
    ticket_reference: OpaqueMetadataId
    handoff_reference: OpaqueMetadataId
    implementation_owner_id: OpaqueMetadataId
    ticket_docs_commit: CommitReference
    handoff_docs_commit: CommitReference


class ApprovedDispatchArtifactRegistry(Protocol):
    """Private Router registry for exact reviewed dispatch artifacts."""

    def resolve(
        self,
        *,
        project_id: ProjectId,
        ticket_reference: OpaqueMetadataId,
        handoff_reference: OpaqueMetadataId,
        implementation_owner_id: OpaqueMetadataId,
    ) -> ApprovedDispatchArtifact | None:
        """Resolve one exact ticket, handoff, and named owner identity."""


class StaticApprovedDispatchArtifactRegistry:
    """Small typed registry used by the private boundary and deterministic tests."""

    def __init__(self, *, records: tuple[ApprovedDispatchArtifact, ...]) -> None:
        identities = tuple(
            (
                record.project_id,
                record.ticket_reference,
                record.handoff_reference,
                record.implementation_owner_id,
            )
            for record in records
        )
        if len(set(identities)) != len(identities):
            raise ValueError("approved dispatch artifact identities must be unique")
        self._records = records

    def resolve(
        self,
        *,
        project_id: ProjectId,
        ticket_reference: OpaqueMetadataId,
        handoff_reference: OpaqueMetadataId,
        implementation_owner_id: OpaqueMetadataId,
    ) -> ApprovedDispatchArtifact | None:
        """Return only the record with an exact authorized identity tuple."""

        validated_project_id = _validated_project_id(project_id)
        if validated_project_id is None:
            return None
        for record in self._records:
            if (
                record.project_id == validated_project_id
                and record.ticket_reference == ticket_reference
                and record.handoff_reference == handoff_reference
                and record.implementation_owner_id == implementation_owner_id
            ):
                return record
        return None


def resolve_approved_dispatch_artifact(
    registry: ApprovedDispatchArtifactRegistry,
    *,
    project_id: ProjectId,
    ticket_reference: OpaqueMetadataId,
    handoff_reference: OpaqueMetadataId,
    implementation_owner_id: OpaqueMetadataId,
    ticket_docs_commit: CommitReference | None,
    handoff_docs_commit: CommitReference | None,
) -> ApprovedDispatchArtifact | None:
    """Require both identity and reviewed commit metadata to match the registry."""

    validated_project_id = _validated_project_id(project_id)
    if (
        validated_project_id is None
        or ticket_docs_commit is None
        or handoff_docs_commit is None
    ):
        return None
    record = registry.resolve(
        project_id=validated_project_id,
        ticket_reference=ticket_reference,
        handoff_reference=handoff_reference,
        implementation_owner_id=implementation_owner_id,
    )
    if record is None:
        return None
    if (
        record.ticket_docs_commit != ticket_docs_commit
        or record.handoff_docs_commit != handoff_docs_commit
    ):
        return None
    return record


class FixedDispatchResponse(RouterModel):
    """A response candidate bound to one Router-created pending descriptor."""

    pending_dispatch: PendingDispatchDescriptor
    ticket_docs_commit: CommitReference
    ticket_reference: OpaqueMetadataId
    handoff_docs_commit: CommitReference
    handoff_reference: OpaqueMetadataId
    implementation_owner_id: OpaqueMetadataId

    @model_validator(mode="after")
    def binds_exact_pending_dispatch(self) -> FixedDispatchResponse:
        """Prevent arbitrary ticket, handoff, or owner substitutions."""

        pending = self.pending_dispatch
        if (
            pending.ticket_docs_commit is None
            or pending.handoff_docs_commit is None
            or self.ticket_reference != pending.ticket_reference
            or self.handoff_reference != pending.reviewed_handoff_reference
            or self.implementation_owner_id != pending.implementation_owner_id
            or self.ticket_docs_commit != pending.ticket_docs_commit
            or self.handoff_docs_commit != pending.handoff_docs_commit
        ):
            raise ValueError("fixed response must match the pending dispatch descriptor")
        return self


class RenderedDispatchResponse(RouterModel):
    """The only response result exposed to the caller."""

    outcome: RenderOutcome
    text: NonBlankText | None = None
    error: RenderError | None = None

    @model_validator(mode="after")
    def output_shape_is_safe(self) -> RenderedDispatchResponse:
        """Never expose text together with a halt or omit text after rendering."""

        if self.outcome is RenderOutcome.RENDERED:
            if self.text is None or self.error is not None:
                raise ValueError("rendered response requires text only")
        elif self.text is not None or self.error is None:
            raise ValueError("halted response requires one stable error")
        return self


class DispatchResponseFormatter:
    """Deterministic formatter for a validated Router-owned response candidate."""

    def format(self, response: FixedDispatchResponse) -> str:
        """Return the fixed response shape and no source-derived content."""

        return (
            "工單 ready\n"
            f"- commit：{response.ticket_docs_commit}\n"
            f"- 工單：{response.ticket_reference}\n\n"
            "文件交接\n"
            f"- commit：{response.handoff_docs_commit}\n"
            f"- implementation owner：{response.implementation_owner_id}\n"
            f"- 工單 {response.ticket_reference} 是否已交付給 implementation owner "
            f"{response.implementation_owner_id}？"
        )


def _halt(error: RenderError) -> RenderedDispatchResponse:
    return RenderedDispatchResponse(outcome=RenderOutcome.HALT, error=error)


def render_dispatch_response(
    response: object,
    formatter: DispatchResponseFormatter | None = None,
) -> RenderedDispatchResponse:
    """Reject direct rendering; a live Private Router client is the authority."""

    del response, formatter
    return _halt(RenderError.UNTRUSTED_RESPONSE)


def render_trusted_dispatch_response(
    *,
    client: object,
    plan: object,
    artifacts: CommittedDispatchArtifacts | None = None,
    formatter: DispatchResponseFormatter | None = None,
) -> RenderedDispatchResponse:
    """Reject indirect rendering; ownership is checked inside PrivateRouterClient."""

    del client, plan, artifacts, formatter
    return _halt(RenderError.UNTRUSTED_RESPONSE)
