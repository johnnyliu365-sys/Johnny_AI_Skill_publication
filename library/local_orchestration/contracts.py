"""Strongly typed ownership contracts for the local fake installer lifecycle."""

from __future__ import annotations

from enum import Enum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


CANONICAL_INSTALL_ROOT = r"%LOCALAPPDATA%\JohnnyAIWorkflow"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _require_nonblank(value: str, label: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{label} must be nonblank and unpadded")
    return value


class InstallationId(_StrictModel):
    value: str

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: str) -> str:
        return _require_nonblank(value, "installation id")


class InstallRoot(_StrictModel):
    value: str

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: str) -> str:
        if value != CANONICAL_INSTALL_ROOT:
            raise ValueError("install root must match the canonical root exactly")
        return value


class OwnedRelativePath(_StrictModel):
    value: str

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: str) -> str:
        value = _require_nonblank(value, "owned relative path")
        folded = value.casefold()
        parts = value.split("/")
        if (
            value.startswith(("/", "\\"))
            or "\\" in value
            or ":" in value
            or "%2f" in folded
            or "%5c" in folded
            or any(part in ("", ".", "..") for part in parts)
        ):
            raise ValueError("owned path must be canonical and relative")
        return value

    def parts(self) -> tuple[str, ...]:
        return tuple(self.value.split("/"))


class ArtifactDigest(_StrictModel):
    value: str

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("artifact digest must be lowercase sha256")
        return value


class HostId(str, Enum):
    LOCAL_FAKE = "local-fake"


class ManifestEntry(_StrictModel):
    path: OwnedRelativePath
    digest: ArtifactDigest


class OwnedManifest(_StrictModel):
    entries: tuple[ManifestEntry, ...]

    @field_validator("entries")
    @classmethod
    def validate_entries(cls, entries: tuple[ManifestEntry, ...]) -> tuple[ManifestEntry, ...]:
        if not entries:
            raise ValueError("manifest must contain at least one entry")
        paths = tuple(entry.path.value for entry in entries)
        if len(paths) != len(set(paths)):
            raise ValueError("manifest paths must be unique")
        return entries


class HostRegistrationReceipt(_StrictModel):
    installation_id: InstallationId
    host_id: HostId
    registration_ref: str

    @field_validator("registration_ref")
    @classmethod
    def validate_registration_ref(cls, value: str) -> str:
        return _require_nonblank(value, "registration reference")


class OwnedInstallLedger(_StrictModel):
    installation_id: InstallationId
    root: InstallRoot
    manifest: OwnedManifest
    host_receipt: HostRegistrationReceipt

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        if self.host_receipt.installation_id != self.installation_id:
            raise ValueError("host receipt must bind the ledger installation")
        return self


class InstallRequest(_StrictModel):
    installation_id: InstallationId
    root: InstallRoot
    manifest: OwnedManifest
    host_id: HostId


class UninstallRequest(_StrictModel):
    installation_id: InstallationId
    root: InstallRoot


class InstallStatus(str, Enum):
    INSTALLED = "INSTALLED"
    INSTALL_BLOCKED = "INSTALL_BLOCKED"


class UninstallStatus(str, Enum):
    REMOVED = "REMOVED"
    NOT_INSTALLED = "NOT_INSTALLED"
    UNINSTALL_BLOCKED = "UNINSTALL_BLOCKED"


class BlockReason(str, Enum):
    EXISTING_INSTALLATION = "EXISTING_INSTALLATION"
    FOREIGN_INSTALLATION = "FOREIGN_INSTALLATION"
    INVALID_LEDGER = "INVALID_LEDGER"
    LEDGER_MISSING_WITH_EFFECTS = "LEDGER_MISSING_WITH_EFFECTS"
    MANIFEST_MISMATCH = "MANIFEST_MISMATCH"
    FOREIGN_HOST_RECEIPT = "FOREIGN_HOST_RECEIPT"
    FILESYSTEM_STAGE_FAILED = "FILESYSTEM_STAGE_FAILED"
    HOST_REGISTER_FAILED = "HOST_REGISTER_FAILED"
    LEDGER_SAVE_FAILED = "LEDGER_SAVE_FAILED"
    HOST_REMOVE_FAILED = "HOST_REMOVE_FAILED"


class InstallSucceeded(_StrictModel):
    status: Literal[InstallStatus.INSTALLED] = InstallStatus.INSTALLED
    ledger: OwnedInstallLedger
    host_receipt: HostRegistrationReceipt


class InstallBlocked(_StrictModel):
    status: Literal[InstallStatus.INSTALL_BLOCKED] = InstallStatus.INSTALL_BLOCKED
    reason: BlockReason


InstallResult = InstallSucceeded | InstallBlocked


class UninstallRemoved(_StrictModel):
    status: Literal[UninstallStatus.REMOVED] = UninstallStatus.REMOVED


class UninstallNotInstalled(_StrictModel):
    status: Literal[UninstallStatus.NOT_INSTALLED] = UninstallStatus.NOT_INSTALLED


class UninstallBlocked(_StrictModel):
    status: Literal[UninstallStatus.UNINSTALL_BLOCKED] = UninstallStatus.UNINSTALL_BLOCKED
    reason: BlockReason


UninstallResult = UninstallRemoved | UninstallNotInstalled | UninstallBlocked
