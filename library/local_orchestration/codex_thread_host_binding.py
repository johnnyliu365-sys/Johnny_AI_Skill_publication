"""Codex task-directory projection and receipt-bound host binding."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path, PureWindowsPath
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from library.workflow_router.live_dispatch_contracts import ReceiptLifecycle, TicketReceipt
from library.workflow_router.thread_host_contracts import (
    CodexHostId,
    CodexProjectId,
    CodexTaskId,
    CodexThreadActivity,
    CodexThreadHostBinding,
    CodexThreadHostBindingResult,
    CodexThreadHostProbeTarget,
    CodexThreadHostResolutionResult,
    CodexThreadId,
    HostObservationDigest,
    ThreadHostBindingFailure,
    ThreadHostBindingStatus,
    ThreadHostResolutionFailure,
    ThreadHostResolutionStatus,
    derive_thread_host_binding_digest,
)


class _TransportModel(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        frozen=True,
        strict=True,
        revalidate_instances="always",
    )


class _CodexDirectoryThread(_TransportModel):
    id: CodexThreadId
    kind: Literal["codex"]
    project_id: CodexProjectId | None = Field(default=None, alias="projectId")
    host_id: CodexHostId = Field(alias="hostId")
    status: CodexThreadActivity
    cwd: str = Field(min_length=1)


class _ChatDirectoryThread(_TransportModel):
    id: str = Field(min_length=1)
    kind: Literal["chatgpt"]


_DirectoryThread = Annotated[
    _CodexDirectoryThread | _ChatDirectoryThread,
    Field(discriminator="kind"),
]


class _DirectoryTransport(_TransportModel):
    schema_version: Literal[4] = Field(alias="schemaVersion")
    pinned_threads: tuple[_DirectoryThread, ...] = Field(alias="pinnedThreads")
    threads: tuple[_DirectoryThread, ...]
    unavailable_hosts: tuple[CodexHostId, ...] = Field(alias="unavailableHosts")


class _ReadbackStatusTransport(_TransportModel):
    type: CodexThreadActivity


class _ReadbackThreadTransport(_TransportModel):
    id: CodexThreadId
    kind: Literal["codex"]
    host_id: CodexHostId = Field(alias="hostId")
    project_id: CodexProjectId | None = Field(default=None, alias="projectId")
    status: _ReadbackStatusTransport
    cwd: str = Field(min_length=1)


class _ReadbackTransport(_TransportModel):
    schema_version: Literal[1] = Field(alias="schemaVersion")
    thread: _ReadbackThreadTransport


class _RequestShape(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    task_id: CodexTaskId
    thread_id: CodexThreadId
    codex_project_id: CodexProjectId

    @model_validator(mode="after")
    def task_is_thread(self) -> Self:
        if self.task_id != self.thread_id:
            raise ValueError("Codex task and thread identity must match")
        return self


@dataclass(frozen=True, slots=True)
class ResolvedWorkspaceRoot:
    """An exact existing local workspace root used only during host readback."""

    root: Path

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path):
            raise TypeError("workspace root must be a Path")
        if not self.root.is_absolute():
            raise ValueError("workspace root must be absolute")
        resolved = self.root.resolve(strict=True)
        if resolved != self.root or not resolved.is_dir():
            raise ValueError("workspace root must be an existing resolved directory")


@dataclass(frozen=True, slots=True)
class CodexThreadHostBindingRequest:
    """Transient request binding one active receipt to one expected Codex project."""

    receipt: TicketReceipt
    task_id: CodexTaskId
    thread_id: CodexThreadId
    codex_project_id: CodexProjectId
    workspace_root: ResolvedWorkspaceRoot

    def __post_init__(self) -> None:
        if type(self.receipt) is not TicketReceipt:
            raise TypeError("host binding requires the exact live ticket receipt")
        if self.receipt.lifecycle is not ReceiptLifecycle.ACTIVE:
            raise ValueError("host binding requires one active ticket receipt")
        if type(self.workspace_root) is not ResolvedWorkspaceRoot:
            raise TypeError("host binding requires an exact resolved workspace root")
        _RequestShape(
            task_id=self.task_id,
            thread_id=self.thread_id,
            codex_project_id=self.codex_project_id,
        )


@dataclass(frozen=True, slots=True)
class _DirectoryEntry:
    thread_id: CodexThreadId
    project_id: CodexProjectId | None
    host_id: CodexHostId
    activity: CodexThreadActivity
    cwd: str


@dataclass(frozen=True, slots=True)
class _DirectorySnapshot:
    entries: tuple[_DirectoryEntry, ...]
    unavailable_hosts: tuple[CodexHostId, ...]
    digest: HostObservationDigest


@dataclass(frozen=True, slots=True)
class _ThreadReadback:
    thread_id: CodexThreadId
    project_id: CodexProjectId | None
    host_id: CodexHostId
    activity: CodexThreadActivity
    cwd: str
    digest: HostObservationDigest


def _observation_digest(material: str) -> HostObservationDigest:
    return "sha256_" + sha256(material.encode("utf-8")).hexdigest()


def _workspace_matches(raw_cwd: str, expected: ResolvedWorkspaceRoot) -> bool:
    if not raw_cwd or raw_cwd != raw_cwd.strip() or "\x00" in raw_cwd:
        return False
    lowered = raw_cwd.casefold()
    if "://" in lowered or lowered.startswith("file:"):
        return False
    pure = PureWindowsPath(raw_cwd)
    if not pure.is_absolute() or any(part in (".", "..") for part in pure.parts):
        return False
    try:
        candidate = Path(raw_cwd).resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    if not candidate.is_dir():
        return False
    return os.path.normcase(str(candidate)) == os.path.normcase(str(expected.root))


def _resolution_failure(
    failure: ThreadHostResolutionFailure,
) -> CodexThreadHostResolutionResult:
    return CodexThreadHostResolutionResult(
        status=ThreadHostResolutionStatus(failure.value),
        failure=failure,
    )


def _binding_failure(failure: ThreadHostBindingFailure) -> CodexThreadHostBindingResult:
    return CodexThreadHostBindingResult(
        status=ThreadHostBindingStatus(failure.value),
        failure=failure,
    )


class CodexAppThreadObservationAdapter:
    """Project metadata from Codex tool payloads; untrusted bodies are discarded."""

    def parse_directory(self, payload: str) -> _DirectorySnapshot | None:
        try:
            transport = _DirectoryTransport.model_validate_json(payload, strict=True)
        except (ValidationError, UnicodeError):
            return None
        codex_threads = tuple(
            thread
            for thread in (*transport.pinned_threads, *transport.threads)
            if type(thread) is _CodexDirectoryThread
        )
        raw_entries = tuple(
            _DirectoryEntry(
                thread_id=thread.id,
                project_id=thread.project_id,
                host_id=thread.host_id,
                activity=thread.status,
                cwd=thread.cwd,
            )
            for thread in codex_threads
        )
        entries = tuple(dict.fromkeys(raw_entries))
        ordered_entries = tuple(
            sorted(
                entries,
                key=lambda entry: (
                    entry.thread_id,
                    entry.project_id or "",
                    entry.host_id,
                    entry.activity.value,
                    os.path.normcase(entry.cwd),
                ),
            )
        )
        evidence_material = "\n".join(
            (
                entry.thread_id
                + "|"
                + (entry.project_id or "-")
                + "|"
                + entry.host_id
                + "|"
                + entry.activity.value
                + "|"
                + os.path.normcase(entry.cwd)
            )
            for entry in ordered_entries
        )
        evidence_material += "\nunavailable=" + "|".join(
            sorted(transport.unavailable_hosts)
        )
        return _DirectorySnapshot(
            entries=ordered_entries,
            unavailable_hosts=transport.unavailable_hosts,
            digest=_observation_digest(evidence_material),
        )

    def parse_readback(self, payload: str) -> _ThreadReadback | None:
        try:
            transport = _ReadbackTransport.model_validate_json(payload, strict=True)
        except (ValidationError, UnicodeError):
            return None
        thread = transport.thread
        return _ThreadReadback(
            thread_id=thread.id,
            project_id=thread.project_id,
            host_id=thread.host_id,
            activity=thread.status.type,
            cwd=thread.cwd,
            digest=_observation_digest(
                thread.id
                + "|"
                + (thread.project_id or "-")
                + "|"
                + thread.host_id
                + "|"
                + thread.status.type.value
                + "|"
                + os.path.normcase(thread.cwd)
            ),
        )


class CodexThreadHostBinder:
    """Resolve and bind an exact Codex thread without host effects or polling."""

    def __init__(self, adapter: CodexAppThreadObservationAdapter | None = None) -> None:
        self._adapter = (
            adapter if adapter is not None else CodexAppThreadObservationAdapter()
        )

    def resolve(
        self,
        request: CodexThreadHostBindingRequest,
        directory_payload: str | None,
    ) -> CodexThreadHostResolutionResult:
        if directory_payload is None:
            return _resolution_failure(ThreadHostResolutionFailure.DIRECTORY_UNAVAILABLE)
        snapshot = self._adapter.parse_directory(directory_payload)
        if snapshot is None:
            return _resolution_failure(ThreadHostResolutionFailure.DIRECTORY_PAYLOAD_INVALID)
        candidates = tuple(
            entry for entry in snapshot.entries if entry.thread_id == request.thread_id
        )
        if not candidates:
            return _resolution_failure(ThreadHostResolutionFailure.THREAD_NOT_FOUND)
        if len(candidates) != 1:
            return _resolution_failure(ThreadHostResolutionFailure.AMBIGUOUS_THREAD)
        candidate = candidates[0]
        if candidate.host_id in snapshot.unavailable_hosts:
            return _resolution_failure(ThreadHostResolutionFailure.HOST_UNAVAILABLE)
        if candidate.project_id is None:
            return _resolution_failure(ThreadHostResolutionFailure.PROJECT_REQUIRED)
        if candidate.project_id != request.codex_project_id:
            return _resolution_failure(ThreadHostResolutionFailure.PROJECT_MISMATCH)
        if not _workspace_matches(candidate.cwd, request.workspace_root):
            return _resolution_failure(ThreadHostResolutionFailure.WORKSPACE_MISMATCH)
        if candidate.activity is CodexThreadActivity.NOT_LOADED:
            return _resolution_failure(ThreadHostResolutionFailure.THREAD_NOT_READY)
        receipt = request.receipt
        target = CodexThreadHostProbeTarget(
            router_project_id=receipt.project_id,
            ticket_reference=receipt.ticket_reference,
            receipt_id=receipt.receipt_id,
            task_id=request.task_id,
            thread_id=request.thread_id,
            host_id=candidate.host_id,
            codex_project_id=candidate.project_id,
            worktree_fingerprint=receipt.worktree_fingerprint,
            branch_fingerprint=receipt.branch_fingerprint,
            activity=candidate.activity,
            directory_observation_digest=snapshot.digest,
        )
        return CodexThreadHostResolutionResult(
            status=ThreadHostResolutionStatus.RESOLVED,
            target=target,
        )

    def bind(
        self,
        request: CodexThreadHostBindingRequest,
        directory_payload: str | None,
        readback_payload: str | None,
    ) -> CodexThreadHostBindingResult:
        resolution = self.resolve(request, directory_payload)
        if resolution.status is not ThreadHostResolutionStatus.RESOLVED:
            if resolution.failure is None:
                return _binding_failure(ThreadHostBindingFailure.DIRECTORY_PAYLOAD_INVALID)
            return _binding_failure(ThreadHostBindingFailure(resolution.failure.value))
        target = resolution.target
        if target is None:
            return _binding_failure(ThreadHostBindingFailure.DIRECTORY_PAYLOAD_INVALID)
        if readback_payload is None:
            return _binding_failure(ThreadHostBindingFailure.READBACK_UNAVAILABLE)
        readback = self._adapter.parse_readback(readback_payload)
        if readback is None:
            return _binding_failure(ThreadHostBindingFailure.READBACK_PAYLOAD_INVALID)
        if (
            readback.thread_id != target.thread_id
            or readback.host_id != target.host_id
            or (
                readback.project_id is not None
                and readback.project_id != target.codex_project_id
            )
            or not _workspace_matches(readback.cwd, request.workspace_root)
        ):
            return _binding_failure(ThreadHostBindingFailure.READBACK_MISMATCH)
        if readback.activity is CodexThreadActivity.NOT_LOADED:
            return _binding_failure(ThreadHostBindingFailure.THREAD_NOT_READY)
        binding = CodexThreadHostBinding(
            target=target,
            readback_observation_digest=readback.digest,
            binding_digest=derive_thread_host_binding_digest(target, readback.digest),
        )
        return CodexThreadHostBindingResult(
            status=ThreadHostBindingStatus.BOUND,
            binding=binding,
        )


__all__ = [
    "CodexAppThreadObservationAdapter",
    "CodexThreadHostBinder",
    "CodexThreadHostBindingRequest",
    "ResolvedWorkspaceRoot",
]
