"""Injected effect boundaries for the owned install lifecycle."""

from __future__ import annotations

from enum import Enum
from typing import Protocol

from .contracts import (
    HostId,
    HostRegistrationReceipt,
    InstallationId,
    OwnedInstallLedger,
    OwnedManifest,
)


class LifecycleFailureCode(str, Enum):
    FILESYSTEM_STAGE = "FILESYSTEM_STAGE"
    HOST_REGISTER = "HOST_REGISTER"
    LEDGER_SAVE = "LEDGER_SAVE"
    HOST_REMOVE = "HOST_REMOVE"


class LifecyclePortError(RuntimeError):
    def __init__(self, code: LifecycleFailureCode) -> None:
        super().__init__(code.value)
        self.code = code


class LedgerAbsent:
    """Typed absence result; ledger reads never use null."""

    __slots__ = ()


LedgerRead = OwnedInstallLedger | LedgerAbsent


class FilesystemStageResult(str, Enum):
    STAGED = "STAGED"


class FilesystemRemovalResult(str, Enum):
    REMOVED = "REMOVED"


class LedgerWriteResult(str, Enum):
    SAVED = "SAVED"
    REMOVED = "REMOVED"


class HostRemovalResult(str, Enum):
    REMOVED = "REMOVED"


class ProcessStopResult(str, Enum):
    STOPPED_OR_ABSENT = "STOPPED_OR_ABSENT"


class OwnedFilesystemPort(Protocol):
    def stage(self, installation_id: InstallationId, manifest: OwnedManifest) -> FilesystemStageResult: ...

    def manifest_matches(self, installation_id: InstallationId, manifest: OwnedManifest) -> bool: ...

    def remove_manifest(self, installation_id: InstallationId, manifest: OwnedManifest) -> FilesystemRemovalResult: ...

    def has_owned_effects(self, installation_id: InstallationId) -> bool: ...


class InstallLedgerPort(Protocol):
    def read(self) -> LedgerRead: ...

    def save(self, ledger: OwnedInstallLedger) -> LedgerWriteResult: ...

    def remove(self, installation_id: InstallationId) -> LedgerWriteResult: ...


class HostLifecyclePort(Protocol):
    def register(self, installation_id: InstallationId, host_id: HostId) -> HostRegistrationReceipt: ...

    def matches(self, receipt: HostRegistrationReceipt) -> bool: ...

    def remove(self, receipt: HostRegistrationReceipt) -> HostRemovalResult: ...

    def has_registration(self, installation_id: InstallationId) -> bool: ...


class ProcessLifecyclePort(Protocol):
    def stop(self, installation_id: InstallationId) -> ProcessStopResult: ...
