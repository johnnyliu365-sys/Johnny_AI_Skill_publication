"""Strict, effect-free contracts for one current Codex registration attempt."""

from __future__ import annotations

from enum import Enum
import ntpath
from typing import Literal, Protocol, Self, TypeAlias, runtime_checkable

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from .contracts import CANONICAL_INSTALL_ROOT, ArtifactDigest, InstallRoot, InstallationId, OwnedRelativePath
from .host_contracts import CodexCliVersion, CodexMarketplaceName, CodexPluginName, CodexPreflightRequest


class _StrictModel(BaseModel):
    """Reject unchecked values at the production registration boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, revalidate_instances="always")


def _require_nonblank(value: str, label: str) -> str:
    if not value or value != value.strip() or "\x00" in value:
        raise ValueError(f"{label} must be nonblank and NUL-free")
    return value


def _canonical_observed_path(locator: OwnedRelativePath) -> str:
    """Derive one case-sensitive observed path below the canonical install root."""

    expanded_root = ntpath.expandvars(CANONICAL_INSTALL_ROOT)
    drive, _ = ntpath.splitdrive(expanded_root)
    if not drive or not ntpath.isabs(expanded_root) or ntpath.normpath(expanded_root) != expanded_root:
        raise ValueError("canonical install root expansion must be absolute")
    return ntpath.join(expanded_root, *locator.parts())


class _CodexTextValue(_StrictModel):
    value: str

    @field_validator("value")
    @classmethod
    def exact_text(cls, value: str) -> str:
        return _require_nonblank(value, cls.__name__)


class CodexPluginId(_CodexTextValue):
    """The exact plugin identifier returned by a successful add response."""


class CodexAuthPolicy(_CodexTextValue):
    """A non-secret, named policy observation returned by the CLI."""


DEFAULT_EXPECTED_AUTH_POLICY = CodexAuthPolicy(value="trusted-local")


class CodexObservedAbsolutePath(_StrictModel):
    """An observed Windows path that may be compared but never persisted in a receipt."""

    value: str

    @field_validator("value")
    @classmethod
    def exact_windows_absolute_path(cls, value: str) -> str:
        value = _require_nonblank(value, "observed absolute path")
        folded = value.casefold()
        drive, _ = ntpath.splitdrive(value)
        components = value.replace("/", "\\").split("\\")
        if (
            not drive
            or not ntpath.isabs(value)
            or "://" in value
            or "%2f" in folded
            or "%5c" in folded
            or any(component in ("", ".", "..") for component in components[1:])
        ):
            raise ValueError("observed path must be a canonical Windows absolute path")
        return value


class CodexRegistrationAttemptId(_StrictModel):
    """Opaque metadata that binds a journal to one current attempt."""

    value: str

    @field_validator("value")
    @classmethod
    def opaque_attempt_id(cls, value: str) -> str:
        prefix = "attempt-"
        suffix = value[len(prefix) :] if value.startswith(prefix) else ""
        if len(suffix) != 16 or any(character not in "0123456789abcdef" for character in suffix):
            raise ValueError("attempt id must be an opaque lowercase identifier")
        return value


class CodexMarketplaceAddObservation(_StrictModel):
    """The complete strict marketplace-add observation needed for a proof request."""

    marketplace_name: CodexMarketplaceName
    installed_root: CodexObservedAbsolutePath
    already_added: bool


class CodexPluginAddObservation(_StrictModel):
    """The complete strict plugin-add observation needed for a proof request."""

    plugin_id: CodexPluginId
    name: CodexPluginName
    marketplace_name: CodexMarketplaceName
    version: CodexCliVersion
    installed_path: CodexObservedAbsolutePath
    auth_policy: CodexAuthPolicy


class CodexRegistrationProofRequest(_StrictModel):
    """One exact current request and its complete observed add DTOs."""

    preflight: CodexPreflightRequest
    version: CodexCliVersion
    marketplace_observation: CodexMarketplaceAddObservation
    plugin_observation: CodexPluginAddObservation
    source_locator: OwnedRelativePath
    installed_locator: OwnedRelativePath
    digest: ArtifactDigest
    expected_auth_policy: CodexAuthPolicy = DEFAULT_EXPECTED_AUTH_POLICY

    @model_validator(mode="after")
    def exact_request_observation_binding(self) -> Self:
        if self.source_locator != self.preflight.marketplace_source:
            raise ValueError("proof source locator must bind the preflight request")
        if self.marketplace_observation.marketplace_name != self.preflight.marketplace:
            raise ValueError("marketplace observation must bind the preflight request")
        if self.plugin_observation.name != self.preflight.plugin:
            raise ValueError("plugin observation must bind the preflight request")
        if self.plugin_observation.marketplace_name != self.preflight.marketplace:
            raise ValueError("plugin marketplace must bind the preflight request")
        if self.plugin_observation.auth_policy != self.expected_auth_policy:
            raise ValueError("plugin auth policy must bind the request authority")
        if self.marketplace_observation.installed_root.value != _canonical_observed_path(self.source_locator):
            raise ValueError("marketplace observation must bind the canonical source locator")
        if self.plugin_observation.installed_path.value != _canonical_observed_path(self.installed_locator):
            raise ValueError("plugin observation must bind the canonical installed locator")
        return self


class CodexRegistrationProof(_StrictModel):
    """The proof-port output that must match every receipt-bound observation."""

    installation_id: InstallationId
    root: InstallRoot
    marketplace: CodexMarketplaceName
    plugin_id: CodexPluginId
    plugin_name: CodexPluginName
    version: CodexCliVersion
    source_locator: OwnedRelativePath
    installed_locator: OwnedRelativePath
    auth_policy: CodexAuthPolicy
    digest: ArtifactDigest
    observed_marketplace_root: CodexObservedAbsolutePath
    observed_marketplace_already_added: bool
    observed_plugin_path: CodexObservedAbsolutePath


class CodexRegistrationProofPortFailure(Exception):
    """The one declared finite failure raised by a proof-port implementation."""


@runtime_checkable
class CodexRegistrationProofPort(Protocol):
    """Required non-null boundary that returns proof for one exact request."""

    def prove(self, request: CodexRegistrationProofRequest) -> CodexRegistrationProof:
        """Return only an exact proof for the supplied current attempt."""


class CodexRegistrationReceipt(_StrictModel):
    """Metadata-only registration receipt with no observed absolute path."""

    installation_id: InstallationId
    root: InstallRoot
    marketplace: CodexMarketplaceName
    plugin_id: CodexPluginId
    plugin_name: CodexPluginName
    version: CodexCliVersion
    source_locator: OwnedRelativePath
    installed_locator: OwnedRelativePath
    auth_policy: CodexAuthPolicy
    digest: ArtifactDigest


class CodexRegistrationRejectReason(str, Enum):
    INVALID_INPUT = "INVALID_INPUT"
    INVALID_PROOF_PORT = "INVALID_PROOF_PORT"
    PROOF_PORT_FAILED = "PROOF_PORT_FAILED"
    INVALID_PROOF = "INVALID_PROOF"
    PROOF_MISMATCH = "PROOF_MISMATCH"
    JOURNAL_INVALID = "JOURNAL_INVALID"
    JOURNAL_REQUEST_MISMATCH = "JOURNAL_REQUEST_MISMATCH"
    JOURNAL_ATTEMPT_MISMATCH = "JOURNAL_ATTEMPT_MISMATCH"


class CodexRegistrationRejected(_StrictModel):
    """Finite failure result that retains no raw port error or path."""

    status: Literal["REGISTRATION_BLOCKED"] = "REGISTRATION_BLOCKED"
    reason: CodexRegistrationRejectReason


CodexRegistrationResult: TypeAlias = CodexRegistrationReceipt | CodexRegistrationRejected


def issue_registration_receipt(
    request: CodexRegistrationProofRequest,
    proof_port: CodexRegistrationProofPort,
) -> CodexRegistrationResult:
    """Issue a receipt only after recursive request, observation and proof equality."""

    validated_request = _revalidate_proof_request(request)
    if isinstance(validated_request, CodexRegistrationRejected):
        return validated_request
    if not isinstance(proof_port, CodexRegistrationProofPort):
        return CodexRegistrationRejected(reason=CodexRegistrationRejectReason.INVALID_PROOF_PORT)
    try:
        proof = proof_port.prove(validated_request)
    except CodexRegistrationProofPortFailure:
        return CodexRegistrationRejected(reason=CodexRegistrationRejectReason.PROOF_PORT_FAILED)
    try:
        validated_proof = CodexRegistrationProof.model_validate_json(proof.model_dump_json(warnings=False))
    except (AttributeError, TypeError, ValidationError, ValueError):
        return CodexRegistrationRejected(reason=CodexRegistrationRejectReason.INVALID_PROOF)
    if not _proof_matches_request(validated_proof, validated_request):
        return CodexRegistrationRejected(reason=CodexRegistrationRejectReason.PROOF_MISMATCH)
    return CodexRegistrationReceipt(
        installation_id=validated_request.preflight.installation_id,
        root=validated_request.preflight.root,
        marketplace=validated_request.preflight.marketplace,
        plugin_id=validated_request.plugin_observation.plugin_id,
        plugin_name=validated_request.plugin_observation.name,
        version=validated_request.version,
        source_locator=validated_request.source_locator,
        installed_locator=validated_request.installed_locator,
        auth_policy=validated_request.expected_auth_policy,
        digest=validated_request.digest,
    )


def _revalidate_proof_request(
    request: CodexRegistrationProofRequest,
) -> CodexRegistrationProofRequest | CodexRegistrationRejected:
    try:
        return CodexRegistrationProofRequest.model_validate_json(request.model_dump_json(warnings=False))
    except (AttributeError, TypeError, ValidationError, ValueError):
        return CodexRegistrationRejected(reason=CodexRegistrationRejectReason.INVALID_INPUT)


def _proof_matches_request(
    proof: CodexRegistrationProof,
    request: CodexRegistrationProofRequest,
) -> bool:
    return (
        proof.installation_id == request.preflight.installation_id
        and proof.root == request.preflight.root
        and proof.marketplace == request.preflight.marketplace
        and proof.plugin_id == request.plugin_observation.plugin_id
        and proof.plugin_name == request.plugin_observation.name
        and proof.version == request.version
        and proof.source_locator == request.source_locator
        and proof.installed_locator == request.installed_locator
        and proof.auth_policy == request.expected_auth_policy
        and proof.digest == request.digest
        and proof.observed_marketplace_root == request.marketplace_observation.installed_root
        and proof.observed_marketplace_already_added == request.marketplace_observation.already_added
        and proof.observed_plugin_path == request.plugin_observation.installed_path
    )


class CodexAttemptEffectState(str, Enum):
    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    MAY_EXIST = "MAY_EXIST"
    OWNED = "OWNED"
    PREEXISTING = "PREEXISTING"


class CodexAttemptEffect(str, Enum):
    PLUGIN = "PLUGIN"
    MARKETPLACE = "MARKETPLACE"


_LEGAL_ATTEMPT_STATE_PAIRS: frozenset[tuple[CodexAttemptEffectState, CodexAttemptEffectState]] = frozenset(
    (
        (CodexAttemptEffectState.NOT_ATTEMPTED, CodexAttemptEffectState.NOT_ATTEMPTED),
        (CodexAttemptEffectState.MAY_EXIST, CodexAttemptEffectState.NOT_ATTEMPTED),
        (CodexAttemptEffectState.OWNED, CodexAttemptEffectState.NOT_ATTEMPTED),
        (CodexAttemptEffectState.OWNED, CodexAttemptEffectState.MAY_EXIST),
        (CodexAttemptEffectState.OWNED, CodexAttemptEffectState.OWNED),
        (CodexAttemptEffectState.OWNED, CodexAttemptEffectState.PREEXISTING),
        (CodexAttemptEffectState.PREEXISTING, CodexAttemptEffectState.NOT_ATTEMPTED),
    )
)


class CodexRegistrationAttemptJournal(_StrictModel):
    """Finite current-attempt authority with plugin-first unresolved ordering."""

    request: CodexPreflightRequest
    attempt_id: CodexRegistrationAttemptId
    marketplace_state: CodexAttemptEffectState
    plugin_state: CodexAttemptEffectState

    @model_validator(mode="after")
    def legal_attempt_order(self) -> Self:
        state_pair = (self.marketplace_state, self.plugin_state)
        if state_pair not in _LEGAL_ATTEMPT_STATE_PAIRS:
            raise ValueError("marketplace and plugin attempt states are not causally legal")
        return self

    def unresolved_removal_order(self) -> tuple[CodexAttemptEffect, ...]:
        effects: list[CodexAttemptEffect] = []
        if _has_removal_authority(self.plugin_state):
            effects.append(CodexAttemptEffect.PLUGIN)
        if _has_removal_authority(self.marketplace_state):
            effects.append(CodexAttemptEffect.MARKETPLACE)
        return tuple(effects)


def _has_removal_authority(state: CodexAttemptEffectState) -> bool:
    return state in (CodexAttemptEffectState.MAY_EXIST, CodexAttemptEffectState.OWNED)


CodexJournalValidationResult: TypeAlias = CodexRegistrationAttemptJournal | CodexRegistrationRejected


def revalidate_current_attempt_journal(
    journal: CodexRegistrationAttemptJournal,
    request: CodexPreflightRequest,
    attempt_id: CodexRegistrationAttemptId,
) -> CodexJournalValidationResult:
    """Fail closed for malformed, replayed or cross-request journal authority."""

    try:
        validated_journal = CodexRegistrationAttemptJournal.model_validate_json(journal.model_dump_json(warnings=False))
        validated_request = CodexPreflightRequest.model_validate_json(request.model_dump_json(warnings=False))
        validated_attempt = CodexRegistrationAttemptId.model_validate_json(attempt_id.model_dump_json(warnings=False))
    except (AttributeError, TypeError, ValidationError, ValueError):
        return CodexRegistrationRejected(reason=CodexRegistrationRejectReason.JOURNAL_INVALID)
    if validated_journal.request != validated_request:
        return CodexRegistrationRejected(reason=CodexRegistrationRejectReason.JOURNAL_REQUEST_MISMATCH)
    if validated_journal.attempt_id != validated_attempt:
        return CodexRegistrationRejected(reason=CodexRegistrationRejectReason.JOURNAL_ATTEMPT_MISMATCH)
    return validated_journal
