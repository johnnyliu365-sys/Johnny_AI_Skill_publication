"""Temporary-directory and in-memory fakes for Ticket 01 only."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path

from .contracts import (
    ArtifactDigest,
    HostId,
    HostRegistrationReceipt,
    InstallationId,
    OwnedInstallLedger,
    OwnedManifest,
    OwnedRelativePath,
)
from .ports import (
    FilesystemRemovalResult,
    FilesystemStageResult,
    HostRemovalResult,
    LedgerAbsent,
    LedgerRead,
    LedgerWriteResult,
    LifecycleFailureCode,
    LifecyclePortError,
    ProcessStopResult,
)


class FakeOwnedFilesystem:
    def __init__(self, sandbox: Path, payloads: Mapping[OwnedRelativePath, bytes]) -> None:
        self._root = sandbox / "owned-root"
        self._payloads = {path.value: content for path, content in payloads.items()}
        self._owned: dict[InstallationId, set[str]] = {}
        self._fail_stage = False
        self.effect_calls = 0

    def fail_next_stage(self) -> None:
        self._fail_stage = True

    def stage(self, installation_id: InstallationId, manifest: OwnedManifest) -> FilesystemStageResult:
        self.effect_calls += 1
        if self._fail_stage:
            self._fail_stage = False
            raise LifecyclePortError(LifecycleFailureCode.FILESYSTEM_STAGE)
        contents: list[tuple[OwnedRelativePath, bytes]] = []
        for entry in manifest.entries:
            content = self._payloads[entry.path.value]
            if digest_bytes(content) != entry.digest:
                raise ValueError("configured payload does not match its manifest digest")
            contents.append((entry.path, content))
        for path, content in contents:
            target = self._path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            self._owned.setdefault(installation_id, set()).add(path.value)
        return FilesystemStageResult.STAGED

    def manifest_matches(self, installation_id: InstallationId, manifest: OwnedManifest) -> bool:
        expected = self._owned.get(installation_id, set())
        for entry in manifest.entries:
            target = self._path(entry.path)
            if entry.path.value not in expected or not target.is_file():
                return False
            if digest_bytes(target.read_bytes()) != entry.digest:
                return False
        return True

    def remove_manifest(
        self, installation_id: InstallationId, manifest: OwnedManifest
    ) -> FilesystemRemovalResult:
        self.effect_calls += 1
        owned = self._owned.get(installation_id, set())
        for entry in manifest.entries:
            if entry.path.value not in owned:
                continue
            target = self._path(entry.path)
            if target.is_file():
                target.unlink()
            owned.discard(entry.path.value)
            self._prune_empty_parents(target.parent)
        return FilesystemRemovalResult.REMOVED

    def has_owned_effects(self, installation_id: InstallationId) -> bool:
        return any(self._path(OwnedRelativePath(value=value)).exists() for value in self._owned.get(installation_id, set()))

    def write_unowned(self, path: OwnedRelativePath, content: bytes) -> Path:
        target = self._path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return target

    def read(self, path: OwnedRelativePath) -> bytes:
        return self._path(path).read_bytes()

    def _path(self, path: OwnedRelativePath) -> Path:
        return self._root.joinpath(*path.parts())

    def _prune_empty_parents(self, directory: Path) -> None:
        while directory != self._root and directory.exists():
            try:
                directory.rmdir()
            except OSError:
                return
            directory = directory.parent


class FakeInstallLedger:
    def __init__(self) -> None:
        self._ledger: LedgerRead = LedgerAbsent()
        self._fail_save = False
        self.effect_calls = 0

    def fail_next_save(self) -> None:
        self._fail_save = True

    def read(self) -> LedgerRead:
        return self._ledger

    def save(self, ledger: OwnedInstallLedger) -> LedgerWriteResult:
        self.effect_calls += 1
        if self._fail_save:
            self._fail_save = False
            raise LifecyclePortError(LifecycleFailureCode.LEDGER_SAVE)
        self._ledger = ledger
        return LedgerWriteResult.SAVED

    def remove(self, installation_id: InstallationId) -> LedgerWriteResult:
        self.effect_calls += 1
        if isinstance(self._ledger, OwnedInstallLedger) and self._ledger.installation_id == installation_id:
            self._ledger = LedgerAbsent()
        return LedgerWriteResult.REMOVED

    def replace_for_test(self, ledger: OwnedInstallLedger) -> None:
        self._ledger = ledger


class FakeHostLifecycle:
    def __init__(self) -> None:
        self._receipt: HostRegistrationReceipt | None = None
        self._fail_register = False
        self._fail_remove = False
        self.effect_calls = 0

    def fail_next_register(self) -> None:
        self._fail_register = True

    def fail_next_remove(self) -> None:
        self._fail_remove = True

    def register(self, installation_id: InstallationId, host_id: HostId) -> HostRegistrationReceipt:
        self.effect_calls += 1
        if self._fail_register:
            self._fail_register = False
            raise LifecyclePortError(LifecycleFailureCode.HOST_REGISTER)
        receipt = HostRegistrationReceipt(
            installation_id=installation_id,
            host_id=host_id,
            registration_ref=f"owned:{installation_id.value}:{host_id.value}",
        )
        self._receipt = receipt
        return receipt

    def matches(self, receipt: HostRegistrationReceipt) -> bool:
        return self._receipt == receipt

    def remove(self, receipt: HostRegistrationReceipt) -> HostRemovalResult:
        self.effect_calls += 1
        if self._fail_remove:
            self._fail_remove = False
            raise LifecyclePortError(LifecycleFailureCode.HOST_REMOVE)
        if self._receipt == receipt:
            self._receipt = None
        return HostRemovalResult.REMOVED

    def has_registration(self, installation_id: InstallationId) -> bool:
        return self._receipt is not None and self._receipt.installation_id == installation_id


class FakeProcessLifecycle:
    def __init__(self) -> None:
        self.stopped: list[InstallationId] = []
        self.effect_calls = 0

    def stop(self, installation_id: InstallationId) -> ProcessStopResult:
        self.effect_calls += 1
        self.stopped.append(installation_id)
        return ProcessStopResult.STOPPED_OR_ABSENT


def digest_bytes(content: bytes) -> ArtifactDigest:
    return ArtifactDigest(value=sha256(content).hexdigest())
