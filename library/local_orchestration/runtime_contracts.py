"""Strict metadata-only contracts for Ticket 02."""

from __future__ import annotations

from enum import Enum
from pathlib import PureWindowsPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from library.workflow_router import ProjectId

from .contracts import InstallationId


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _nonblank(value: str, label: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{label} must be nonblank and unpadded")
    return value


class EventId(_StrictModel):
    value: str

    @field_validator("value")
    @classmethod
    def valid(cls, value: str) -> str:
        return _nonblank(value, "event id")


class CorrelationId(_StrictModel):
    value: str

    @field_validator("value")
    @classmethod
    def valid(cls, value: str) -> str:
        return _nonblank(value, "correlation id")


class RevisionDigest(_StrictModel):
    value: str

    @field_validator("value")
    @classmethod
    def valid(cls, value: str) -> str:
        value = _nonblank(value, "revision digest")
        if not value.startswith("rev-") or len(value) < 12:
            raise ValueError("revision digest must use the rev- vocabulary")
        return value


class EvidenceDigest(_StrictModel):
    value: str

    @field_validator("value")
    @classmethod
    def valid(cls, value: str) -> str:
        if len(value) != 71 or not value.startswith("sha256-"):
            raise ValueError("evidence digest must be sha256 metadata")
        if any(character not in "0123456789abcdef" for character in value[7:]):
            raise ValueError("evidence digest must be lowercase hexadecimal")
        return value


class ProjectReference(_StrictModel):
    value: ProjectId


class RegistryLocator(_StrictModel):
    value: str

    @field_validator("value")
    @classmethod
    def valid(cls, value: str) -> str:
        value = _nonblank(value, "registry locator")
        path = PureWindowsPath(value)
        lowered = value.casefold()
        if (
            not path.is_absolute()
            or str(path) != value
            or "%2f" in lowered
            or "%5c" in lowered
            or any(part in ("", ".", "..") for part in path.parts[1:])
        ):
            raise ValueError("registry locator must be an exact canonical absolute root")
        return value


class RuntimeEvent(_StrictModel):
    event_id: EventId
    installation_id: InstallationId
    project: ProjectReference
    expected_base: RevisionDigest
    correlation_id: CorrelationId
    locator: RegistryLocator


class RouterResumeRequest(_StrictModel):
    event_id: EventId
    installation_id: InstallationId
    project: ProjectReference
    expected_base: RevisionDigest
    correlation_id: CorrelationId

    @classmethod
    def from_event(cls, event: RuntimeEvent) -> RouterResumeRequest:
        return cls(
            event_id=event.event_id,
            installation_id=event.installation_id,
            project=event.project,
            expected_base=event.expected_base,
            correlation_id=event.correlation_id,
        )


class ProjectRegistration(_StrictModel):
    installation_id: InstallationId
    project: ProjectReference
    locator: RegistryLocator


class GuardedDecisionRequest(_StrictModel):
    installation_id: InstallationId
    project: ProjectReference
    expected_base: RevisionDigest
    locator: RegistryLocator

    @classmethod
    def from_event(cls, event: RuntimeEvent) -> GuardedDecisionRequest:
        return cls(
            installation_id=event.installation_id,
            project=event.project,
            expected_base=event.expected_base,
            locator=event.locator,
        )


class RepositorySnapshot(_StrictModel):
    installation_id: InstallationId
    project: ProjectReference
    locator: RegistryLocator
    head_revision: RevisionDigest
    is_clean: bool
    can_fast_forward: bool


class RouterResumeStatus(str, Enum):
    COMPLETED = "COMPLETED"
    NEEDS_USER_ACTION = "NEEDS_USER_ACTION"
    HALTED = "HALTED"


class RouterResumeResult(_StrictModel):
    status: RouterResumeStatus


class GuardedBlockReason(str, Enum):
    PROJECT_UNREGISTERED = "PROJECT_UNREGISTERED"
    INSTALLATION_MISMATCH = "INSTALLATION_MISMATCH"
    LOCATOR_MISMATCH = "LOCATOR_MISMATCH"
    SNAPSHOT_MISMATCH = "SNAPSHOT_MISMATCH"
    DIRTY = "DIRTY"
    STALE_BASE = "STALE_BASE"
    NON_FAST_FORWARD = "NON_FAST_FORWARD"
    LOCK_CONTENDED = "LOCK_CONTENDED"


class FastForwardAllowed(_StrictModel):
    status: Literal["FAST_FORWARD_ALLOWED"] = "FAST_FORWARD_ALLOWED"


class FastForwardBlocked(_StrictModel):
    status: Literal["BLOCKED"] = "BLOCKED"
    reason: GuardedBlockReason


GuardedDecision = FastForwardAllowed | FastForwardBlocked


class RuntimeStatus(str, Enum):
    COMPLETED = "COMPLETED"
    NEEDS_USER_ACTION = "NEEDS_USER_ACTION"
    HALTED = "HALTED"


class RuntimeHaltReason(str, Enum):
    REPLAYED = "REPLAYED"
    ROUTER_HALTED = "ROUTER_HALTED"
    EVENT_CLAIM_FAILED = "EVENT_CLAIM_FAILED"
    ROUTER_RESUME_FAILED = "ROUTER_RESUME_FAILED"
    REGISTRY_RESOLVE_FAILED = "REGISTRY_RESOLVE_FAILED"
    GUARDED_DECISION_FAILED = "GUARDED_DECISION_FAILED"
    PROJECT_UNREGISTERED = "PROJECT_UNREGISTERED"
    INSTALLATION_MISMATCH = "INSTALLATION_MISMATCH"
    LOCATOR_MISMATCH = "LOCATOR_MISMATCH"
    SNAPSHOT_MISMATCH = "SNAPSHOT_MISMATCH"
    DIRTY = "DIRTY"
    STALE_BASE = "STALE_BASE"
    NON_FAST_FORWARD = "NON_FAST_FORWARD"
    LOCK_CONTENDED = "LOCK_CONTENDED"


class MetadataCheckpoint(_StrictModel):
    event_id: EventId
    installation_id: InstallationId
    project: ProjectReference
    expected_base: RevisionDigest
    correlation_id: CorrelationId
    status: RuntimeStatus
    evidence_digest: EvidenceDigest


class RuntimeCompleted(_StrictModel):
    status: Literal[RuntimeStatus.COMPLETED] = RuntimeStatus.COMPLETED
    checkpoint: MetadataCheckpoint


class RuntimeNeedsUserAction(_StrictModel):
    status: Literal[RuntimeStatus.NEEDS_USER_ACTION] = RuntimeStatus.NEEDS_USER_ACTION
    checkpoint: MetadataCheckpoint


class RuntimeHalted(_StrictModel):
    status: Literal[RuntimeStatus.HALTED] = RuntimeStatus.HALTED
    reason: RuntimeHaltReason
    checkpoint: MetadataCheckpoint


RuntimeResult = RuntimeCompleted | RuntimeNeedsUserAction | RuntimeHalted


class RuntimeFailureCode(str, Enum):
    EVENT_CLAIM = "EVENT_CLAIM"
    ROUTER_RESUME = "ROUTER_RESUME"
    REGISTRY_RESOLVE = "REGISTRY_RESOLVE"
    GUARDED_DECISION = "GUARDED_DECISION"


class RuntimePortError(RuntimeError):
    def __init__(self, code: RuntimeFailureCode) -> None:
        super().__init__(code.value)
        self.code = code
