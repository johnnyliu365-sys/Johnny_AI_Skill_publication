"""Pure profile-bound CLI admission for plugin-distribution preflight."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, TypeAlias, TypeGuard

from pydantic import ValidationError

from library.workflow_router.profile import build_plugin_distribution_profile

from .johnny_router_contracts import (
    JohnnyRouterBlocked,
    JohnnyRouterCapabilityUnavailable,
    JohnnyRouterOperation,
    JohnnyRouterPreflightPort,
    JohnnyRouterRequest,
    JohnnyRouterResult,
    JohnnyRouterResultCode,
    JohnnyRouterSucceeded,
    PreflightProbe,
)


_PROFILE_ID: Literal["plugin-distribution-poc-r02"] = "plugin-distribution-poc-r02"
_PROFILE_VERSION: Literal["2"] = "2"
_BlockedCode: TypeAlias = Literal[
    JohnnyRouterResultCode.UNKNOWN_OPERATION,
    JohnnyRouterResultCode.INVALID_ARGUMENTS,
    JohnnyRouterResultCode.STALE_PROFILE,
    JohnnyRouterResultCode.INVALID_PROBE,
]
_CapabilityCode: TypeAlias = Literal[
    JohnnyRouterResultCode.GIT_UNAVAILABLE,
    JohnnyRouterResultCode.PYTHON_UNAVAILABLE,
    JohnnyRouterResultCode.PYTHON_INCOMPATIBLE,
    JohnnyRouterResultCode.OPERATION_UNAVAILABLE,
]


def _is_argument_sequence(value: object) -> TypeGuard[Sequence[object]]:
    """Recognize a positional argv container without accepting scalar text."""

    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _is_plain_text(value: object) -> TypeGuard[str]:
    """Accept only ordinary strings at the untyped argv boundary."""

    return type(value) is str


def _emit(result: JohnnyRouterResult) -> JohnnyRouterResult:
    """Write the one canonical result and return the same typed value."""

    print(result.model_dump_json())
    return result


def _blocked(
    code: _BlockedCode,
    operation: JohnnyRouterOperation | None,
) -> JohnnyRouterBlocked:
    """Construct one finite blocked result."""

    return JohnnyRouterBlocked(code=code, operation=operation)


def _capability_unavailable(
    code: _CapabilityCode,
    operation: JohnnyRouterOperation,
) -> JohnnyRouterCapabilityUnavailable:
    """Construct one finite capability result."""

    return JohnnyRouterCapabilityUnavailable(code=code, operation=operation)


def _preflight_request(
    operation: JohnnyRouterOperation,
) -> JohnnyRouterRequest:
    """Build and revalidate the exact profile-bound request."""

    request = JohnnyRouterRequest(
        operation=operation,
        expected_profile_id=_PROFILE_ID,
        expected_profile_version=_PROFILE_VERSION,
    )
    return JohnnyRouterRequest.model_validate(request, strict=True)


def _validated_probe(
    probe: PreflightProbe,
) -> PreflightProbe:
    """Revalidate port evidence before interpreting any capability field."""

    return PreflightProbe.model_validate(probe, strict=True)


def main(argv: object, ports: JohnnyRouterPreflightPort) -> JohnnyRouterResult:
    """Admit one closed request and emit exactly one finite JSON result."""

    build_plugin_distribution_profile()

    if not _is_argument_sequence(argv) or len(argv) != 3:
        return _emit(_blocked(JohnnyRouterResultCode.INVALID_ARGUMENTS, None))

    operation_value, profile_id, profile_version = argv
    if not (
        _is_plain_text(operation_value)
        and _is_plain_text(profile_id)
        and _is_plain_text(profile_version)
    ):
        return _emit(_blocked(JohnnyRouterResultCode.INVALID_ARGUMENTS, None))

    try:
        operation = JohnnyRouterOperation(operation_value)
    except ValueError:
        return _emit(_blocked(JohnnyRouterResultCode.UNKNOWN_OPERATION, None))

    if profile_id != _PROFILE_ID or profile_version != _PROFILE_VERSION:
        return _emit(_blocked(JohnnyRouterResultCode.STALE_PROFILE, operation))

    try:
        request = _preflight_request(operation)
    except ValidationError:
        return _emit(_blocked(JohnnyRouterResultCode.INVALID_ARGUMENTS, None))

    if request.operation is not JohnnyRouterOperation.PREFLIGHT:
        return _emit(
            _capability_unavailable(
                JohnnyRouterResultCode.OPERATION_UNAVAILABLE,
                request.operation,
            )
        )

    raw_probe = ports.probe()
    try:
        probe = _validated_probe(raw_probe)
    except ValidationError:
        return _emit(_blocked(JohnnyRouterResultCode.INVALID_PROBE, request.operation))

    if not probe.git_available:
        return _emit(
            _capability_unavailable(
                JohnnyRouterResultCode.GIT_UNAVAILABLE,
                request.operation,
            )
        )
    if probe.python_version is None:
        return _emit(
            _capability_unavailable(
                JohnnyRouterResultCode.PYTHON_UNAVAILABLE,
                request.operation,
            )
        )
    if not (3, 11, 0) <= probe.python_version < (3, 14, 0):
        return _emit(
            _capability_unavailable(
                JohnnyRouterResultCode.PYTHON_INCOMPATIBLE,
                request.operation,
            )
        )

    return _emit(JohnnyRouterSucceeded())


__all__ = ["main"]
