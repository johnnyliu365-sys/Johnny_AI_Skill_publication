from __future__ import annotations

from enum import Enum
import ntpath
from typing import ClassVar, Literal, Protocol, Self, runtime_checkable

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from .contracts import CANONICAL_INSTALL_ROOT, InstallRoot, InstallationId, OwnedRelativePath


CANONICAL_HOST_REGISTRATION_KEY = "JohnnyAIWorkflow/AgentHost"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _valid_installation(installation_id: InstallationId) -> None:
    value = installation_id.value
    prefix = "installation-"
    suffix = value[len(prefix) :] if value.startswith(prefix) else ""
    if len(suffix) != 16 or any(character not in "0123456789abcdef" for character in suffix):
        raise ValueError("installation id must be opaque lowercase metadata")


class AgentHost(str, Enum):
    CODEX = "CODEX"
    CLAUDE = "CLAUDE"
    RECORDED = "RECORDED"


class HostRegistrationKey(_StrictModel):
    value: str

    @field_validator("value")
    @classmethod
    def exact_key(cls, value: str) -> str:
        if value != CANONICAL_HOST_REGISTRATION_KEY:
            raise ValueError("registration key must match the canonical key exactly")
        return value


class HostEvidenceId(_StrictModel):
    value: str

    @field_validator("value")
    @classmethod
    def opaque_id(cls, value: str) -> str:
        prefix = "evidence-"
        suffix = value[len(prefix) :] if value.startswith(prefix) else ""
        if len(suffix) != 16 or any(character not in "0123456789abcdef" for character in suffix):
            raise ValueError("host evidence id must be opaque lowercase metadata")
        return value


class HostCommandStatus(str, Enum):
    DETECTED = "DETECTED"
    REGISTERED = "REGISTERED"
    VERIFIED = "VERIFIED"
    ABSENT = "ABSENT"


class HostFailureCode(str, Enum):
    EXECUTABLE_UNAVAILABLE = "EXECUTABLE_UNAVAILABLE"
    ACCESS_DENIED = "ACCESS_DENIED"
    REGISTER_FAILED = "REGISTER_FAILED"
    VERIFY_FAILED = "VERIFY_FAILED"
    REMOVAL_PROOF_FAILED = "REMOVAL_PROOF_FAILED"
    FOREIGN_REGISTRATION = "FOREIGN_REGISTRATION"


class HostBlockReason(str, Enum):
    UNVERIFIED_HOST = "UNVERIFIED_HOST"
    EXECUTABLE_UNAVAILABLE = "EXECUTABLE_UNAVAILABLE"
    ACCESS_DENIED = "ACCESS_DENIED"
    REGISTER_FAILED = "REGISTER_FAILED"
    VERIFY_FAILED = "VERIFY_FAILED"
    REMOVAL_PROOF_FAILED = "REMOVAL_PROOF_FAILED"
    FOREIGN_REGISTRATION = "FOREIGN_REGISTRATION"
    COMMAND_RESULT_MISMATCH = "COMMAND_RESULT_MISMATCH"
    RECEIPT_MISMATCH = "RECEIPT_MISMATCH"
    REMOVAL_PROOF_MISMATCH = "REMOVAL_PROOF_MISMATCH"


class HostPortError(Exception):
    def __init__(self, code: HostFailureCode) -> None:
        super().__init__(code.value)
        self.code = code


class HostCapabilityRequest(_StrictModel):
    installation_id: InstallationId
    host: AgentHost
    registration_key: HostRegistrationKey

    @model_validator(mode="after")
    def recorded_only(self) -> Self:
        _valid_installation(self.installation_id)
        if self.host is not AgentHost.RECORDED:
            raise ValueError("recorded verification cannot identify a public host")
        return self


class HostCommandResult(_StrictModel):
    installation_id: InstallationId
    host: AgentHost
    registration_key: HostRegistrationKey
    status: HostCommandStatus
    evidence_id: HostEvidenceId

    @model_validator(mode="after")
    def opaque_installation(self) -> Self:
        _valid_installation(self.installation_id)
        return self


class AgentHostReceipt(_StrictModel):
    installation_id: InstallationId
    host: AgentHost
    registration_key: HostRegistrationKey
    evidence_id: HostEvidenceId

    @model_validator(mode="after")
    def opaque_installation(self) -> Self:
        _valid_installation(self.installation_id)
        return self


class AgentHostRemovalProof(_StrictModel):
    installation_id: InstallationId
    host: AgentHost
    registration_key: HostRegistrationKey
    evidence_id: HostEvidenceId

    @model_validator(mode="after")
    def opaque_installation(self) -> Self:
        _valid_installation(self.installation_id)
        return self


class HostRemovalRequest(_StrictModel):
    installation_id: InstallationId
    host: AgentHost
    registration_key: HostRegistrationKey
    receipt: AgentHostReceipt

    @model_validator(mode="after")
    def exact_receipt(self) -> Self:
        _valid_installation(self.installation_id)
        if self.host is not AgentHost.RECORDED:
            raise ValueError("only a recorded registration can use the recorded lifecycle")
        if (
            self.installation_id != self.receipt.installation_id
            or self.host != self.receipt.host
            or self.registration_key != self.receipt.registration_key
        ):
            raise ValueError("removal request must bind the exact receipt")
        return self

    @classmethod
    def from_receipt(cls, receipt: AgentHostReceipt) -> HostRemovalRequest:
        return cls(
            installation_id=receipt.installation_id,
            host=receipt.host,
            registration_key=receipt.registration_key,
            receipt=receipt,
        )


class HostCapabilitySupported(_StrictModel):
    status: Literal["SUPPORTED"] = "SUPPORTED"
    host: AgentHost
    receipt: AgentHostReceipt
    removal_proof: AgentHostRemovalProof

    @model_validator(mode="after")
    def exact_proof(self) -> Self:
        if self.host is not AgentHost.RECORDED or self.receipt.host != self.host or (
            self.receipt.installation_id != self.removal_proof.installation_id
            or self.receipt.host != self.removal_proof.host
            or self.receipt.registration_key != self.removal_proof.registration_key
        ):
            raise ValueError("support requires exact recorded removal proof")
        return self


class HostCapabilityUnverified(_StrictModel):
    status: Literal["UNVERIFIED"] = "UNVERIFIED"
    host: AgentHost

    @model_validator(mode="after")
    def public_only(self) -> Self:
        if self.host not in (AgentHost.CODEX, AgentHost.CLAUDE):
            raise ValueError("unverified report is reserved for public hosts")
        return self


class HostCapabilityBlocked(_StrictModel):
    status: Literal["BLOCKED"] = "BLOCKED"
    host: AgentHost
    reason: HostBlockReason


HostCapabilityReport = HostCapabilitySupported | HostCapabilityUnverified | HostCapabilityBlocked


class HostRemovalSucceeded(_StrictModel):
    status: Literal["REMOVED"] = "REMOVED"
    proof: AgentHostRemovalProof


class HostRemovalBlocked(_StrictModel):
    status: Literal["BLOCKED"] = "BLOCKED"
    reason: HostBlockReason


HostRemovalResult = HostRemovalSucceeded | HostRemovalBlocked


def _codex_text(value: str, label: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{label} must be nonblank")
    return value


class _CodexValue(_StrictModel):
    value: str
    @field_validator("value")
    @classmethod
    def valid(cls, value: str) -> str: return _codex_text(value, cls.__name__)


class CodexCliVersion(_CodexValue): pass
class CodexMarketplaceName(_CodexValue): pass
class CodexPluginName(_CodexValue): pass


class CodexMarketplaceSource(_StrictModel):
    type: str
    value: str
    _valid = field_validator("type", "value")(classmethod(lambda cls, value: _codex_text(value, "marketplace source field")))


def _present_source(fields: set[str], source: CodexMarketplaceSource | None) -> None:
    if "marketplaceSource" in fields and source is None: raise ValueError("marketplace source cannot be null when present")


def _windows_absolute(value: str) -> bool: return bool(ntpath.splitdrive(value)[0]) and ntpath.isabs(value)


class CodexCommandResponse(_StrictModel):
    exit_code: int
    stdout: str
    stderr: str


class CodexMarketplaceEntry(_StrictModel):
    name: str
    root: str
    marketplaceSource: CodexMarketplaceSource | None = None
    _valid = field_validator("name", "root")(classmethod(lambda cls, value: _codex_text(value, "marketplace field")))
    @model_validator(mode="after")
    def present_source(self) -> Self:
        _present_source(self.model_fields_set, self.marketplaceSource); return self


class CodexMarketplaceList(_StrictModel):
    marketplaces: tuple[CodexMarketplaceEntry, ...]
    @field_validator("marketplaces", mode="before")
    @classmethod
    def tuple_value(cls, value: object) -> tuple[object, ...] | object: return tuple(value) if isinstance(value, list) else value


class CodexPluginEntry(_StrictModel):
    pluginId: str
    name: str
    marketplaceName: str
    version: str
    installed: bool
    enabled: bool
    source: str
    installPolicy: str
    authPolicy: str
    marketplaceSource: CodexMarketplaceSource | None = None
    _valid = field_validator("pluginId", "name", "marketplaceName", "version", "source", "installPolicy", "authPolicy")(classmethod(lambda cls, value: _codex_text(value, "plugin field")))
    @model_validator(mode="after")
    def present_source(self) -> Self:
        _present_source(self.model_fields_set, self.marketplaceSource); return self


class CodexPluginList(_StrictModel):
    installed: tuple[CodexPluginEntry, ...]
    available: tuple[CodexPluginEntry, ...]
    @field_validator("installed", "available", mode="before")
    @classmethod
    def tuple_value(cls, value: object) -> tuple[object, ...] | object: return tuple(value) if isinstance(value, list) else value


class CodexPreflightRequest(_StrictModel):
    installation_id: InstallationId
    root: "InstallRoot"
    marketplace: CodexMarketplaceName
    plugin: CodexPluginName
    marketplace_source: "OwnedRelativePath"
    @model_validator(mode="after")
    def owned_source(self) -> Self:
        if self.marketplace_source.value != f"marketplaces/{self.marketplace.value}" or self.marketplace_source.value != self.marketplace_source.value.casefold(): raise ValueError("source is not canonical")
        return self


class CodexSourceProof(_StrictModel):
    installation_id: InstallationId
    root: "InstallRoot"
    locator: "OwnedRelativePath"
    absolute_path: str
    @model_validator(mode="after")
    def exact_locator(self) -> Self:
        root = ntpath.expandvars(CANONICAL_INSTALL_ROOT)
        if not _windows_absolute(root) or not _windows_absolute(self.absolute_path) or self.absolute_path != root + "\\" + self.locator.value.replace("/", "\\"):
            raise ValueError("source proof is not an owned absolute locator")
        return self


@runtime_checkable
class CodexCommandPort(Protocol):
    def execute(self, arguments: tuple[str, ...], timeout_seconds: float) -> CodexCommandResponse: ...


@runtime_checkable
class CodexFilesystemPort(Protocol):
    def resolve_source(self, request: CodexPreflightRequest) -> CodexSourceProof: ...


class CodexBlockReason(str, Enum):
    INVALID_INPUT = "INVALID_INPUT"
    INVALID_PORT = "INVALID_PORT"
    TIMEOUT = "TIMEOUT"
    EXECUTABLE_UNAVAILABLE = "EXECUTABLE_UNAVAILABLE"
    ACCESS_DENIED = "ACCESS_DENIED"
    COMMAND_FAILED = "COMMAND_FAILED"
    FILESYSTEM_FAILED = "FILESYSTEM_FAILED"
    MALFORMED_OUTPUT = "MALFORMED_OUTPUT"
    INVALID_ENCODING = "INVALID_ENCODING"
    UNSUPPORTED_CLI = "UNSUPPORTED_CLI"
    SOURCE_MISMATCH = "SOURCE_MISMATCH"
    COLLISION = "COLLISION"


class CodexPreflightEligible(_StrictModel):
    status: Literal["ELIGIBLE"] = "ELIGIBLE"
    version: CodexCliVersion


class CodexBlocked(_StrictModel):
    status: Literal["INSTALL_BLOCKED"] = "INSTALL_BLOCKED"
    reason: CodexBlockReason


CodexPreflightResult = CodexPreflightEligible | CodexBlocked
