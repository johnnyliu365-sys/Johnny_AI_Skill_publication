"""A synchronous fake decision gate that never executes Git."""

from __future__ import annotations

from enum import Enum
from typing import Protocol

from .project_registry import ProjectRegistryPort, RegistrationMissing
from .runtime_contracts import (
    FastForwardAllowed,
    FastForwardBlocked,
    GuardedBlockReason,
    GuardedDecision,
    GuardedDecisionRequest,
    ProjectRegistration,
    RepositorySnapshot,
    RuntimeFailureCode,
    RuntimePortError,
)


class LockAcquireResult(str, Enum):
    ACQUIRED = "ACQUIRED"
    CONTENDED = "CONTENDED"


class LockReleaseResult(str, Enum):
    RELEASED = "RELEASED"


class ProjectLockPort(Protocol):
    def acquire(self) -> LockAcquireResult: ...

    def release(self) -> LockReleaseResult: ...


class RepositorySnapshotPort(Protocol):
    def read(self, registration: ProjectRegistration) -> RepositorySnapshot: ...


class FakeProjectLock:
    def __init__(self) -> None:
        self.contended = False
        self.acquisitions = 0
        self.releases = 0

    def acquire(self) -> LockAcquireResult:
        if self.contended:
            return LockAcquireResult.CONTENDED
        self.acquisitions += 1
        return LockAcquireResult.ACQUIRED

    def release(self) -> LockReleaseResult:
        self.releases += 1
        return LockReleaseResult.RELEASED


class FakeRepositorySnapshotPort:
    def __init__(self, snapshot: RepositorySnapshot) -> None:
        self._snapshot = snapshot
        self.read_calls = 0

    def read(self, registration: ProjectRegistration) -> RepositorySnapshot:
        self.read_calls += 1
        return self._snapshot

    def replace(self, snapshot: RepositorySnapshot) -> None:
        self._snapshot = snapshot


class GuardedGitDecision:
    def __init__(
        self,
        registry: ProjectRegistryPort,
        lock: ProjectLockPort,
        snapshots: RepositorySnapshotPort,
    ) -> None:
        self._registry = registry
        self._lock = lock
        self._snapshots = snapshots
        self._fail_decision = False
        self.decision_calls = 0
        self.git_mutation_count = 0

    def fail_next_decision(self) -> None:
        self._fail_decision = True

    def decide(self, request: GuardedDecisionRequest) -> GuardedDecision:
        self.decision_calls += 1
        if self._fail_decision:
            self._fail_decision = False
            raise RuntimePortError(RuntimeFailureCode.GUARDED_DECISION)
        registration = self._registry.resolve(request.project)
        if isinstance(registration, RegistrationMissing):
            return FastForwardBlocked(reason=GuardedBlockReason.PROJECT_UNREGISTERED)
        if registration.installation_id != request.installation_id:
            return FastForwardBlocked(reason=GuardedBlockReason.INSTALLATION_MISMATCH)
        if registration.locator != request.locator:
            return FastForwardBlocked(reason=GuardedBlockReason.LOCATOR_MISMATCH)
        if self._lock.acquire() is LockAcquireResult.CONTENDED:
            return FastForwardBlocked(reason=GuardedBlockReason.LOCK_CONTENDED)
        try:
            snapshot = self._snapshots.read(registration)
            if (
                snapshot.installation_id != registration.installation_id
                or snapshot.project != registration.project
                or snapshot.locator != registration.locator
            ):
                return FastForwardBlocked(reason=GuardedBlockReason.SNAPSHOT_MISMATCH)
            if not snapshot.is_clean:
                return FastForwardBlocked(reason=GuardedBlockReason.DIRTY)
            if snapshot.head_revision != request.expected_base:
                return FastForwardBlocked(reason=GuardedBlockReason.STALE_BASE)
            if not snapshot.can_fast_forward:
                return FastForwardBlocked(reason=GuardedBlockReason.NON_FAST_FORWARD)
            return FastForwardAllowed()
        finally:
            self._lock.release()
