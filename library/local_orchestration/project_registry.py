"""Exact in-memory project registration boundary."""

from __future__ import annotations

from enum import Enum
from typing import Protocol

from .runtime_contracts import (
    ProjectReference,
    ProjectRegistration,
    RuntimeFailureCode,
    RuntimePortError,
)


class RegistrationMissing:
    __slots__ = ()


RegistrationRead = ProjectRegistration | RegistrationMissing


class RegistryWriteResult(str, Enum):
    REGISTERED = "REGISTERED"


class ProjectRegistryPort(Protocol):
    def resolve(self, project: ProjectReference) -> RegistrationRead: ...


class InMemoryProjectRegistry:
    def __init__(self) -> None:
        self._registrations: dict[str, ProjectRegistration] = {}
        self._fail_resolve = False
        self.resolve_calls = 0
        self.mutation_count = 0

    def register(self, registration: ProjectRegistration) -> RegistryWriteResult:
        self._registrations[registration.project.value] = registration
        self.mutation_count += 1
        return RegistryWriteResult.REGISTERED

    def resolve(self, project: ProjectReference) -> RegistrationRead:
        self.resolve_calls += 1
        if self._fail_resolve:
            self._fail_resolve = False
            raise RuntimePortError(RuntimeFailureCode.REGISTRY_RESOLVE)
        return self._registrations.get(project.value, RegistrationMissing())

    def fail_next_resolve(self) -> None:
        self._fail_resolve = True
