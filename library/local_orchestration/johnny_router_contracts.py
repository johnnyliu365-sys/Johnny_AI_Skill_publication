"""Closed, profile-bound contracts for the plugin-distribution preflight CLI."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Protocol, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _StrictModel(BaseModel):
    """Immutable strict values at the CLI boundary."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
    )


class JohnnyRouterOperation(str, Enum):
    """The finite operations admitted by the profile-bound CLI."""

    PREFLIGHT = "PREFLIGHT"
    REGISTER_PROJECT = "REGISTER_PROJECT"
    DETACH_PROJECT = "DETACH_PROJECT"
    REGISTER_SUBSCRIPTION = "REGISTER_SUBSCRIPTION"
    CANCEL_SUBSCRIPTION = "CANCEL_SUBSCRIPTION"
    ROUTE_EVENT = "ROUTE_EVENT"
    STATUS = "STATUS"
    UNINSTALL = "UNINSTALL"


class JohnnyRouterRequest(_StrictModel):
    """One exact request shape for the current plugin-distribution profile."""

    operation: JohnnyRouterOperation
    expected_profile_id: Literal["plugin-distribution-poc-r02"]
    expected_profile_version: Literal["2"]


class PreflightProbe(_StrictModel):
    """Validated capability evidence supplied by the isolated preflight port."""

    git_available: bool
    python_version: tuple[int, int, int] | None

    @model_validator(mode="after")
    def python_version_is_nonnegative(self) -> Self:
        """Keep the version tuple finite and representable as Python version data."""

        if self.python_version is not None and any(
            type(component) is not int or component < 0
            for component in self.python_version
        ):
            raise ValueError("python version components must be non-negative integers")
        return self


class JohnnyRouterResultStatus(str, Enum):
    """Finite result status values exposed by the CLI."""

    SUCCEEDED = "SUCCEEDED"
    BLOCKED = "BLOCKED"
    CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    HALTED = "HALTED"


class JohnnyRouterResultCode(str, Enum):
    """Finite result codes with no free-form diagnostic channel."""

    PREFLIGHT_PASSED = "PREFLIGHT_PASSED"
    UNKNOWN_OPERATION = "UNKNOWN_OPERATION"
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
    STALE_PROFILE = "STALE_PROFILE"
    INVALID_PROBE = "INVALID_PROBE"
    GIT_UNAVAILABLE = "GIT_UNAVAILABLE"
    PYTHON_UNAVAILABLE = "PYTHON_UNAVAILABLE"
    PYTHON_INCOMPATIBLE = "PYTHON_INCOMPATIBLE"
    OPERATION_UNAVAILABLE = "OPERATION_UNAVAILABLE"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    HALTED = "HALTED"


class _ProfileBoundResult(_StrictModel):
    """Common profile identity carried by every result member."""

    expected_profile_id: Literal["plugin-distribution-poc-r02"] = "plugin-distribution-poc-r02"
    expected_profile_version: Literal["2"] = "2"


class JohnnyRouterSucceeded(_ProfileBoundResult):
    """Successful exact preflight result."""

    status: Literal[JohnnyRouterResultStatus.SUCCEEDED] = JohnnyRouterResultStatus.SUCCEEDED
    code: Literal[JohnnyRouterResultCode.PREFLIGHT_PASSED] = (
        JohnnyRouterResultCode.PREFLIGHT_PASSED
    )
    operation: Literal[JohnnyRouterOperation.PREFLIGHT] = JohnnyRouterOperation.PREFLIGHT


class JohnnyRouterBlocked(_ProfileBoundResult):
    """Finite argument, profile or probe admission failure."""

    status: Literal[JohnnyRouterResultStatus.BLOCKED] = JohnnyRouterResultStatus.BLOCKED
    code: Literal[
        JohnnyRouterResultCode.UNKNOWN_OPERATION,
        JohnnyRouterResultCode.INVALID_ARGUMENTS,
        JohnnyRouterResultCode.STALE_PROFILE,
        JohnnyRouterResultCode.INVALID_PROBE,
    ]
    operation: JohnnyRouterOperation | None

    @model_validator(mode="after")
    def operation_matches_admission_failure(self) -> Self:
        """Unknown and malformed argv are the only null-operation cases."""

        null_operation_codes = {
            JohnnyRouterResultCode.UNKNOWN_OPERATION,
            JohnnyRouterResultCode.INVALID_ARGUMENTS,
        }
        if (self.code in null_operation_codes) != (self.operation is None):
            raise ValueError("operation must match the blocked admission class")
        if self.code in (
            JohnnyRouterResultCode.STALE_PROFILE,
            JohnnyRouterResultCode.INVALID_PROBE,
        ) and self.operation is None:
            raise ValueError("stale and invalid-probe results require an operation")
        return self


class JohnnyRouterCapabilityUnavailable(_ProfileBoundResult):
    """Finite capability or deferred-operation result."""

    status: Literal[
        JohnnyRouterResultStatus.CAPABILITY_UNAVAILABLE
    ] = JohnnyRouterResultStatus.CAPABILITY_UNAVAILABLE
    code: Literal[
        JohnnyRouterResultCode.GIT_UNAVAILABLE,
        JohnnyRouterResultCode.PYTHON_UNAVAILABLE,
        JohnnyRouterResultCode.PYTHON_INCOMPATIBLE,
        JohnnyRouterResultCode.OPERATION_UNAVAILABLE,
    ]
    operation: JohnnyRouterOperation

    @model_validator(mode="after")
    def operation_matches_capability_failure(self) -> Self:
        """Bind preflight capability failures and deferred operations exactly."""

        preflight_codes = {
            JohnnyRouterResultCode.GIT_UNAVAILABLE,
            JohnnyRouterResultCode.PYTHON_UNAVAILABLE,
            JohnnyRouterResultCode.PYTHON_INCOMPATIBLE,
        }
        if (self.code in preflight_codes) != (
            self.operation is JohnnyRouterOperation.PREFLIGHT
        ):
            raise ValueError("capability result operation does not match its code")
        if (
            self.code is JohnnyRouterResultCode.OPERATION_UNAVAILABLE
            and self.operation is JohnnyRouterOperation.PREFLIGHT
        ):
            raise ValueError("preflight is not a deferred operation")
        return self


class JohnnyRouterNotFound(_ProfileBoundResult):
    """Declared but not returned Ticket 04 not-found result."""

    status: Literal[JohnnyRouterResultStatus.NOT_FOUND] = JohnnyRouterResultStatus.NOT_FOUND
    code: Literal[JohnnyRouterResultCode.NOT_FOUND] = JohnnyRouterResultCode.NOT_FOUND
    operation: JohnnyRouterOperation | None


class JohnnyRouterConflict(_ProfileBoundResult):
    """Declared but not returned Ticket 04 conflict result."""

    status: Literal[JohnnyRouterResultStatus.CONFLICT] = JohnnyRouterResultStatus.CONFLICT
    code: Literal[JohnnyRouterResultCode.CONFLICT] = JohnnyRouterResultCode.CONFLICT
    operation: JohnnyRouterOperation | None


class JohnnyRouterHalted(_ProfileBoundResult):
    """Declared but not returned Ticket 04 halted result."""

    status: Literal[JohnnyRouterResultStatus.HALTED] = JohnnyRouterResultStatus.HALTED
    code: Literal[JohnnyRouterResultCode.HALTED] = JohnnyRouterResultCode.HALTED
    operation: JohnnyRouterOperation | None


JohnnyRouterResult: TypeAlias = Annotated[
    JohnnyRouterSucceeded
    | JohnnyRouterBlocked
    | JohnnyRouterCapabilityUnavailable
    | JohnnyRouterNotFound
    | JohnnyRouterConflict
    | JohnnyRouterHalted,
    Field(discriminator="status"),
]


class JohnnyRouterPreflightPort(Protocol):
    """The only runtime capability boundary admitted by Ticket 04."""

    def probe(self) -> PreflightProbe:
        """Return one typed, metadata-only preflight observation."""


__all__ = [
    "JohnnyRouterBlocked",
    "JohnnyRouterCapabilityUnavailable",
    "JohnnyRouterConflict",
    "JohnnyRouterHalted",
    "JohnnyRouterNotFound",
    "JohnnyRouterOperation",
    "JohnnyRouterPreflightPort",
    "JohnnyRouterRequest",
    "JohnnyRouterResult",
    "JohnnyRouterResultCode",
    "JohnnyRouterResultStatus",
    "JohnnyRouterSucceeded",
    "PreflightProbe",
]
