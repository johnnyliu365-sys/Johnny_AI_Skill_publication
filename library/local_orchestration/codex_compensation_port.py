"""Closed, descriptor-free admission for a five-operation Codex compensation port."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import CodeType, FunctionType, GetSetDescriptorType, MappingProxyType, MethodType
from typing import Callable, Final, Literal, TypeAlias, cast

from pydantic import BaseModel, ConfigDict, ValidationError

from .codex_registration_contracts import CodexAuthPolicy, CodexPluginId
from .contracts import ArtifactDigest, InstallRoot, InstallationId, OwnedRelativePath
from .host_contracts import CodexCliVersion, CodexMarketplaceList, CodexMarketplaceName, CodexPluginList, CodexPluginName


class _StrictModel(BaseModel):
    """Frozen metadata-only values at the closed capability boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, revalidate_instances="always")


class CodexCompensationPortManifest(_StrictModel):
    """Exact authority that every later compensation operation must receive."""

    installation_id: InstallationId
    root: InstallRoot
    marketplace: CodexMarketplaceName
    marketplace_source: OwnedRelativePath
    plugin_id: CodexPluginId
    plugin: CodexPluginName
    version: CodexCliVersion
    installed_locator: OwnedRelativePath
    auth_policy: CodexAuthPolicy
    digest: ArtifactDigest


class CodexCompensationPortRequest(_StrictModel):
    """The single strongly typed argument for each admitted port operation."""

    manifest: CodexCompensationPortManifest


class CodexCompensationPortValueRejectReason(str, Enum):
    """The one finite reason for rejecting a non-exact compensation request."""

    INVALID_REQUEST = "INVALID_REQUEST"


class CodexCompensationPortValueRejected(_StrictModel):
    """Metadata-only rejection that never retains a caller manifest or diagnostic."""

    status: Literal["INVALID_VALUE"] = "INVALID_VALUE"
    reason: CodexCompensationPortValueRejectReason = CodexCompensationPortValueRejectReason.INVALID_REQUEST


CodexCompensationPortRequestRevalidation: TypeAlias = (
    CodexCompensationPortRequest | CodexCompensationPortValueRejected
)


_REQUEST_STATE_FIELDS: Final[tuple[str, ...]] = ("manifest",)
_MANIFEST_STATE_FIELDS: Final[tuple[str, ...]] = (
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
_VALUE_STATE_FIELDS: Final[tuple[str, ...]] = ("value",)


def revalidate_codex_compensation_port_request(value: object) -> CodexCompensationPortRequestRevalidation:
    """Rebuild only one exact, closed compensation request without caller protocols."""

    if type(value) is not CodexCompensationPortRequest:
        return _value_rejected()
    request = value
    if not _has_exact_model_state(request, _REQUEST_STATE_FIELDS):
        return _value_rejected()
    request_state = _model_state(request)
    if request_state is None:
        return _value_rejected()
    current_manifest = request_state["manifest"]
    if type(current_manifest) is not CodexCompensationPortManifest:
        return _value_rejected()
    rebuilt_manifest = _rebuild_exact_manifest(current_manifest)
    if rebuilt_manifest is None:
        return _value_rejected()
    try:
        return CodexCompensationPortRequest(manifest=rebuilt_manifest)
    except (TypeError, ValidationError, ValueError):
        return _value_rejected()


def _rebuild_exact_manifest(value: CodexCompensationPortManifest) -> CodexCompensationPortManifest | None:
    """Read fixed Pydantic storage and rebuild all closed request values by value."""

    if not _has_exact_model_state(value, _MANIFEST_STATE_FIELDS):
        return None
    state = _model_state(value)
    if state is None:
        return None
    installation_id = _rebuild_value(state["installation_id"], InstallationId)
    root = _rebuild_value(state["root"], InstallRoot)
    marketplace = _rebuild_value(state["marketplace"], CodexMarketplaceName)
    marketplace_source = _rebuild_value(state["marketplace_source"], OwnedRelativePath)
    plugin_id = _rebuild_value(state["plugin_id"], CodexPluginId)
    plugin = _rebuild_value(state["plugin"], CodexPluginName)
    version = _rebuild_value(state["version"], CodexCliVersion)
    installed_locator = _rebuild_value(state["installed_locator"], OwnedRelativePath)
    auth_policy = _rebuild_value(state["auth_policy"], CodexAuthPolicy)
    digest = _rebuild_value(state["digest"], ArtifactDigest)
    if (
        installation_id is None
        or root is None
        or marketplace is None
        or marketplace_source is None
        or plugin_id is None
        or plugin is None
        or version is None
        or installed_locator is None
        or auth_policy is None
        or digest is None
    ):
        return None
    try:
        return CodexCompensationPortManifest(
            installation_id=cast(InstallationId, installation_id),
            root=cast(InstallRoot, root),
            marketplace=cast(CodexMarketplaceName, marketplace),
            marketplace_source=cast(OwnedRelativePath, marketplace_source),
            plugin_id=cast(CodexPluginId, plugin_id),
            plugin=cast(CodexPluginName, plugin),
            version=cast(CodexCliVersion, version),
            installed_locator=cast(OwnedRelativePath, installed_locator),
            auth_policy=cast(CodexAuthPolicy, auth_policy),
            digest=cast(ArtifactDigest, digest),
        )
    except (TypeError, ValidationError, ValueError):
        return None


def _rebuild_value(value: object, expected_type: type[BaseModel]) -> BaseModel | None:
    """Admit one exact scalar model, then reconstruct it from its exact built-in string."""

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
    """Require fixed Pydantic storage without property, equality, or serialization access."""

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
    for expected in expected_fields:
        if expected not in state or expected not in fields_set:
            return False
    return True


def _model_state(value: BaseModel) -> dict[str, object] | None:
    """Read only the exact built-in Pydantic instance dictionary."""

    try:
        state: object = object.__getattribute__(value, "__dict__")
    except AttributeError:
        return None
    if type(state) is not dict:
        return None
    return cast(dict[str, object], state)


def _value_rejected() -> CodexCompensationPortValueRejected:
    return CodexCompensationPortValueRejected(
        status="INVALID_VALUE",
        reason=CodexCompensationPortValueRejectReason.INVALID_REQUEST,
    )


class CodexPluginRemovalProof(_StrictModel):
    """Typed plugin-removal result for later exact composition."""

    manifest: CodexCompensationPortManifest
    status: Literal["REMOVED"]


class CodexMarketplaceRemovalProof(_StrictModel):
    """Typed marketplace-removal result for later exact composition."""

    manifest: CodexCompensationPortManifest
    status: Literal["REMOVED"]


class CodexInstalledPathAbsenceProof(_StrictModel):
    """Typed path-absence result for later exact composition."""

    manifest: CodexCompensationPortManifest
    absent: bool


class CodexCompensationPortOperation(str, Enum):
    """The one exact admitted operation bound into a finite failure envelope."""

    REMOVE_PLUGIN = "REMOVE_PLUGIN"
    REMOVE_MARKETPLACE = "REMOVE_MARKETPLACE"
    LIST_PLUGINS = "LIST_PLUGINS"
    LIST_MARKETPLACES = "LIST_MARKETPLACES"
    PROVE_INSTALLED_PATH_ABSENT = "PROVE_INSTALLED_PATH_ABSENT"


class CodexCompensationPortFailureReason(str, Enum):
    """Finite metadata-only reasons for an admitted operation's returned failure."""

    REQUEST_INVALID = "REQUEST_INVALID"
    DEPENDENCY_BLOCKED = "DEPENDENCY_BLOCKED"
    EVIDENCE_INVALID = "EVIDENCE_INVALID"


class CodexCompensationPortOperationFailed(_StrictModel):
    """Closed manifest-bound failure value with no diagnostic or new path authority."""

    manifest: CodexCompensationPortManifest
    operation: CodexCompensationPortOperation
    status: Literal["FAILED"] = "FAILED"
    reason: CodexCompensationPortFailureReason


CodexRemovePluginOperation: TypeAlias = Callable[
    [CodexCompensationPortRequest],
    CodexPluginRemovalProof | CodexCompensationPortOperationFailed,
]
CodexRemoveMarketplaceOperation: TypeAlias = Callable[
    [CodexCompensationPortRequest],
    CodexMarketplaceRemovalProof | CodexCompensationPortOperationFailed,
]
CodexListPluginsOperation: TypeAlias = Callable[
    [CodexCompensationPortRequest],
    CodexPluginList | CodexCompensationPortOperationFailed,
]
CodexListMarketplacesOperation: TypeAlias = Callable[
    [CodexCompensationPortRequest],
    CodexMarketplaceList | CodexCompensationPortOperationFailed,
]
CodexProveInstalledPathAbsentOperation: TypeAlias = Callable[
    [CodexCompensationPortRequest],
    CodexInstalledPathAbsenceProof | CodexCompensationPortOperationFailed,
]


class CodexCompensationPortRejectReason(str, Enum):
    """Finite internal reasons; their public status remains uniformly INVALID_PORT."""

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


class CodexCompensationPortRejected(_StrictModel):
    """Metadata-only result for every failed capability admission."""

    status: Literal["INVALID_PORT"]
    reason: CodexCompensationPortRejectReason


class CodexCompensationPortAdmitted(_StrictModel):
    """Safe serialization view; it never exposes raw adapter functions."""

    status: Literal["ADMITTED"]
    operation_count: Literal[5]


class _CapabilityToken:
    """Private constructor authority for a capability created by this factory only."""


_CAPABILITY_TOKEN: Final[_CapabilityToken] = _CapabilityToken()
_MISSING_OPERATION: Final[object] = object()
_FUNCTION_VARARGS_FLAG: Final[int] = 0x04
_FUNCTION_VARKWARGS_FLAG: Final[int] = 0x08
_TYPE_MRO_GETSET: Final[GetSetDescriptorType] = cast(GetSetDescriptorType, type.__dict__["__mro__"])
_TYPE_DICTIONARY_GETSET: Final[GetSetDescriptorType] = cast(GetSetDescriptorType, type.__dict__["__dict__"])


@dataclass(frozen=True, slots=True, init=False)
class CodexCompensationPortCapability:
    """Five explicitly bound operations admitted without resolving adapter members."""

    status: Literal["ADMITTED"]
    remove_plugin: CodexRemovePluginOperation
    remove_marketplace: CodexRemoveMarketplaceOperation
    list_plugins: CodexListPluginsOperation
    list_marketplaces: CodexListMarketplacesOperation
    prove_installed_path_absent: CodexProveInstalledPathAbsentOperation

    def __init__(
        self,
        token: _CapabilityToken,
        remove_plugin: CodexRemovePluginOperation,
        remove_marketplace: CodexRemoveMarketplaceOperation,
        list_plugins: CodexListPluginsOperation,
        list_marketplaces: CodexListMarketplacesOperation,
        prove_installed_path_absent: CodexProveInstalledPathAbsentOperation,
    ) -> None:
        if token is not _CAPABILITY_TOKEN:
            raise TypeError("capability construction requires factory authority")
        object.__setattr__(self, "status", "ADMITTED")
        object.__setattr__(self, "remove_plugin", remove_plugin)
        object.__setattr__(self, "remove_marketplace", remove_marketplace)
        object.__setattr__(self, "list_plugins", list_plugins)
        object.__setattr__(self, "list_marketplaces", list_marketplaces)
        object.__setattr__(self, "prove_installed_path_absent", prove_installed_path_absent)

    def metadata(self) -> CodexCompensationPortAdmitted:
        """Return only public admission metadata, never bound callable internals."""

        return CodexCompensationPortAdmitted(status="ADMITTED", operation_count=5)


CodexCompensationPortAdmission: TypeAlias = CodexCompensationPortCapability | CodexCompensationPortRejected


class _OperationName(str, Enum):
    REMOVE_PLUGIN = "remove_plugin"
    REMOVE_MARKETPLACE = "remove_marketplace"
    LIST_PLUGINS = "list_plugins"
    LIST_MARKETPLACES = "list_marketplaces"
    PROVE_INSTALLED_PATH_ABSENT = "prove_installed_path_absent"


def admit_codex_compensation_port(candidate: object) -> CodexCompensationPortAdmission:
    """Admit only exact plain class methods without dynamic candidate lookup or execution."""

    if candidate is None:
        return _rejected(CodexCompensationPortRejectReason.INVALID_CANDIDATE)
    candidate_class = type(candidate)
    if candidate_class is str or candidate_class is tuple or candidate_class is list or candidate_class is dict:
        return _rejected(CodexCompensationPortRejectReason.INVALID_CANDIDATE)
    remove_plugin = _admit_operation(candidate_class, _OperationName.REMOVE_PLUGIN)
    if isinstance(remove_plugin, CodexCompensationPortRejected):
        return remove_plugin
    remove_marketplace = _admit_operation(candidate_class, _OperationName.REMOVE_MARKETPLACE)
    if isinstance(remove_marketplace, CodexCompensationPortRejected):
        return remove_marketplace
    list_plugins = _admit_operation(candidate_class, _OperationName.LIST_PLUGINS)
    if isinstance(list_plugins, CodexCompensationPortRejected):
        return list_plugins
    list_marketplaces = _admit_operation(candidate_class, _OperationName.LIST_MARKETPLACES)
    if isinstance(list_marketplaces, CodexCompensationPortRejected):
        return list_marketplaces
    prove_absent = _admit_operation(candidate_class, _OperationName.PROVE_INSTALLED_PATH_ABSENT)
    if isinstance(prove_absent, CodexCompensationPortRejected):
        return prove_absent
    return CodexCompensationPortCapability(
        _CAPABILITY_TOKEN,
        cast(CodexRemovePluginOperation, MethodType(remove_plugin, candidate)),
        cast(CodexRemoveMarketplaceOperation, MethodType(remove_marketplace, candidate)),
        cast(CodexListPluginsOperation, MethodType(list_plugins, candidate)),
        cast(CodexListMarketplacesOperation, MethodType(list_marketplaces, candidate)),
        cast(CodexProveInstalledPathAbsentOperation, MethodType(prove_absent, candidate)),
    )


def _admit_operation(
    candidate_class: type[object],
    operation: _OperationName,
) -> FunctionType | CodexCompensationPortRejected:
    """Locate exactly one raw class-dictionary function without descriptor resolution."""

    raw_member = _raw_member_from_mro(candidate_class, operation)
    if raw_member is _MISSING_OPERATION:
        return _rejected(CodexCompensationPortRejectReason.MISSING_OPERATION)
    if type(raw_member) is property:
        return _rejected(CodexCompensationPortRejectReason.PROPERTY_OPERATION)
    if type(raw_member) is staticmethod:
        return _rejected(CodexCompensationPortRejectReason.STATIC_METHOD_OPERATION)
    if type(raw_member) is classmethod:
        return _rejected(CodexCompensationPortRejectReason.CLASS_METHOD_OPERATION)
    if type(raw_member) is not FunctionType:
        return _rejected(CodexCompensationPortRejectReason.NON_PLAIN_FUNCTION)
    plain_function = raw_member
    shape_reason = _plain_function_shape_reason(plain_function)
    if shape_reason is not None:
        return _rejected(shape_reason)
    return plain_function


def _raw_member_from_mro(candidate_class: type[object], operation: _OperationName) -> object:
    """Read raw type slots without resolving caller class or metaclass descriptors."""

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


def _plain_function_shape_reason(function: FunctionType) -> CodexCompensationPortRejectReason | None:
    """Use only immutable code/default metadata, never signature or wrapper metadata."""

    code_value = object.__getattribute__(function, "__code__")
    defaults_value = object.__getattribute__(function, "__defaults__")
    keyword_defaults_value = object.__getattribute__(function, "__kwdefaults__")
    if type(code_value) is not CodeType:
        return CodexCompensationPortRejectReason.NON_PLAIN_FUNCTION
    code = code_value
    if defaults_value is not None or keyword_defaults_value is not None:
        return CodexCompensationPortRejectReason.DEFAULTED_ARGUMENTS
    if code.co_flags & (_FUNCTION_VARARGS_FLAG | _FUNCTION_VARKWARGS_FLAG):
        return CodexCompensationPortRejectReason.VARIADIC_ARGUMENTS
    if code.co_kwonlyargcount != 0:
        return CodexCompensationPortRejectReason.REQUIRED_KEYWORD_ARGUMENTS
    if code.co_argcount < 2:
        return CodexCompensationPortRejectReason.ZERO_REQUEST_ARGUMENTS
    if code.co_argcount > 2:
        return CodexCompensationPortRejectReason.TWO_REQUEST_ARGUMENTS
    return None


def _rejected(reason: CodexCompensationPortRejectReason) -> CodexCompensationPortRejected:
    return CodexCompensationPortRejected(status="INVALID_PORT", reason=reason)
