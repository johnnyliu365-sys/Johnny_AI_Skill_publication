"""Pure conversion of one exact registration receipt into a removal request."""

from __future__ import annotations

from enum import Enum
from typing import Final, Literal, TypeAlias, cast

from pydantic import BaseModel, ConfigDict, ValidationError

from .codex_compensation_port import CodexCompensationPortManifest, CodexCompensationPortRequest
from .codex_registration_contracts import (
    CodexAuthPolicy,
    CodexPluginId,
    CodexRegistrationReceipt,
)
from .contracts import ArtifactDigest, InstallRoot, InstallationId, OwnedRelativePath
from .host_contracts import CodexCliVersion, CodexMarketplaceName, CodexPluginName


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, revalidate_instances="always")


class CodexReceiptRemovalInvocation(_StrictModel):
    """The exact persisted receipt and the two identities supplied by the caller."""

    installation_id: InstallationId
    root: InstallRoot
    receipt: CodexRegistrationReceipt


class CodexReceiptRemovalBlockReason(str, Enum):
    """Finite reasons for refusing a receipt-to-request conversion."""

    INVALID_INVOCATION = "INVALID_INVOCATION"
    INVALID_RECEIPT = "INVALID_RECEIPT"
    RECEIPT_MISMATCH = "RECEIPT_MISMATCH"


class CodexReceiptRemovalReady(_StrictModel):
    """A rebuilt receipt and compensation request with no caller-owned objects."""

    status: Literal["READY"] = "READY"
    receipt: CodexRegistrationReceipt
    request: CodexCompensationPortRequest


class CodexReceiptRemovalBlocked(_StrictModel):
    """A finite metadata-only refusal before any effect boundary exists."""

    status: Literal["UNINSTALL_BLOCKED"] = "UNINSTALL_BLOCKED"
    reason: CodexReceiptRemovalBlockReason


CodexReceiptRemovalResult: TypeAlias = CodexReceiptRemovalReady | CodexReceiptRemovalBlocked


_INVOCATION_STATE_FIELDS: Final[tuple[str, ...]] = ("installation_id", "root", "receipt")
_RECEIPT_STATE_FIELDS: Final[tuple[str, ...]] = (
    "installation_id",
    "root",
    "marketplace",
    "plugin_id",
    "plugin_name",
    "version",
    "source_locator",
    "installed_locator",
    "auth_policy",
    "digest",
)
_VALUE_STATE_FIELDS: Final[tuple[str, ...]] = ("value",)


def build_codex_receipt_removal_request(value: object) -> CodexReceiptRemovalResult:
    """Admit, rebuild, bind and convert one exact receipt invocation."""

    if type(value) is not CodexReceiptRemovalInvocation:
        return _blocked(CodexReceiptRemovalBlockReason.INVALID_INVOCATION)
    invocation = value
    if not _has_exact_model_state(invocation, _INVOCATION_STATE_FIELDS):
        return _blocked(CodexReceiptRemovalBlockReason.INVALID_INVOCATION)
    invocation_state = _model_state(invocation)
    if invocation_state is None:
        return _blocked(CodexReceiptRemovalBlockReason.INVALID_INVOCATION)

    rebuilt_installation_id = _rebuild_value(invocation_state["installation_id"], InstallationId)
    rebuilt_root = _rebuild_value(invocation_state["root"], InstallRoot)
    if rebuilt_installation_id is None or rebuilt_root is None:
        return _blocked(CodexReceiptRemovalBlockReason.INVALID_INVOCATION)

    rebuilt_receipt = _rebuild_receipt(invocation_state["receipt"])
    if rebuilt_receipt is None:
        return _blocked(CodexReceiptRemovalBlockReason.INVALID_RECEIPT)

    installation_id = cast(InstallationId, rebuilt_installation_id)
    root = cast(InstallRoot, rebuilt_root)
    if (
        installation_id.value != rebuilt_receipt.installation_id.value
        or root.value != rebuilt_receipt.root.value
    ):
        return _blocked(CodexReceiptRemovalBlockReason.RECEIPT_MISMATCH)

    try:
        manifest = CodexCompensationPortManifest(
            installation_id=installation_id,
            root=root,
            marketplace=rebuilt_receipt.marketplace,
            marketplace_source=rebuilt_receipt.source_locator,
            plugin_id=rebuilt_receipt.plugin_id,
            plugin=rebuilt_receipt.plugin_name,
            version=rebuilt_receipt.version,
            installed_locator=rebuilt_receipt.installed_locator,
            auth_policy=rebuilt_receipt.auth_policy,
            digest=rebuilt_receipt.digest,
        )
        request = CodexCompensationPortRequest(manifest=manifest)
        return CodexReceiptRemovalReady(receipt=rebuilt_receipt, request=request)
    except (TypeError, ValidationError, ValueError):
        return _blocked(CodexReceiptRemovalBlockReason.INVALID_RECEIPT)


def _rebuild_receipt(value: object) -> CodexRegistrationReceipt | None:
    """Rebuild a receipt from fixed Pydantic storage without caller hooks."""

    if type(value) is not CodexRegistrationReceipt:
        return None
    receipt = value
    if not _has_exact_model_state(receipt, _RECEIPT_STATE_FIELDS):
        return None
    state = _model_state(receipt)
    if state is None:
        return None
    installation_id = _rebuild_value(state["installation_id"], InstallationId)
    root = _rebuild_value(state["root"], InstallRoot)
    marketplace = _rebuild_value(state["marketplace"], CodexMarketplaceName)
    plugin_id = _rebuild_value(state["plugin_id"], CodexPluginId)
    plugin_name = _rebuild_value(state["plugin_name"], CodexPluginName)
    version = _rebuild_value(state["version"], CodexCliVersion)
    source_locator = _rebuild_value(state["source_locator"], OwnedRelativePath)
    installed_locator = _rebuild_value(state["installed_locator"], OwnedRelativePath)
    auth_policy = _rebuild_value(state["auth_policy"], CodexAuthPolicy)
    digest = _rebuild_value(state["digest"], ArtifactDigest)
    if (
        installation_id is None
        or root is None
        or marketplace is None
        or plugin_id is None
        or plugin_name is None
        or version is None
        or source_locator is None
        or installed_locator is None
        or auth_policy is None
        or digest is None
    ):
        return None
    try:
        return CodexRegistrationReceipt(
            installation_id=cast(InstallationId, installation_id),
            root=cast(InstallRoot, root),
            marketplace=cast(CodexMarketplaceName, marketplace),
            plugin_id=cast(CodexPluginId, plugin_id),
            plugin_name=cast(CodexPluginName, plugin_name),
            version=cast(CodexCliVersion, version),
            source_locator=cast(OwnedRelativePath, source_locator),
            installed_locator=cast(OwnedRelativePath, installed_locator),
            auth_policy=cast(CodexAuthPolicy, auth_policy),
            digest=cast(ArtifactDigest, digest),
        )
    except (TypeError, ValidationError, ValueError):
        return None


def _rebuild_value(value: object, expected_type: type[BaseModel]) -> BaseModel | None:
    """Rebuild one exact value object from its fixed scalar storage."""

    if type(value) is not expected_type or not _has_exact_model_state(value, _VALUE_STATE_FIELDS):
        return None
    state = _model_state(value)
    if state is None:
        return None
    raw_value = state["value"]
    if type(raw_value) is not str:
        return None
    try:
        return expected_type(value=raw_value)
    except (TypeError, ValidationError, ValueError):
        return None


def _has_exact_model_state(value: BaseModel, expected_fields: tuple[str, ...]) -> bool:
    """Require only the declared Pydantic storage and no extra/private state."""

    state = _model_state(value)
    if state is None:
        return False
    try:
        extras: object = object.__getattribute__(value, "__pydantic_extra__")
        private: object = object.__getattribute__(value, "__pydantic_private__")
        fields_set: object = object.__getattribute__(value, "__pydantic_fields_set__")
    except AttributeError:
        return False
    if extras is not None or private is not None or type(fields_set) is not set:
        return False
    if len(state) != len(expected_fields) or len(fields_set) != len(expected_fields):
        return False
    for key in state:
        if type(key) is not str:
            return False
    for key in fields_set:
        if type(key) is not str:
            return False
    return all(expected in state and expected in fields_set for expected in expected_fields)


def _model_state(value: BaseModel) -> dict[str, object] | None:
    """Read the built-in instance dictionary without resolving model descriptors."""

    try:
        state: object = object.__getattribute__(value, "__dict__")
    except AttributeError:
        return None
    if type(state) is not dict:
        return None
    return cast(dict[str, object], state)


def _blocked(reason: CodexReceiptRemovalBlockReason) -> CodexReceiptRemovalBlocked:
    return CodexReceiptRemovalBlocked(reason=reason)
