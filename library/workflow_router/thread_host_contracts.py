"""Strict metadata contracts for receipt-bound Codex thread host binding."""

from __future__ import annotations

from enum import Enum
from hashlib import sha256
from typing import Annotated, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import (
    BranchFingerprint,
    EvidenceDigest,
    OpaqueMetadataId,
    ProjectId,
    WorktreeFingerprint,
)


CodexTaskId: TypeAlias = Annotated[
    str,
    Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
]
CodexThreadId: TypeAlias = CodexTaskId
CodexHostId: TypeAlias = Annotated[
    str,
    Field(pattern=r"^[a-z0-9][a-z0-9:_-]{0,127}$"),
]
CodexProjectId: TypeAlias = Annotated[
    str,
    Field(
        pattern=(
            r"^(?:local-[0-9a-f]{32}|"
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
        )
    ),
]
HostObservationDigest: TypeAlias = EvidenceDigest


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
    )


class CodexThreadActivity(str, Enum):
    """Finite activity states returned by the Codex task directory."""

    ACTIVE = "active"
    IDLE = "idle"
    NOT_LOADED = "notLoaded"


class ThreadHostResolutionStatus(str, Enum):
    """Finite outcomes before the exact thread readback call."""

    RESOLVED = "RESOLVED"
    DIRECTORY_UNAVAILABLE = "DIRECTORY_UNAVAILABLE"
    DIRECTORY_PAYLOAD_INVALID = "DIRECTORY_PAYLOAD_INVALID"
    THREAD_NOT_FOUND = "THREAD_NOT_FOUND"
    AMBIGUOUS_THREAD = "AMBIGUOUS_THREAD"
    PROJECT_REQUIRED = "PROJECT_REQUIRED"
    PROJECT_MISMATCH = "PROJECT_MISMATCH"
    WORKSPACE_MISMATCH = "WORKSPACE_MISMATCH"
    HOST_UNAVAILABLE = "HOST_UNAVAILABLE"
    THREAD_NOT_READY = "THREAD_NOT_READY"


class ThreadHostResolutionFailure(str, Enum):
    """Finite failures before exact thread readback."""

    DIRECTORY_UNAVAILABLE = "DIRECTORY_UNAVAILABLE"
    DIRECTORY_PAYLOAD_INVALID = "DIRECTORY_PAYLOAD_INVALID"
    THREAD_NOT_FOUND = "THREAD_NOT_FOUND"
    AMBIGUOUS_THREAD = "AMBIGUOUS_THREAD"
    PROJECT_REQUIRED = "PROJECT_REQUIRED"
    PROJECT_MISMATCH = "PROJECT_MISMATCH"
    WORKSPACE_MISMATCH = "WORKSPACE_MISMATCH"
    HOST_UNAVAILABLE = "HOST_UNAVAILABLE"
    THREAD_NOT_READY = "THREAD_NOT_READY"


class ThreadHostBindingStatus(str, Enum):
    """Finite outcomes after exact thread readback."""

    BOUND = "BOUND"
    DIRECTORY_UNAVAILABLE = "DIRECTORY_UNAVAILABLE"
    DIRECTORY_PAYLOAD_INVALID = "DIRECTORY_PAYLOAD_INVALID"
    THREAD_NOT_FOUND = "THREAD_NOT_FOUND"
    AMBIGUOUS_THREAD = "AMBIGUOUS_THREAD"
    PROJECT_REQUIRED = "PROJECT_REQUIRED"
    PROJECT_MISMATCH = "PROJECT_MISMATCH"
    WORKSPACE_MISMATCH = "WORKSPACE_MISMATCH"
    HOST_UNAVAILABLE = "HOST_UNAVAILABLE"
    THREAD_NOT_READY = "THREAD_NOT_READY"
    READBACK_UNAVAILABLE = "READBACK_UNAVAILABLE"
    READBACK_PAYLOAD_INVALID = "READBACK_PAYLOAD_INVALID"
    READBACK_MISMATCH = "READBACK_MISMATCH"


class ThreadHostBindingFailure(str, Enum):
    """Finite failures after exact thread readback."""

    DIRECTORY_UNAVAILABLE = "DIRECTORY_UNAVAILABLE"
    DIRECTORY_PAYLOAD_INVALID = "DIRECTORY_PAYLOAD_INVALID"
    THREAD_NOT_FOUND = "THREAD_NOT_FOUND"
    AMBIGUOUS_THREAD = "AMBIGUOUS_THREAD"
    PROJECT_REQUIRED = "PROJECT_REQUIRED"
    PROJECT_MISMATCH = "PROJECT_MISMATCH"
    WORKSPACE_MISMATCH = "WORKSPACE_MISMATCH"
    HOST_UNAVAILABLE = "HOST_UNAVAILABLE"
    THREAD_NOT_READY = "THREAD_NOT_READY"
    READBACK_UNAVAILABLE = "READBACK_UNAVAILABLE"
    READBACK_PAYLOAD_INVALID = "READBACK_PAYLOAD_INVALID"
    READBACK_MISMATCH = "READBACK_MISMATCH"


class CodexThreadHostProbeTarget(_StrictModel):
    """Metadata-only target selected from one authoritative directory snapshot."""

    router_project_id: ProjectId
    ticket_reference: OpaqueMetadataId
    receipt_id: OpaqueMetadataId
    task_id: CodexTaskId
    thread_id: CodexThreadId
    host_id: CodexHostId
    codex_project_id: CodexProjectId
    worktree_fingerprint: WorktreeFingerprint
    branch_fingerprint: BranchFingerprint
    activity: CodexThreadActivity
    directory_observation_digest: HostObservationDigest

    @model_validator(mode="after")
    def task_is_thread(self) -> Self:
        if self.task_id != self.thread_id:
            raise ValueError("Codex task and thread identity must match")
        return self


class CodexThreadHostResolutionResult(_StrictModel):
    """Exactly one probe target or one finite resolution failure."""

    status: ThreadHostResolutionStatus
    target: CodexThreadHostProbeTarget | None = None
    failure: ThreadHostResolutionFailure | None = None

    @model_validator(mode="after")
    def exact_target_or_failure(self) -> Self:
        if self.status is ThreadHostResolutionStatus.RESOLVED:
            if self.target is None or self.failure is not None:
                raise ValueError("resolved host requires one target and no failure")
            return self
        if self.target is not None or self.failure is None:
            raise ValueError("failed resolution requires one failure and no target")
        if self.status.value != self.failure.value:
            raise ValueError("resolution status and failure must match")
        return self


def derive_thread_host_binding_digest(
    target: CodexThreadHostProbeTarget,
    readback_observation_digest: HostObservationDigest,
) -> EvidenceDigest:
    """Derive a deterministic metadata-only binding revision."""

    material = (
        target.model_dump_json()
        + "|"
        + readback_observation_digest
    ).encode("utf-8")
    return "sha256_" + sha256(material).hexdigest()


class CodexThreadHostBinding(_StrictModel):
    """Receipt-bound host identity proven by directory and exact readback."""

    target: CodexThreadHostProbeTarget
    readback_observation_digest: HostObservationDigest
    binding_digest: EvidenceDigest

    @model_validator(mode="after")
    def binding_digest_is_exact(self) -> Self:
        expected = derive_thread_host_binding_digest(
            self.target,
            self.readback_observation_digest,
        )
        if self.binding_digest != expected:
            raise ValueError("thread host binding digest must match exact observations")
        return self


class CodexThreadHostBindingResult(_StrictModel):
    """Exactly one bound host or one finite binding failure."""

    status: ThreadHostBindingStatus
    binding: CodexThreadHostBinding | None = None
    failure: ThreadHostBindingFailure | None = None

    @model_validator(mode="after")
    def exact_binding_or_failure(self) -> Self:
        if self.status is ThreadHostBindingStatus.BOUND:
            if self.binding is None or self.failure is not None:
                raise ValueError("bound host requires one binding and no failure")
            return self
        if self.binding is not None or self.failure is None:
            raise ValueError("failed binding requires one failure and no binding")
        if self.status.value != self.failure.value:
            raise ValueError("binding status and failure must match")
        return self


__all__ = [
    "CodexHostId",
    "CodexProjectId",
    "CodexTaskId",
    "CodexThreadActivity",
    "CodexThreadHostBinding",
    "CodexThreadHostBindingResult",
    "CodexThreadHostProbeTarget",
    "CodexThreadHostResolutionResult",
    "CodexThreadId",
    "HostObservationDigest",
    "ThreadHostBindingFailure",
    "ThreadHostBindingStatus",
    "ThreadHostResolutionFailure",
    "ThreadHostResolutionStatus",
    "derive_thread_host_binding_digest",
]
