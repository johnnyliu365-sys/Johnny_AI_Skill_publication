"""One finite synchronous application service for owned install and removal."""

from __future__ import annotations

from pydantic import ValidationError

from .contracts import (
    BlockReason,
    InstallBlocked,
    InstallRequest,
    InstallResult,
    InstallSucceeded,
    OwnedInstallLedger,
    OwnedManifest,
    UninstallBlocked,
    UninstallNotInstalled,
    UninstallRemoved,
    UninstallRequest,
    UninstallResult,
)
from .ports import (
    HostLifecyclePort,
    InstallLedgerPort,
    LedgerAbsent,
    LifecycleFailureCode,
    LifecyclePortError,
    OwnedFilesystemPort,
    ProcessLifecyclePort,
)


class OwnedInstallLifecycle:
    """Coordinate only receipt-bound fake effects behind injected ports."""

    def __init__(
        self,
        filesystem: OwnedFilesystemPort,
        ledger: InstallLedgerPort,
        host: HostLifecyclePort,
        process: ProcessLifecyclePort,
    ) -> None:
        self._filesystem = filesystem
        self._ledger = ledger
        self._host = host
        self._process = process

    def install(self, request: InstallRequest) -> InstallResult:
        existing = self._ledger.read()
        if not isinstance(existing, LedgerAbsent):
            reason = (
                BlockReason.EXISTING_INSTALLATION
                if existing.installation_id == request.installation_id
                else BlockReason.FOREIGN_INSTALLATION
            )
            return InstallBlocked(reason=reason)

        try:
            self._filesystem.stage(request.installation_id, request.manifest)
        except LifecyclePortError as error:
            if error.code is LifecycleFailureCode.FILESYSTEM_STAGE:
                return InstallBlocked(reason=BlockReason.FILESYSTEM_STAGE_FAILED)
            raise

        try:
            receipt = self._host.register(request.installation_id, request.host_id)
        except LifecyclePortError as error:
            self._filesystem.remove_manifest(request.installation_id, request.manifest)
            if error.code is LifecycleFailureCode.HOST_REGISTER:
                return InstallBlocked(reason=BlockReason.HOST_REGISTER_FAILED)
            raise

        owned_ledger = OwnedInstallLedger(
            installation_id=request.installation_id,
            root=request.root,
            manifest=request.manifest,
            host_receipt=receipt,
        )
        try:
            self._ledger.save(owned_ledger)
        except LifecyclePortError as error:
            self._rollback_install(request.manifest, owned_ledger)
            if error.code is LifecycleFailureCode.LEDGER_SAVE:
                return InstallBlocked(reason=BlockReason.LEDGER_SAVE_FAILED)
            raise

        if self._ledger.read() != owned_ledger:
            self._rollback_install(request.manifest, owned_ledger)
            return InstallBlocked(reason=BlockReason.LEDGER_SAVE_FAILED)
        return InstallSucceeded(ledger=owned_ledger, host_receipt=receipt)

    def uninstall(self, request: UninstallRequest) -> UninstallResult:
        persisted = self._ledger.read()
        if isinstance(persisted, LedgerAbsent):
            if self._filesystem.has_owned_effects(request.installation_id) or self._host.has_registration(
                request.installation_id
            ):
                return UninstallBlocked(reason=BlockReason.LEDGER_MISSING_WITH_EFFECTS)
            return UninstallNotInstalled()

        try:
            verified = OwnedInstallLedger.model_validate_json(persisted.model_dump_json())
        except ValidationError:
            return UninstallBlocked(reason=BlockReason.INVALID_LEDGER)
        if verified.installation_id != request.installation_id or verified.root != request.root:
            return UninstallBlocked(reason=BlockReason.FOREIGN_INSTALLATION)
        if not self._filesystem.manifest_matches(verified.installation_id, verified.manifest):
            return UninstallBlocked(reason=BlockReason.MANIFEST_MISMATCH)
        if not self._host.matches(verified.host_receipt):
            return UninstallBlocked(reason=BlockReason.FOREIGN_HOST_RECEIPT)

        self._process.stop(verified.installation_id)
        try:
            self._host.remove(verified.host_receipt)
        except LifecyclePortError as error:
            if error.code is LifecycleFailureCode.HOST_REMOVE:
                return UninstallBlocked(reason=BlockReason.HOST_REMOVE_FAILED)
            raise
        self._filesystem.remove_manifest(verified.installation_id, verified.manifest)
        self._ledger.remove(verified.installation_id)
        return UninstallRemoved()

    def _rollback_install(self, manifest: OwnedManifest, ledger: OwnedInstallLedger) -> None:
        self._host.remove(ledger.host_receipt)
        self._filesystem.remove_manifest(ledger.installation_id, manifest)
        current = self._ledger.read()
        if not isinstance(current, LedgerAbsent) and current.installation_id == ledger.installation_id:
            self._ledger.remove(ledger.installation_id)
