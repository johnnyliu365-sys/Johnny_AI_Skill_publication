"""Thin exact composition of an admitted compensation port and pure reducer."""

from __future__ import annotations

from enum import Enum
from types import MethodType
from typing import Literal, TypeAlias, cast

from pydantic import BaseModel, ConfigDict, ValidationError

from .codex_compensation_port import (
    CodexCompensationPortCapability,
    CodexCompensationPortFailureReason,
    CodexCompensationPortOperation,
    CodexCompensationPortOperationFailed,
    CodexCompensationPortManifest,
    CodexCompensationPortRequest,
    CodexCompensationPortValueRejected,
    CodexInstalledPathAbsenceProof,
    CodexMarketplaceRemovalProof,
    CodexPluginRemovalProof,
    revalidate_codex_compensation_port_request,
)
from .codex_compensation_reducer import (
    CodexCompensationBlocked,
    CodexCompensationBlockReason,
    CodexCompensationNoop,
    CodexCompensationObservation,
    CodexCompensationPlan,
    CodexCompensationResult,
    CodexCompensationStep,
    CodexInstalledLocationProof,
    CodexMarketplaceProof,
    CodexNoCompensationPlan,
    CodexPluginListsProof,
    CodexProofTruth,
    CodexRemovalConfirmed,
    CodexRemovalFailed,
    reduce_compensation,
)
from .codex_registration_contracts import CodexAuthPolicy, CodexPluginId
from .contracts import ArtifactDigest, InstallRoot, InstallationId, OwnedRelativePath
from .host_contracts import (
    CodexCliVersion,
    CodexMarketplaceEntry,
    CodexMarketplaceList,
    CodexMarketplaceName,
    CodexMarketplaceSource,
    CodexPluginEntry,
    CodexPluginList,
    CodexPluginName,
)


_FAILURE_STATE_FIELDS: tuple[str, ...] = ("manifest", "operation", "status", "reason")
_MANIFEST_STATE_FIELDS: tuple[str, ...] = (
    "installation_id",
    "root",
    "marketplace",
    "marketplace_source",
    "plugin_id",
    "plugin",
    "version",
    "installed_locator",
    "auth_policy",
    "digest",
)
_VALUE_STATE_FIELDS: tuple[str, ...] = ("value",)
_REMOVAL_PROOF_STATE_FIELDS: tuple[str, ...] = ("manifest", "status")
_INSTALLED_PATH_PROOF_STATE_FIELDS: tuple[str, ...] = ("manifest", "absent")
_PLUGIN_LIST_STATE_FIELDS: tuple[str, ...] = ("installed", "available")
_PLUGIN_ENTRY_STATE_FIELDS: tuple[str, ...] = (
    "pluginId",
    "name",
    "marketplaceName",
    "version",
    "installed",
    "enabled",
    "source",
    "installPolicy",
    "authPolicy",
    "marketplaceSource",
)
_MARKETPLACE_LIST_STATE_FIELDS: tuple[str, ...] = ("marketplaces",)
_MARKETPLACE_ENTRY_STATE_FIELDS: tuple[str, ...] = ("name", "root", "marketplaceSource")
_MARKETPLACE_SOURCE_STATE_FIELDS: tuple[str, ...] = ("type", "value")


class CodexCompensationObservationRejectReason(str, Enum):
    """Finite reasons for rejecting a pure compensation observation request."""

    INVALID_OPERATION = "INVALID_OPERATION"
    INVALID_REQUEST = "INVALID_REQUEST"


class _ObservationModel(BaseModel):
    """Strict, frozen metadata-only public observation envelope."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, revalidate_instances="always")


class CodexCompensationObservationRejected(_ObservationModel):
    """Finite rejection without response or effect-boundary data."""

    status: Literal["OBSERVATION_REJECTED"]
    reason: CodexCompensationObservationRejectReason


CodexCompensationObservationResult: TypeAlias = (
    CodexCompensationObservation | CodexCompensationObservationRejected
)


def observe_codex_compensation_operation(
    operation: object,
    value: object,
    request: object,
) -> CodexCompensationObservationResult:
    """Normalize one exact returned operation value without invoking an effect boundary."""

    if type(operation) is not CodexCompensationPortOperation:
        return CodexCompensationObservationRejected(
            status="OBSERVATION_REJECTED",
            reason=CodexCompensationObservationRejectReason.INVALID_OPERATION,
        )
    request_revalidation = revalidate_codex_compensation_port_request(request)
    if type(request_revalidation) is CodexCompensationPortValueRejected:
        return CodexCompensationObservationRejected(
            status="OBSERVATION_REJECTED",
            reason=CodexCompensationObservationRejectReason.INVALID_REQUEST,
        )
    validated_request = cast(CodexCompensationPortRequest, request_revalidation)
    if operation is CodexCompensationPortOperation.REMOVE_PLUGIN:
        return _plugin_removal_observation(value, validated_request)
    if operation is CodexCompensationPortOperation.REMOVE_MARKETPLACE:
        return _marketplace_removal_observation(value, validated_request)
    if operation is CodexCompensationPortOperation.LIST_PLUGINS:
        return _plugin_list_observation(value, validated_request)
    if operation is CodexCompensationPortOperation.LIST_MARKETPLACES:
        return _marketplace_list_observation(value, validated_request)
    return _installed_path_observation(value, validated_request)


def compose_codex_compensation(
    capability: CodexCompensationPortCapability,
    request: CodexCompensationPortRequest,
    plan: CodexCompensationPlan | CodexNoCompensationPlan,
) -> CodexCompensationResult:
    """Validate all identities, execute the frozen plan, and return reducer truth."""

    if not _capability_is_exact(capability):
        return _plan_invalid()
    request_revalidation = revalidate_codex_compensation_port_request(request)
    if type(request_revalidation) is CodexCompensationPortValueRejected:
        return _plan_invalid()
    if type(plan) is not CodexCompensationPlan and type(plan) is not CodexNoCompensationPlan:
        return _plan_invalid()
    validated_plan = plan
    plan_preflight = reduce_compensation(validated_plan, ())
    if isinstance(plan_preflight, CodexCompensationNoop):
        if not _request_matches_plan(request, validated_plan):
            return _plan_invalid()
        return plan_preflight
    if (
        type(validated_plan) is not CodexCompensationPlan
        or not isinstance(plan_preflight, CodexCompensationBlocked)
        or plan_preflight.reason is not CodexCompensationBlockReason.OUTCOME_SEQUENCE_INVALID
        or not _request_matches_plan(request, validated_plan)
    ):
        return _plan_invalid()
    outcomes: list[CodexCompensationObservation] = []
    for step in validated_plan.steps:
        if step is CodexCompensationStep.REMOVE_PLUGIN:
            returned_plugin_removal: object = capability.remove_plugin(request)
            outcomes.append(_plugin_removal_observation(returned_plugin_removal, request))
        elif step is CodexCompensationStep.REMOVE_MARKETPLACE:
            returned_marketplace_removal: object = capability.remove_marketplace(request)
            outcomes.append(_marketplace_removal_observation(returned_marketplace_removal, request))
        elif step is CodexCompensationStep.PROVE_PLUGIN_LISTS_ABSENT:
            returned_plugins: object = capability.list_plugins(request)
            outcomes.append(_plugin_list_observation(returned_plugins, request))
        elif step is CodexCompensationStep.PROVE_MARKETPLACE_ABSENT:
            returned_marketplaces: object = capability.list_marketplaces(request)
            outcomes.append(_marketplace_list_observation(returned_marketplaces, request))
        else:
            returned_path_proof: object = capability.prove_installed_path_absent(request)
            outcomes.append(_installed_path_observation(returned_path_proof, request))
    return reduce_compensation(validated_plan, tuple(outcomes))


def _plan_invalid() -> CodexCompensationBlocked:
    return CodexCompensationBlocked(
        status="COMPENSATION_BLOCKED",
        reason=CodexCompensationBlockReason.PLAN_INVALID,
    )


def _capability_is_exact(value: object) -> bool:
    if type(value) is not CodexCompensationPortCapability:
        return False
    capability = value
    try:
        return (
            type(capability.status) is str
            and capability.status == "ADMITTED"
            and type(capability.remove_plugin) is MethodType
            and type(capability.remove_marketplace) is MethodType
            and type(capability.list_plugins) is MethodType
            and type(capability.list_marketplaces) is MethodType
            and type(capability.prove_installed_path_absent) is MethodType
        )
    except AttributeError:
        return False


def _manifest_is_exact(value: object) -> bool:
    if type(value) is not CodexCompensationPortManifest:
        return False
    current = value
    try:
        if not _manifest_has_exact_original_state(current):
            return False
        exact_shape = (
            type(current.installation_id) is InstallationId
            and type(current.installation_id.value) is str
            and type(current.root) is InstallRoot
            and type(current.root.value) is str
            and type(current.marketplace) is CodexMarketplaceName
            and type(current.marketplace.value) is str
            and type(current.marketplace_source) is OwnedRelativePath
            and type(current.marketplace_source.value) is str
            and type(current.plugin_id) is CodexPluginId
            and type(current.plugin_id.value) is str
            and type(current.plugin) is CodexPluginName
            and type(current.plugin.value) is str
            and type(current.version) is CodexCliVersion
            and type(current.version.value) is str
            and type(current.installed_locator) is OwnedRelativePath
            and type(current.installed_locator.value) is str
            and type(current.auth_policy) is CodexAuthPolicy
            and type(current.auth_policy.value) is str
            and type(current.digest) is ArtifactDigest
            and type(current.digest.value) is str
        )
        if not exact_shape:
            return False
        CodexCompensationPortManifest(
            installation_id=InstallationId(value=current.installation_id.value),
            root=InstallRoot(value=current.root.value),
            marketplace=CodexMarketplaceName(value=current.marketplace.value),
            marketplace_source=OwnedRelativePath(value=current.marketplace_source.value),
            plugin_id=CodexPluginId(value=current.plugin_id.value),
            plugin=CodexPluginName(value=current.plugin.value),
            version=CodexCliVersion(value=current.version.value),
            installed_locator=OwnedRelativePath(value=current.installed_locator.value),
            auth_policy=CodexAuthPolicy(value=current.auth_policy.value),
            digest=ArtifactDigest(value=current.digest.value),
        )
    except (AttributeError, TypeError, ValidationError, ValueError):
        return False
    return True


def _manifest_has_exact_original_state(value: CodexCompensationPortManifest) -> bool:
    """Require fixed declared storage on the original manifest and every nested value."""

    return (
        _has_exact_model_state(value, _MANIFEST_STATE_FIELDS)
        and _has_exact_model_state(value.installation_id, _VALUE_STATE_FIELDS)
        and _has_exact_model_state(value.root, _VALUE_STATE_FIELDS)
        and _has_exact_model_state(value.marketplace, _VALUE_STATE_FIELDS)
        and _has_exact_model_state(value.marketplace_source, _VALUE_STATE_FIELDS)
        and _has_exact_model_state(value.plugin_id, _VALUE_STATE_FIELDS)
        and _has_exact_model_state(value.plugin, _VALUE_STATE_FIELDS)
        and _has_exact_model_state(value.version, _VALUE_STATE_FIELDS)
        and _has_exact_model_state(value.installed_locator, _VALUE_STATE_FIELDS)
        and _has_exact_model_state(value.auth_policy, _VALUE_STATE_FIELDS)
        and _has_exact_model_state(value.digest, _VALUE_STATE_FIELDS)
    )


def _has_exact_model_state(
    value: BaseModel,
    expected_fields: tuple[str, ...],
    optional_unset_fields: tuple[str, ...] = (),
) -> bool:
    """Read only fixed Pydantic storage after exact type admission."""

    state: object = object.__getattribute__(value, "__dict__")
    extras: object = object.__getattribute__(value, "__pydantic_extra__")
    private: object = object.__getattribute__(value, "__pydantic_private__")
    fields_set: object = object.__getattribute__(value, "__pydantic_fields_set__")
    if type(state) is not dict or extras is not None or private is not None or type(fields_set) is not set:
        return False
    if any(field not in expected_fields for field in optional_unset_fields):
        return False
    if len(state) != len(expected_fields) or len(fields_set) not in (
        len(expected_fields),
        len(expected_fields) - len(optional_unset_fields),
    ):
        return False
    for key in state:
        if type(key) is not str:
            return False
    for key in fields_set:
        if type(key) is not str or key not in expected_fields:
            return False
    for expected in expected_fields:
        if expected not in state:
            return False
        if expected not in optional_unset_fields and expected not in fields_set:
            return False
    for optional in optional_unset_fields:
        if optional not in fields_set and state[optional] is not None:
            return False
    return True


def _operation_failure_matches(
    value: object,
    expected_operation: CodexCompensationPortOperation,
    request: CodexCompensationPortRequest,
) -> bool:
    """Admit only a complete exact failure for the invoked manifest-bound operation."""

    if type(value) is not CodexCompensationPortOperationFailed:
        return False
    failure = value
    try:
        if not _has_exact_model_state(failure, _FAILURE_STATE_FIELDS):
            return False
        returned_manifest: object = object.__getattribute__(failure, "manifest")
        operation: object = object.__getattribute__(failure, "operation")
        status: object = object.__getattribute__(failure, "status")
        reason: object = object.__getattribute__(failure, "reason")
    except AttributeError:
        return False
    return (
        type(returned_manifest) is CodexCompensationPortManifest
        and _manifest_is_exact(returned_manifest)
        and type(operation) is CodexCompensationPortOperation
        and operation is expected_operation
        and type(status) is str
        and status == "FAILED"
        and type(reason) is CodexCompensationPortFailureReason
        and _manifests_match(returned_manifest, request.manifest)
    )


def _request_matches_plan(
    request: CodexCompensationPortRequest,
    plan: CodexCompensationPlan | CodexNoCompensationPlan,
) -> bool:
    current = request.manifest
    expected = plan.request
    return (
        current.installation_id.value == expected.installation_id.value
        and current.root.value == expected.root.value
        and current.marketplace.value == expected.marketplace.value
        and current.plugin.value == expected.plugin.value
        and current.marketplace_source.value == expected.marketplace_source.value
    )


def _manifests_match(
    returned: CodexCompensationPortManifest,
    expected: CodexCompensationPortManifest,
) -> bool:
    return (
        returned.installation_id.value == expected.installation_id.value
        and returned.root.value == expected.root.value
        and returned.marketplace.value == expected.marketplace.value
        and returned.marketplace_source.value == expected.marketplace_source.value
        and returned.plugin_id.value == expected.plugin_id.value
        and returned.plugin.value == expected.plugin.value
        and returned.version.value == expected.version.value
        and returned.installed_locator.value == expected.installed_locator.value
        and returned.auth_policy.value == expected.auth_policy.value
        and returned.digest.value == expected.digest.value
    )


def _plugin_removal_observation(
    value: object,
    request: CodexCompensationPortRequest,
) -> CodexRemovalConfirmed | CodexRemovalFailed:
    failed = CodexRemovalFailed(
        step=CodexCompensationStep.REMOVE_PLUGIN,
        status="DECLARED_FAILURE",
    )
    if _operation_failure_matches(value, CodexCompensationPortOperation.REMOVE_PLUGIN, request):
        return failed
    if type(value) is not CodexPluginRemovalProof:
        return failed
    proof = value
    try:
        if not _has_exact_model_state(proof, _REMOVAL_PROOF_STATE_FIELDS):
            return failed
        returned_manifest: object = proof.manifest
        status: object = proof.status
    except AttributeError:
        return failed
    if (
        not _manifest_is_exact(returned_manifest)
        or type(status) is not str
        or status != "REMOVED"
        or not _manifests_match(cast(CodexCompensationPortManifest, returned_manifest), request.manifest)
    ):
        return failed
    return CodexRemovalConfirmed(
        step=CodexCompensationStep.REMOVE_PLUGIN,
        status="CONFIRMED",
    )


def _marketplace_removal_observation(
    value: object,
    request: CodexCompensationPortRequest,
) -> CodexRemovalConfirmed | CodexRemovalFailed:
    failed = CodexRemovalFailed(
        step=CodexCompensationStep.REMOVE_MARKETPLACE,
        status="DECLARED_FAILURE",
    )
    if _operation_failure_matches(value, CodexCompensationPortOperation.REMOVE_MARKETPLACE, request):
        return failed
    if type(value) is not CodexMarketplaceRemovalProof:
        return failed
    proof = value
    try:
        if not _has_exact_model_state(proof, _REMOVAL_PROOF_STATE_FIELDS):
            return failed
        returned_manifest: object = proof.manifest
        status: object = proof.status
    except AttributeError:
        return failed
    if (
        not _manifest_is_exact(returned_manifest)
        or type(status) is not str
        or status != "REMOVED"
        or not _manifests_match(cast(CodexCompensationPortManifest, returned_manifest), request.manifest)
    ):
        return failed
    return CodexRemovalConfirmed(
        step=CodexCompensationStep.REMOVE_MARKETPLACE,
        status="CONFIRMED",
    )


def _plugin_list_observation(
    value: object,
    request: CodexCompensationPortRequest,
) -> CodexPluginListsProof:
    if _operation_failure_matches(value, CodexCompensationPortOperation.LIST_PLUGINS, request):
        return CodexPluginListsProof(
            step=CodexCompensationStep.PROVE_PLUGIN_LISTS_ABSENT,
            installed=CodexProofTruth.UNPROVED,
            available=CodexProofTruth.UNPROVED,
        )
    if not _plugin_list_is_exact(value):
        return CodexPluginListsProof(
            step=CodexCompensationStep.PROVE_PLUGIN_LISTS_ABSENT,
            installed=CodexProofTruth.MALFORMED,
            available=CodexProofTruth.MALFORMED,
        )
    plugin_list = cast(CodexPluginList, value)
    return CodexPluginListsProof(
        step=CodexCompensationStep.PROVE_PLUGIN_LISTS_ABSENT,
        installed=_plugin_collection_truth(plugin_list.installed, request.manifest),
        available=_plugin_collection_truth(plugin_list.available, request.manifest),
    )


def _marketplace_list_observation(
    value: object,
    request: CodexCompensationPortRequest,
) -> CodexMarketplaceProof:
    if _operation_failure_matches(value, CodexCompensationPortOperation.LIST_MARKETPLACES, request):
        return CodexMarketplaceProof(
            step=CodexCompensationStep.PROVE_MARKETPLACE_ABSENT,
            truth=CodexProofTruth.UNPROVED,
        )
    if not _marketplace_list_is_exact(value):
        return CodexMarketplaceProof(
            step=CodexCompensationStep.PROVE_MARKETPLACE_ABSENT,
            truth=CodexProofTruth.MALFORMED,
        )
    marketplace_list = cast(CodexMarketplaceList, value)
    mismatch = False
    for entry in marketplace_list.marketplaces:
        if entry.name != request.manifest.marketplace.value:
            continue
        source = entry.marketplaceSource
        if source is not None and source.value == request.manifest.marketplace_source.value:
            return CodexMarketplaceProof(
                step=CodexCompensationStep.PROVE_MARKETPLACE_ABSENT,
                truth=CodexProofTruth.RESIDUE,
            )
        mismatch = True
    return CodexMarketplaceProof(
        step=CodexCompensationStep.PROVE_MARKETPLACE_ABSENT,
        truth=CodexProofTruth.MISMATCH if mismatch else CodexProofTruth.PROVED_ABSENT,
    )


def _installed_path_observation(
    value: object,
    request: CodexCompensationPortRequest,
) -> CodexInstalledLocationProof:
    if _operation_failure_matches(value, CodexCompensationPortOperation.PROVE_INSTALLED_PATH_ABSENT, request):
        return CodexInstalledLocationProof(
            step=CodexCompensationStep.PROVE_INSTALLED_LOCATION_ABSENT,
            truth=CodexProofTruth.UNPROVED,
        )
    if type(value) is not CodexInstalledPathAbsenceProof:
        return CodexInstalledLocationProof(
            step=CodexCompensationStep.PROVE_INSTALLED_LOCATION_ABSENT,
            truth=CodexProofTruth.MALFORMED,
        )
    proof = value
    try:
        if not _has_exact_model_state(proof, _INSTALLED_PATH_PROOF_STATE_FIELDS):
            return CodexInstalledLocationProof(
                step=CodexCompensationStep.PROVE_INSTALLED_LOCATION_ABSENT,
                truth=CodexProofTruth.MALFORMED,
            )
        returned_manifest: object = proof.manifest
        absent: object = proof.absent
    except AttributeError:
        return CodexInstalledLocationProof(
            step=CodexCompensationStep.PROVE_INSTALLED_LOCATION_ABSENT,
            truth=CodexProofTruth.MALFORMED,
        )
    if not _manifest_is_exact(returned_manifest) or type(absent) is not bool:
        truth = CodexProofTruth.MALFORMED
    elif not _manifests_match(cast(CodexCompensationPortManifest, returned_manifest), request.manifest):
        truth = CodexProofTruth.MISMATCH
    elif absent:
        truth = CodexProofTruth.PROVED_ABSENT
    else:
        truth = CodexProofTruth.RESIDUE
    return CodexInstalledLocationProof(
        step=CodexCompensationStep.PROVE_INSTALLED_LOCATION_ABSENT,
        truth=truth,
    )


def _plugin_list_is_exact(value: object) -> bool:
    if type(value) is not CodexPluginList:
        return False
    plugin_list = value
    try:
        if not _has_exact_model_state(plugin_list, _PLUGIN_LIST_STATE_FIELDS):
            return False
        return (
            type(plugin_list.installed) is tuple
            and type(plugin_list.available) is tuple
            and all(_plugin_entry_is_exact(entry) for entry in plugin_list.installed)
            and all(_plugin_entry_is_exact(entry) for entry in plugin_list.available)
        )
    except (AttributeError, TypeError):
        return False


def _plugin_entry_is_exact(value: object) -> bool:
    if type(value) is not CodexPluginEntry:
        return False
    entry = value
    try:
        if not _has_exact_model_state(entry, _PLUGIN_ENTRY_STATE_FIELDS, ("marketplaceSource",)):
            return False
        if (
            type(entry.pluginId) is not str
            or type(entry.name) is not str
            or type(entry.marketplaceName) is not str
            or type(entry.version) is not str
            or type(entry.installed) is not bool
            or type(entry.enabled) is not bool
            or type(entry.source) is not str
            or type(entry.installPolicy) is not str
            or type(entry.authPolicy) is not str
        ):
            return False
        source: object = entry.marketplaceSource
        if source is not None and not _marketplace_source_is_exact(source):
            return False
        fields: dict[str, object] = {
            "pluginId": entry.pluginId,
            "name": entry.name,
            "marketplaceName": entry.marketplaceName,
            "version": entry.version,
            "installed": entry.installed,
            "enabled": entry.enabled,
            "source": entry.source,
            "installPolicy": entry.installPolicy,
            "authPolicy": entry.authPolicy,
        }
        if source is not None:
            fields["marketplaceSource"] = cast(CodexMarketplaceSource, source)
        CodexPluginEntry.model_validate(fields)
    except (AttributeError, TypeError, ValidationError, ValueError):
        return False
    return True


def _plugin_collection_truth(
    entries: tuple[CodexPluginEntry, ...],
    manifest: CodexCompensationPortManifest,
) -> CodexProofTruth:
    mismatch = False
    for entry in entries:
        if entry.pluginId != manifest.plugin_id.value:
            continue
        if (
            entry.name == manifest.plugin.value
            and entry.marketplaceName == manifest.marketplace.value
            and entry.version == manifest.version.value
            and entry.authPolicy == manifest.auth_policy.value
        ):
            return CodexProofTruth.RESIDUE
        mismatch = True
    return CodexProofTruth.MISMATCH if mismatch else CodexProofTruth.PROVED_ABSENT


def _marketplace_list_is_exact(value: object) -> bool:
    if type(value) is not CodexMarketplaceList:
        return False
    marketplace_list = value
    try:
        if not _has_exact_model_state(marketplace_list, _MARKETPLACE_LIST_STATE_FIELDS):
            return False
        return (
            type(marketplace_list.marketplaces) is tuple
            and all(_marketplace_entry_is_exact(entry) for entry in marketplace_list.marketplaces)
        )
    except (AttributeError, TypeError):
        return False


def _marketplace_entry_is_exact(value: object) -> bool:
    if type(value) is not CodexMarketplaceEntry:
        return False
    entry = value
    try:
        if not _has_exact_model_state(entry, _MARKETPLACE_ENTRY_STATE_FIELDS, ("marketplaceSource",)):
            return False
        if type(entry.name) is not str or type(entry.root) is not str:
            return False
        source: object = entry.marketplaceSource
        if source is not None and not _marketplace_source_is_exact(source):
            return False
        if source is None:
            CodexMarketplaceEntry(name=entry.name, root=entry.root)
        else:
            CodexMarketplaceEntry(
                name=entry.name,
                root=entry.root,
                marketplaceSource=cast(CodexMarketplaceSource, source),
            )
    except (AttributeError, TypeError, ValidationError, ValueError):
        return False
    return True


def _marketplace_source_is_exact(value: object) -> bool:
    if type(value) is not CodexMarketplaceSource:
        return False
    source = value
    try:
        if not _has_exact_model_state(source, _MARKETPLACE_SOURCE_STATE_FIELDS):
            return False
        if type(source.type) is not str or type(source.value) is not str:
            return False
        CodexMarketplaceSource(type=source.type, value=source.value)
    except (AttributeError, TypeError, ValidationError, ValueError):
        return False
    return True
