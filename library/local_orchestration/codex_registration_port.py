"""Closed, effect-free admission and value validation for Codex registration."""

from __future__ import annotations

from enum import Enum
import ntpath
from types import CodeType, FunctionType, GetSetDescriptorType, MappingProxyType, MethodType
from typing import Callable, Final, Literal, NoReturn, SupportsIndex, TypeAlias, cast

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from .codex_command_attempts import (
    CodexCommandStartState,
    CodexCommandTarget,
    CodexMarketplaceAddConfirmed,
    CodexPluginAddConfirmed,
    CodexPreStartFailure,
    CodexPreStartFailureReason,
    CodexStartedFailure,
    CodexStartedFailureReason,
)
from .codex_registration_contracts import (
    CodexAuthPolicy,
    CodexMarketplaceAddObservation,
    CodexObservedAbsolutePath,
    CodexPluginAddObservation,
    CodexPluginId,
    CodexRegistrationAttemptId,
    CodexRegistrationProof,
    CodexRegistrationProofRequest,
)
from .contracts import (
    CANONICAL_INSTALL_ROOT,
    ArtifactDigest,
    InstallRoot,
    InstallationId,
    OwnedRelativePath,
)
from .host_contracts import (
    CodexBlockReason,
    CodexCliVersion,
    CodexMarketplaceName,
    CodexPluginName,
    CodexPreflightEligible,
    CodexPreflightRequest,
)


class _StrictModel(BaseModel):
    """Strict immutable values at the registration effect boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, revalidate_instances="always")


class CodexRegistrationPortRequest(_StrictModel):
    """All authority required by one current registration attempt."""

    preflight: CodexPreflightRequest
    attempt_id: CodexRegistrationAttemptId
    expected_version: CodexCliVersion
    source_locator: OwnedRelativePath
    installed_locator: OwnedRelativePath
    digest: ArtifactDigest
    expected_auth_policy: CodexAuthPolicy
    expected_plugin_id: CodexPluginId

    @model_validator(mode="after")
    def exact_source_binding(self) -> CodexRegistrationPortRequest:
        try:
            exact_shape = (
                type(self.preflight) is CodexPreflightRequest
                and type(self.preflight.marketplace_source) is OwnedRelativePath
                and type(self.preflight.marketplace_source.value) is str
                and type(self.source_locator) is OwnedRelativePath
                and type(self.source_locator.value) is str
            )
        except AttributeError as error:
            raise ValueError("registration source shape is invalid") from error
        if not exact_shape or self.source_locator.value != self.preflight.marketplace_source.value:
            raise ValueError("registration source must bind the preflight request")
        return self


class CodexFreshPreflightAccepted(_StrictModel):
    """A fresh eligible preflight bound to the exact current request."""

    request: CodexRegistrationPortRequest
    eligible: CodexPreflightEligible


class CodexFreshPreflightRejected(_StrictModel):
    """A fresh finite preflight rejection bound to the exact current request."""

    request: CodexRegistrationPortRequest
    reason: CodexBlockReason


CodexFreshPreflightResult: TypeAlias = CodexFreshPreflightAccepted | CodexFreshPreflightRejected


class CodexMarketplaceAddSucceeded(_StrictModel):
    """Exact marketplace confirmation and its ephemeral typed observation."""

    request: CodexRegistrationPortRequest
    confirmed: CodexMarketplaceAddConfirmed
    observation: CodexMarketplaceAddObservation


class CodexPluginAddSucceeded(_StrictModel):
    """Exact plugin confirmation and its ephemeral typed observation."""

    request: CodexRegistrationPortRequest
    confirmed: CodexPluginAddConfirmed
    observation: CodexPluginAddObservation


class CodexRegistrationCommandFailed(_StrictModel):
    """One finite command failure bound to the exact current request."""

    request: CodexRegistrationPortRequest
    failure: CodexPreStartFailure | CodexStartedFailure


CodexMarketplaceAddResult: TypeAlias = CodexMarketplaceAddSucceeded | CodexRegistrationCommandFailed
CodexPluginAddResult: TypeAlias = CodexPluginAddSucceeded | CodexRegistrationCommandFailed


class CodexRegistrationPortValueRejectReason(str, Enum):
    """Finite reasons for rejecting a supplied request or operation result."""

    INVALID_REQUEST = "INVALID_REQUEST"
    REQUEST_MISMATCH = "REQUEST_MISMATCH"
    INVALID_RESULT = "INVALID_RESULT"
    TARGET_MISMATCH = "TARGET_MISMATCH"
    VERSION_MISMATCH = "VERSION_MISMATCH"


class CodexRegistrationPortValueRejected(_StrictModel):
    """Metadata-only rejection with no raw validation or absolute path text."""

    status: Literal["INVALID_VALUE"] = "INVALID_VALUE"
    reason: CodexRegistrationPortValueRejectReason


CodexRegistrationPortRequestValidation: TypeAlias = (
    CodexRegistrationPortRequest | CodexRegistrationPortValueRejected
)
CodexFreshPreflightValidation: TypeAlias = CodexFreshPreflightResult | CodexRegistrationPortValueRejected
CodexMarketplaceAddValidation: TypeAlias = CodexMarketplaceAddResult | CodexRegistrationPortValueRejected
CodexPluginAddValidation: TypeAlias = CodexPluginAddResult | CodexRegistrationPortValueRejected


def revalidate_registration_port_request(value: object) -> CodexRegistrationPortRequestValidation:
    """Rebuild one exact request before comparing any caller-supplied value."""

    if type(value) is not CodexRegistrationPortRequest:
        return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_REQUEST)
    current = value
    try:
        if not _request_fields_are_exact(current):
            return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_REQUEST)
        rebuilt_preflight = CodexPreflightRequest(
            installation_id=InstallationId(value=current.preflight.installation_id.value),
            root=InstallRoot(value=current.preflight.root.value),
            marketplace=CodexMarketplaceName(value=current.preflight.marketplace.value),
            plugin=CodexPluginName(value=current.preflight.plugin.value),
            marketplace_source=OwnedRelativePath(value=current.preflight.marketplace_source.value),
        )
        rebuilt_attempt = CodexRegistrationAttemptId(value=current.attempt_id.value)
        rebuilt_version = CodexCliVersion(value=current.expected_version.value)
        rebuilt_source = OwnedRelativePath(value=current.source_locator.value)
        rebuilt_installed = OwnedRelativePath(value=current.installed_locator.value)
        rebuilt_digest = ArtifactDigest(value=current.digest.value)
        rebuilt_auth = CodexAuthPolicy(value=current.expected_auth_policy.value)
        rebuilt_plugin_id = CodexPluginId(value=current.expected_plugin_id.value)
    except (AttributeError, TypeError, ValidationError, ValueError):
        return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_REQUEST)
    if rebuilt_source.value != rebuilt_preflight.marketplace_source.value:
        return _value_rejected(CodexRegistrationPortValueRejectReason.REQUEST_MISMATCH)
    try:
        return CodexRegistrationPortRequest(
            preflight=rebuilt_preflight,
            attempt_id=rebuilt_attempt,
            expected_version=rebuilt_version,
            source_locator=rebuilt_source,
            installed_locator=rebuilt_installed,
            digest=rebuilt_digest,
            expected_auth_policy=rebuilt_auth,
            expected_plugin_id=rebuilt_plugin_id,
        )
    except (TypeError, ValidationError, ValueError):
        return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_REQUEST)


def revalidate_fresh_preflight_result(
    value: object,
    expected_request: CodexRegistrationPortRequest,
) -> CodexFreshPreflightValidation:
    """Rebuild a fresh accepted or rejected preflight envelope."""

    expected = revalidate_registration_port_request(expected_request)
    if isinstance(expected, CodexRegistrationPortValueRejected):
        return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_REQUEST)
    if type(value) is CodexFreshPreflightAccepted:
        current = value
        bound = _validated_bound_request(current, expected)
        if isinstance(bound, CodexRegistrationPortValueRejected):
            return bound
        rebuilt_eligible = _rebuild_eligible(current)
        if isinstance(rebuilt_eligible, CodexRegistrationPortValueRejected):
            return rebuilt_eligible
        if rebuilt_eligible.version.value != expected.expected_version.value:
            return _value_rejected(CodexRegistrationPortValueRejectReason.VERSION_MISMATCH)
        return CodexFreshPreflightAccepted(request=bound, eligible=rebuilt_eligible)
    if type(value) is CodexFreshPreflightRejected:
        current_rejection = value
        bound = _validated_bound_request(current_rejection, expected)
        if isinstance(bound, CodexRegistrationPortValueRejected):
            return bound
        try:
            reason: object = current_rejection.reason
        except AttributeError:
            return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)
        if type(reason) is not CodexBlockReason:
            return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)
        return CodexFreshPreflightRejected(request=bound, reason=reason)
    return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)


def revalidate_marketplace_add_result(
    value: object,
    expected_request: CodexRegistrationPortRequest,
) -> CodexMarketplaceAddValidation:
    """Rebuild one marketplace add success or exact-target command failure."""

    expected = revalidate_registration_port_request(expected_request)
    if isinstance(expected, CodexRegistrationPortValueRejected):
        return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_REQUEST)
    if type(value) is CodexRegistrationCommandFailed:
        return _revalidate_command_failure(value, expected, CodexCommandTarget.MARKETPLACE_ADD)
    if type(value) is not CodexMarketplaceAddSucceeded:
        return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)
    current = value
    bound = _validated_bound_request(current, expected)
    if isinstance(bound, CodexRegistrationPortValueRejected):
        return bound
    confirmed = _rebuild_marketplace_confirmation(current)
    if isinstance(confirmed, CodexRegistrationPortValueRejected):
        return confirmed
    observation = _rebuild_marketplace_observation(current)
    if isinstance(observation, CodexRegistrationPortValueRejected):
        return observation
    if (
        observation.marketplace_name.value != expected.preflight.marketplace.value
        or observation.installed_root.value != _canonical_observed_path(expected.source_locator)
    ):
        return _value_rejected(CodexRegistrationPortValueRejectReason.REQUEST_MISMATCH)
    if confirmed.already_added is not observation.already_added:
        return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)
    return CodexMarketplaceAddSucceeded(
        request=bound,
        confirmed=confirmed,
        observation=observation,
    )


def revalidate_plugin_add_result(
    value: object,
    expected_request: CodexRegistrationPortRequest,
) -> CodexPluginAddValidation:
    """Rebuild one plugin add success or exact-target command failure."""

    expected = revalidate_registration_port_request(expected_request)
    if isinstance(expected, CodexRegistrationPortValueRejected):
        return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_REQUEST)
    if type(value) is CodexRegistrationCommandFailed:
        return _revalidate_command_failure(value, expected, CodexCommandTarget.PLUGIN_ADD)
    if type(value) is not CodexPluginAddSucceeded:
        return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)
    current = value
    bound = _validated_bound_request(current, expected)
    if isinstance(bound, CodexRegistrationPortValueRejected):
        return bound
    confirmed = _rebuild_plugin_confirmation(current)
    if isinstance(confirmed, CodexRegistrationPortValueRejected):
        return confirmed
    observation = _rebuild_plugin_observation(current)
    if isinstance(observation, CodexRegistrationPortValueRejected):
        return observation
    if observation.version.value != expected.expected_version.value:
        return _value_rejected(CodexRegistrationPortValueRejectReason.VERSION_MISMATCH)
    if (
        observation.plugin_id.value != expected.expected_plugin_id.value
        or observation.name.value != expected.preflight.plugin.value
        or observation.marketplace_name.value != expected.preflight.marketplace.value
        or observation.auth_policy.value != expected.expected_auth_policy.value
        or observation.installed_path.value != _canonical_observed_path(expected.installed_locator)
    ):
        return _value_rejected(CodexRegistrationPortValueRejectReason.REQUEST_MISMATCH)
    return CodexPluginAddSucceeded(
        request=bound,
        confirmed=confirmed,
        observation=observation,
    )


def _request_fields_are_exact(value: CodexRegistrationPortRequest) -> bool:
    try:
        return (
            type(value.preflight) is CodexPreflightRequest
            and type(value.preflight.installation_id) is InstallationId
            and type(value.preflight.installation_id.value) is str
            and type(value.preflight.root) is InstallRoot
            and type(value.preflight.root.value) is str
            and type(value.preflight.marketplace) is CodexMarketplaceName
            and type(value.preflight.marketplace.value) is str
            and type(value.preflight.plugin) is CodexPluginName
            and type(value.preflight.plugin.value) is str
            and type(value.preflight.marketplace_source) is OwnedRelativePath
            and type(value.preflight.marketplace_source.value) is str
            and type(value.attempt_id) is CodexRegistrationAttemptId
            and type(value.attempt_id.value) is str
            and type(value.expected_version) is CodexCliVersion
            and type(value.expected_version.value) is str
            and type(value.source_locator) is OwnedRelativePath
            and type(value.source_locator.value) is str
            and type(value.installed_locator) is OwnedRelativePath
            and type(value.installed_locator.value) is str
            and type(value.digest) is ArtifactDigest
            and type(value.digest.value) is str
            and type(value.expected_auth_policy) is CodexAuthPolicy
            and type(value.expected_auth_policy.value) is str
            and type(value.expected_plugin_id) is CodexPluginId
            and type(value.expected_plugin_id.value) is str
        )
    except AttributeError:
        return False


def _requests_match(
    current: CodexRegistrationPortRequest,
    expected: CodexRegistrationPortRequest,
) -> bool:
    return (
        current.preflight.installation_id.value == expected.preflight.installation_id.value
        and current.preflight.root.value == expected.preflight.root.value
        and current.preflight.marketplace.value == expected.preflight.marketplace.value
        and current.preflight.plugin.value == expected.preflight.plugin.value
        and current.preflight.marketplace_source.value == expected.preflight.marketplace_source.value
        and current.attempt_id.value == expected.attempt_id.value
        and current.expected_version.value == expected.expected_version.value
        and current.source_locator.value == expected.source_locator.value
        and current.installed_locator.value == expected.installed_locator.value
        and current.digest.value == expected.digest.value
        and current.expected_auth_policy.value == expected.expected_auth_policy.value
        and current.expected_plugin_id.value == expected.expected_plugin_id.value
    )


def _validated_bound_request(
    value: CodexFreshPreflightAccepted
    | CodexFreshPreflightRejected
    | CodexMarketplaceAddSucceeded
    | CodexPluginAddSucceeded
    | CodexRegistrationCommandFailed,
    expected: CodexRegistrationPortRequest,
) -> CodexRegistrationPortRequestValidation:
    try:
        supplied_request: object = value.request
    except AttributeError:
        return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)
    rebuilt = revalidate_registration_port_request(supplied_request)
    if isinstance(rebuilt, CodexRegistrationPortValueRejected):
        return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)
    if not _requests_match(rebuilt, expected):
        return _value_rejected(CodexRegistrationPortValueRejectReason.REQUEST_MISMATCH)
    return rebuilt


def _rebuild_eligible(
    value: CodexFreshPreflightAccepted,
) -> CodexPreflightEligible | CodexRegistrationPortValueRejected:
    try:
        eligible: object = value.eligible
    except AttributeError:
        return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)
    if type(eligible) is not CodexPreflightEligible:
        return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)
    try:
        if (
            type(eligible.status) is not str
            or eligible.status != "ELIGIBLE"
            or type(eligible.version) is not CodexCliVersion
            or type(eligible.version.value) is not str
        ):
            return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)
        return CodexPreflightEligible(version=CodexCliVersion(value=eligible.version.value))
    except (AttributeError, TypeError, ValidationError, ValueError):
        return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)


def _rebuild_marketplace_confirmation(
    value: CodexMarketplaceAddSucceeded,
) -> CodexMarketplaceAddConfirmed | CodexRegistrationPortValueRejected:
    try:
        confirmed: object = value.confirmed
    except AttributeError:
        return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)
    if type(confirmed) is not CodexMarketplaceAddConfirmed:
        return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)
    try:
        if type(confirmed.target) is not CodexCommandTarget:
            return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)
        if confirmed.target is not CodexCommandTarget.MARKETPLACE_ADD:
            return _value_rejected(CodexRegistrationPortValueRejectReason.TARGET_MISMATCH)
        if confirmed.start_state is not CodexCommandStartState.STARTED or type(confirmed.already_added) is not bool:
            return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)
        return CodexMarketplaceAddConfirmed(
            target=confirmed.target,
            start_state=confirmed.start_state,
            already_added=confirmed.already_added,
        )
    except (AttributeError, TypeError, ValidationError, ValueError):
        return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)


def _rebuild_plugin_confirmation(
    value: CodexPluginAddSucceeded,
) -> CodexPluginAddConfirmed | CodexRegistrationPortValueRejected:
    try:
        confirmed: object = value.confirmed
    except AttributeError:
        return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)
    if type(confirmed) is not CodexPluginAddConfirmed:
        return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)
    try:
        if type(confirmed.target) is not CodexCommandTarget:
            return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)
        if confirmed.target is not CodexCommandTarget.PLUGIN_ADD:
            return _value_rejected(CodexRegistrationPortValueRejectReason.TARGET_MISMATCH)
        if confirmed.start_state is not CodexCommandStartState.STARTED:
            return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)
        return CodexPluginAddConfirmed(
            target=confirmed.target,
            start_state=confirmed.start_state,
        )
    except (AttributeError, TypeError, ValidationError, ValueError):
        return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)


def _rebuild_marketplace_observation(
    value: CodexMarketplaceAddSucceeded,
) -> CodexMarketplaceAddObservation | CodexRegistrationPortValueRejected:
    try:
        observation: object = value.observation
    except AttributeError:
        return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)
    if type(observation) is not CodexMarketplaceAddObservation:
        return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)
    try:
        if (
            type(observation.marketplace_name) is not CodexMarketplaceName
            or type(observation.marketplace_name.value) is not str
            or type(observation.installed_root) is not CodexObservedAbsolutePath
            or type(observation.installed_root.value) is not str
            or type(observation.already_added) is not bool
        ):
            return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)
        return CodexMarketplaceAddObservation(
            marketplace_name=CodexMarketplaceName(value=observation.marketplace_name.value),
            installed_root=CodexObservedAbsolutePath(value=observation.installed_root.value),
            already_added=observation.already_added,
        )
    except (AttributeError, TypeError, ValidationError, ValueError):
        return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)


def _rebuild_plugin_observation(
    value: CodexPluginAddSucceeded,
) -> CodexPluginAddObservation | CodexRegistrationPortValueRejected:
    try:
        observation: object = value.observation
    except AttributeError:
        return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)
    if type(observation) is not CodexPluginAddObservation:
        return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)
    try:
        if not _plugin_observation_fields_are_exact(observation):
            return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)
        return CodexPluginAddObservation(
            plugin_id=CodexPluginId(value=observation.plugin_id.value),
            name=CodexPluginName(value=observation.name.value),
            marketplace_name=CodexMarketplaceName(value=observation.marketplace_name.value),
            version=CodexCliVersion(value=observation.version.value),
            installed_path=CodexObservedAbsolutePath(value=observation.installed_path.value),
            auth_policy=CodexAuthPolicy(value=observation.auth_policy.value),
        )
    except (AttributeError, TypeError, ValidationError, ValueError):
        return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)


def _plugin_observation_fields_are_exact(value: CodexPluginAddObservation) -> bool:
    return (
        type(value.plugin_id) is CodexPluginId
        and type(value.plugin_id.value) is str
        and type(value.name) is CodexPluginName
        and type(value.name.value) is str
        and type(value.marketplace_name) is CodexMarketplaceName
        and type(value.marketplace_name.value) is str
        and type(value.version) is CodexCliVersion
        and type(value.version.value) is str
        and type(value.installed_path) is CodexObservedAbsolutePath
        and type(value.installed_path.value) is str
        and type(value.auth_policy) is CodexAuthPolicy
        and type(value.auth_policy.value) is str
    )


def _revalidate_command_failure(
    value: CodexRegistrationCommandFailed,
    expected: CodexRegistrationPortRequest,
    target: CodexCommandTarget,
) -> CodexRegistrationCommandFailed | CodexRegistrationPortValueRejected:
    bound = _validated_bound_request(value, expected)
    if isinstance(bound, CodexRegistrationPortValueRejected):
        return bound
    try:
        failure: object = value.failure
    except AttributeError:
        return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)
    rebuilt_failure: CodexPreStartFailure | CodexStartedFailure | CodexRegistrationPortValueRejected
    if type(failure) is CodexPreStartFailure:
        rebuilt_failure = _rebuild_pre_start_failure(failure, target)
    elif type(failure) is CodexStartedFailure:
        rebuilt_failure = _rebuild_started_failure(failure, target)
    else:
        return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)
    if isinstance(rebuilt_failure, CodexRegistrationPortValueRejected):
        return rebuilt_failure
    return CodexRegistrationCommandFailed(request=bound, failure=rebuilt_failure)


def _rebuild_pre_start_failure(
    failure: CodexPreStartFailure,
    target: CodexCommandTarget,
) -> CodexPreStartFailure | CodexRegistrationPortValueRejected:
    try:
        if type(failure.target) is not CodexCommandTarget:
            return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)
        if failure.target is not target:
            return _value_rejected(CodexRegistrationPortValueRejectReason.TARGET_MISMATCH)
        if (
            type(failure.reason) is not CodexPreStartFailureReason
            or failure.start_state is not CodexCommandStartState.NOT_STARTED
        ):
            return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)
        return CodexPreStartFailure(
            target=failure.target,
            reason=failure.reason,
            start_state=failure.start_state,
        )
    except (AttributeError, TypeError, ValidationError, ValueError):
        return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)


def _rebuild_started_failure(
    failure: CodexStartedFailure,
    target: CodexCommandTarget,
) -> CodexStartedFailure | CodexRegistrationPortValueRejected:
    try:
        if type(failure.target) is not CodexCommandTarget:
            return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)
        if failure.target is not target:
            return _value_rejected(CodexRegistrationPortValueRejectReason.TARGET_MISMATCH)
        if (
            type(failure.reason) is not CodexStartedFailureReason
            or failure.start_state is not CodexCommandStartState.STARTED
        ):
            return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)
        return CodexStartedFailure(
            target=failure.target,
            reason=failure.reason,
            start_state=failure.start_state,
        )
    except (AttributeError, TypeError, ValidationError, ValueError):
        return _value_rejected(CodexRegistrationPortValueRejectReason.INVALID_RESULT)


def _canonical_observed_path(locator: OwnedRelativePath) -> str:
    expanded_root = ntpath.expandvars(CANONICAL_INSTALL_ROOT)
    return ntpath.join(expanded_root, *locator.parts())


def _value_rejected(
    reason: CodexRegistrationPortValueRejectReason,
) -> CodexRegistrationPortValueRejected:
    return CodexRegistrationPortValueRejected(reason=reason)


CodexFreshPreflightOperation: TypeAlias = Callable[[CodexRegistrationPortRequest], CodexFreshPreflightResult]
CodexAddMarketplaceOperation: TypeAlias = Callable[[CodexRegistrationPortRequest], CodexMarketplaceAddResult]
CodexAddPluginOperation: TypeAlias = Callable[[CodexRegistrationPortRequest], CodexPluginAddResult]
CodexRegistrationProofOperation: TypeAlias = Callable[[CodexRegistrationProofRequest], CodexRegistrationProof]


class _CapabilityToken:
    """Private construction authority for an admitted capability."""


_CAPABILITY_TOKEN: Final[_CapabilityToken] = _CapabilityToken()


class CodexRegistrationPortCapability:
    """Four bound operations admitted without resolving candidate descriptors."""

    __slots__ = (
        "_authority",
        "status",
        "fresh_preflight",
        "add_marketplace",
        "add_plugin",
        "prove",
    )

    _authority: _CapabilityToken
    status: Literal["ADMITTED"]
    fresh_preflight: CodexFreshPreflightOperation
    add_marketplace: CodexAddMarketplaceOperation
    add_plugin: CodexAddPluginOperation
    prove: CodexRegistrationProofOperation

    def __init__(
        self,
        token: _CapabilityToken,
        fresh_preflight: CodexFreshPreflightOperation,
        add_marketplace: CodexAddMarketplaceOperation,
        add_plugin: CodexAddPluginOperation,
        prove: CodexRegistrationProofOperation,
    ) -> None:
        if token is not _CAPABILITY_TOKEN:
            raise TypeError("capability construction requires factory authority")
        object.__setattr__(self, "_authority", token)
        object.__setattr__(self, "status", "ADMITTED")
        object.__setattr__(self, "fresh_preflight", fresh_preflight)
        object.__setattr__(self, "add_marketplace", add_marketplace)
        object.__setattr__(self, "add_plugin", add_plugin)
        object.__setattr__(self, "prove", prove)

    def __setattr__(self, name: str, value: object) -> NoReturn:
        raise AttributeError("capability is immutable")

    def __copy__(self) -> NoReturn:
        raise TypeError("capability transfer is forbidden")

    def __deepcopy__(self, memo: dict[int, object]) -> NoReturn:
        raise TypeError("capability transfer is forbidden")

    def __reduce__(self) -> NoReturn:
        raise TypeError("capability transfer is forbidden")

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        raise TypeError("capability transfer is forbidden")

    def metadata(self) -> CodexRegistrationPortAdmitted:
        """Return only frozen public metadata, never the bound operations."""

        if object.__getattribute__(self, "_authority") is not _CAPABILITY_TOKEN:
            raise TypeError("capability authority is invalid")
        return CodexRegistrationPortAdmitted()

    def __repr__(self) -> str:
        self.metadata()
        return "CodexRegistrationPortCapability(status='ADMITTED', operation_count=4)"


class CodexRegistrationPortAdmitted(_StrictModel):
    """Safe serialization view for a successfully admitted capability."""

    status: Literal["ADMITTED"] = "ADMITTED"
    operation_count: Literal[4] = 4


class CodexRegistrationPortRejectReason(str, Enum):
    """Finite admission reasons without candidate or function metadata."""

    INVALID_CANDIDATE = "INVALID_CANDIDATE"
    MISSING_OPERATION = "MISSING_OPERATION"
    NON_PLAIN_FUNCTION = "NON_PLAIN_FUNCTION"
    PROPERTY_OPERATION = "PROPERTY_OPERATION"
    STATIC_METHOD_OPERATION = "STATIC_METHOD_OPERATION"
    CLASS_METHOD_OPERATION = "CLASS_METHOD_OPERATION"
    ZERO_REQUEST_ARGUMENTS = "ZERO_REQUEST_ARGUMENTS"
    TWO_REQUEST_ARGUMENTS = "TWO_REQUEST_ARGUMENTS"
    VARIADIC_ARGUMENTS = "VARIADIC_ARGUMENTS"
    REQUIRED_KEYWORD_ARGUMENTS = "REQUIRED_KEYWORD_ARGUMENTS"
    DEFAULTED_ARGUMENTS = "DEFAULTED_ARGUMENTS"


class CodexRegistrationPortRejected(_StrictModel):
    """Metadata-only admission rejection."""

    status: Literal["INVALID_PORT"] = "INVALID_PORT"
    reason: CodexRegistrationPortRejectReason


CodexRegistrationPortAdmission: TypeAlias = CodexRegistrationPortCapability | CodexRegistrationPortRejected


class _OperationName(str, Enum):
    FRESH_PREFLIGHT = "fresh_preflight"
    ADD_MARKETPLACE = "add_marketplace"
    ADD_PLUGIN = "add_plugin"
    PROVE = "prove"


_MISSING_OPERATION: Final[object] = object()
_FUNCTION_VARARGS_FLAG: Final[int] = 0x04
_FUNCTION_VARKWARGS_FLAG: Final[int] = 0x08
_TYPE_MRO_GETSET: Final[GetSetDescriptorType] = cast(GetSetDescriptorType, type.__dict__["__mro__"])
_TYPE_DICTIONARY_GETSET: Final[GetSetDescriptorType] = cast(GetSetDescriptorType, type.__dict__["__dict__"])


def admit_codex_registration_port(candidate: object) -> CodexRegistrationPortAdmission:
    """Admit four exact plain methods without resolving or executing candidate members."""

    if candidate is None:
        return _port_rejected(CodexRegistrationPortRejectReason.INVALID_CANDIDATE)
    candidate_class = type(candidate)
    if candidate_class is str or candidate_class is tuple or candidate_class is list or candidate_class is dict:
        return _port_rejected(CodexRegistrationPortRejectReason.INVALID_CANDIDATE)
    fresh = _admit_operation(candidate_class, _OperationName.FRESH_PREFLIGHT)
    if isinstance(fresh, CodexRegistrationPortRejected):
        return fresh
    marketplace = _admit_operation(candidate_class, _OperationName.ADD_MARKETPLACE)
    if isinstance(marketplace, CodexRegistrationPortRejected):
        return marketplace
    plugin = _admit_operation(candidate_class, _OperationName.ADD_PLUGIN)
    if isinstance(plugin, CodexRegistrationPortRejected):
        return plugin
    proof = _admit_operation(candidate_class, _OperationName.PROVE)
    if isinstance(proof, CodexRegistrationPortRejected):
        return proof
    return CodexRegistrationPortCapability(
        _CAPABILITY_TOKEN,
        cast(CodexFreshPreflightOperation, MethodType(fresh, candidate)),
        cast(CodexAddMarketplaceOperation, MethodType(marketplace, candidate)),
        cast(CodexAddPluginOperation, MethodType(plugin, candidate)),
        cast(CodexRegistrationProofOperation, MethodType(proof, candidate)),
    )


def _admit_operation(
    candidate_class: type[object],
    operation: _OperationName,
) -> FunctionType | CodexRegistrationPortRejected:
    raw_member = _raw_member_from_mro(candidate_class, operation)
    if raw_member is _MISSING_OPERATION:
        return _port_rejected(CodexRegistrationPortRejectReason.MISSING_OPERATION)
    if type(raw_member) is property:
        return _port_rejected(CodexRegistrationPortRejectReason.PROPERTY_OPERATION)
    if type(raw_member) is staticmethod:
        return _port_rejected(CodexRegistrationPortRejectReason.STATIC_METHOD_OPERATION)
    if type(raw_member) is classmethod:
        return _port_rejected(CodexRegistrationPortRejectReason.CLASS_METHOD_OPERATION)
    if type(raw_member) is not FunctionType:
        return _port_rejected(CodexRegistrationPortRejectReason.NON_PLAIN_FUNCTION)
    shape_reason = _plain_function_shape_reason(raw_member)
    if shape_reason is not None:
        return _port_rejected(shape_reason)
    return raw_member


def _raw_member_from_mro(candidate_class: type[object], operation: _OperationName) -> object:
    mro_value: object = _TYPE_MRO_GETSET.__get__(candidate_class, type)
    if type(mro_value) is not tuple:
        return _MISSING_OPERATION
    for owner_value in cast(tuple[object, ...], mro_value):
        owner = cast(type[object], owner_value)
        dictionary_value: object = _TYPE_DICTIONARY_GETSET.__get__(owner, type)
        if type(dictionary_value) is not MappingProxyType:
            return _MISSING_OPERATION
        dictionary = cast(MappingProxyType[str, object], dictionary_value)
        try:
            return dictionary[operation.value]
        except KeyError:
            continue
    return _MISSING_OPERATION


def _plain_function_shape_reason(
    function: FunctionType,
) -> CodexRegistrationPortRejectReason | None:
    code_value = object.__getattribute__(function, "__code__")
    defaults_value = object.__getattribute__(function, "__defaults__")
    keyword_defaults_value = object.__getattribute__(function, "__kwdefaults__")
    if type(code_value) is not CodeType:
        return CodexRegistrationPortRejectReason.NON_PLAIN_FUNCTION
    code = code_value
    if defaults_value is not None or keyword_defaults_value is not None:
        return CodexRegistrationPortRejectReason.DEFAULTED_ARGUMENTS
    if code.co_flags & (_FUNCTION_VARARGS_FLAG | _FUNCTION_VARKWARGS_FLAG):
        return CodexRegistrationPortRejectReason.VARIADIC_ARGUMENTS
    if code.co_kwonlyargcount != 0:
        return CodexRegistrationPortRejectReason.REQUIRED_KEYWORD_ARGUMENTS
    if code.co_argcount < 2:
        return CodexRegistrationPortRejectReason.ZERO_REQUEST_ARGUMENTS
    if code.co_argcount > 2:
        return CodexRegistrationPortRejectReason.TWO_REQUEST_ARGUMENTS
    return None


def _port_rejected(reason: CodexRegistrationPortRejectReason) -> CodexRegistrationPortRejected:
    return CodexRegistrationPortRejected(reason=reason)
