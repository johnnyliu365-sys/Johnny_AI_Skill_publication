"""Attempt-owned install transaction with verified plan and exact compensation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .johnny_router_contracts import PreflightProbe
from .runtime_dependency_lock import RuntimeDependencyLock
from .windows_package_manifest import PayloadManifest

_MINIMUM_PYTHON = (3, 11)
_EXCLUDED_PYTHON = (3, 14)
_SHA256_FIELD = Field(pattern=r"^[0-9a-f]{64}$")

_OutcomeSupplier: TypeAlias = "Callable[[], InstallEffectOutcome]"
_ReceiptRemover: TypeAlias = "Callable[[str], bool]"


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
    )


class InstallEffectKind(str, Enum):
    """The finite attempt-owned effect surfaces of one install."""

    VENV = "VENV"
    PLUGIN_PAYLOAD = "PLUGIN_PAYLOAD"
    LAUNCHER = "LAUNCHER"


class PluginInstallStatus(str, Enum):
    """Finite outcomes of one install attempt."""

    INSTALLED = "INSTALLED"
    BLOCKED = "BLOCKED"
    COMPENSATED = "COMPENSATED"
    COMPENSATION_INCOMPLETE = "COMPENSATION_INCOMPLETE"


class PluginInstallFailure(str, Enum):
    """Finite reasons an install attempt stops or unwinds."""

    REQUEST_INVALID = "REQUEST_INVALID"
    LOCK_DIGEST_MISMATCH = "LOCK_DIGEST_MISMATCH"
    MANIFEST_DIGEST_MISMATCH = "MANIFEST_DIGEST_MISMATCH"
    ARCHIVE_UNAVAILABLE = "ARCHIVE_UNAVAILABLE"
    ARCHIVE_HASH_MISMATCH = "ARCHIVE_HASH_MISMATCH"
    HOST_PROBE_UNAVAILABLE = "HOST_PROBE_UNAVAILABLE"
    GIT_UNAVAILABLE = "GIT_UNAVAILABLE"
    PYTHON_UNAVAILABLE = "PYTHON_UNAVAILABLE"
    PYTHON_INCOMPATIBLE = "PYTHON_INCOMPATIBLE"
    ATTEMPT_CONFLICT = "ATTEMPT_CONFLICT"
    JOURNAL_UNAVAILABLE = "JOURNAL_UNAVAILABLE"
    DEPENDENCY_HASH_MISMATCH = "DEPENDENCY_HASH_MISMATCH"
    EFFECT_UNAVAILABLE = "EFFECT_UNAVAILABLE"
    EFFECT_INTERRUPTED = "EFFECT_INTERRUPTED"
    REGISTRATION_READBACK_FAILED = "REGISTRATION_READBACK_FAILED"


class InstallDependencyPlanEntry(_StrictModel):
    """One pinned dependency identity presented before any effect."""

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    artifact_sha256s: tuple[str, ...] = Field(min_length=1)


class InstallDependencyPlan(_StrictModel):
    """The exact metadata-only dependency plan derived from the approved lock."""

    python_constraint: str = Field(min_length=1)
    entries: tuple[InstallDependencyPlanEntry, ...] = Field(min_length=1)


class ApprovedBundleReference(_StrictModel):
    """Digest identity of the user-approved bundle archive and manifest."""

    archive_sha256: str = _SHA256_FIELD
    manifest_digest: str = _SHA256_FIELD


class PluginInstallRequest(_StrictModel):
    """One exact install attempt bound to approved bundle evidence."""

    attempt_id: str = Field(pattern=r"^[a-z][a-z0-9-]{2,127}$")
    bundle: ApprovedBundleReference
    manifest: PayloadManifest
    runtime_lock: RuntimeDependencyLock


class InstallEffectRecord(_StrictModel):
    """One attempt-owned effect receipt recorded in creation order."""

    kind: InstallEffectKind
    receipt: str = Field(min_length=1, max_length=256)


class InstallEffectOutcomeStatus(str, Enum):
    """Finite per-effect port outcomes."""

    COMPLETED = "COMPLETED"
    HASH_MISMATCH = "HASH_MISMATCH"
    UNAVAILABLE = "UNAVAILABLE"


class InstallEffectOutcome(_StrictModel):
    """One effect-port return; a receipt exists exactly on completion."""

    status: InstallEffectOutcomeStatus
    receipt: str | None = None

    @model_validator(mode="after")
    def receipt_matches_status(self) -> Self:
        if self.status is InstallEffectOutcomeStatus.COMPLETED:
            if self.receipt is None:
                raise ValueError("a completed effect requires its receipt")
        elif self.receipt is not None:
            raise ValueError("a failed effect cannot carry a receipt")
        return self


class InstallJournalOpenStatus(str, Enum):
    """Finite journal admission outcomes for one attempt identity."""

    OPENED = "OPENED"
    CONFLICT = "CONFLICT"
    UNAVAILABLE = "UNAVAILABLE"


class InstallJournalOpenResult(_StrictModel):
    status: InstallJournalOpenStatus


class PluginInstallResult(_StrictModel):
    """Exactly one finite install outcome with metadata-only evidence."""

    status: PluginInstallStatus
    failure: PluginInstallFailure | None = None
    plan: InstallDependencyPlan | None = None
    effects: tuple[InstallEffectRecord, ...] = ()
    compensated: tuple[InstallEffectKind, ...] = ()
    uncompensated: tuple[InstallEffectKind, ...] = ()

    @model_validator(mode="after")
    def exact_outcome_shape(self) -> Self:
        if self.status is PluginInstallStatus.INSTALLED:
            if self.failure is not None or self.plan is None:
                raise ValueError("an installed result carries a plan and no failure")
            if len(self.effects) != len(InstallEffectKind):
                raise ValueError("an installed result records every effect")
            if self.compensated or self.uncompensated:
                raise ValueError("an installed result compensates nothing")
        elif self.status is PluginInstallStatus.BLOCKED:
            if self.failure is None:
                raise ValueError("a blocked result requires its failure")
            if self.effects or self.compensated or self.uncompensated:
                raise ValueError("a blocked result precedes every effect")
        else:
            if self.failure is None or not self.effects:
                raise ValueError(
                    "a compensated result requires the originating failure and effects"
                )
            if self.status is PluginInstallStatus.COMPENSATED and self.uncompensated:
                raise ValueError("a compensated result leaves no remainder")
            if (
                self.status is PluginInstallStatus.COMPENSATION_INCOMPLETE
                and not self.uncompensated
            ):
                raise ValueError("an incomplete compensation names its remainder")
        return self


class InstallHostProbePort(Protocol):
    """Read-only host capability probe."""

    def probe(self) -> PreflightProbe: ...


class InstallArchivePort(Protocol):
    """Read-only digest observation of the staged bundle archive."""

    def read_archive_sha256(self) -> str: ...


class InstallAttemptJournalPort(Protocol):
    """Durable attempt-owned effect journal."""

    def open(self, attempt_id: str) -> InstallJournalOpenResult: ...

    def record(self, attempt_id: str, record: InstallEffectRecord) -> bool: ...

    def seal(self, attempt_id: str) -> bool: ...


class VenvEffectPort(Protocol):
    """Attempt-owned control-plane environment effects."""

    def create(
        self, attempt_id: str, plan: InstallDependencyPlan
    ) -> InstallEffectOutcome: ...

    def remove(self, receipt: str) -> bool: ...


class PluginPayloadEffectPort(Protocol):
    """Attempt-owned plugin payload effects."""

    def install(
        self, attempt_id: str, manifest: PayloadManifest
    ) -> InstallEffectOutcome: ...

    def remove(self, receipt: str) -> bool: ...


class LauncherEffectPort(Protocol):
    """Attempt-owned launcher effects."""

    def create(self, attempt_id: str) -> InstallEffectOutcome: ...

    def remove(self, receipt: str) -> bool: ...


class RegistrationReadbackPort(Protocol):
    """Post-effect registration readback proof."""

    def readback(self, attempt_id: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class PluginInstallPorts:
    """Every injected boundary of one install transaction."""

    host_probe: InstallHostProbePort
    archive: InstallArchivePort
    journal: InstallAttemptJournalPort
    venv: VenvEffectPort
    plugin_payload: PluginPayloadEffectPort
    launcher: LauncherEffectPort
    registration: RegistrationReadbackPort


def _plan_from_lock(runtime_lock: RuntimeDependencyLock) -> InstallDependencyPlan:
    return InstallDependencyPlan(
        python_constraint=runtime_lock.python_constraint,
        entries=tuple(
            InstallDependencyPlanEntry(
                name=dependency.normalized_name,
                version=dependency.exact_version,
                artifact_sha256s=tuple(
                    artifact.sha256 for artifact in dependency.artifacts
                ),
            )
            for dependency in runtime_lock.dependencies
        ),
    )


def _blocked(failure: PluginInstallFailure) -> PluginInstallResult:
    return PluginInstallResult(status=PluginInstallStatus.BLOCKED, failure=failure)


_EFFECT_FAILURES: dict[InstallEffectOutcomeStatus, PluginInstallFailure] = {
    InstallEffectOutcomeStatus.HASH_MISMATCH: (
        PluginInstallFailure.DEPENDENCY_HASH_MISMATCH
    ),
    InstallEffectOutcomeStatus.UNAVAILABLE: PluginInstallFailure.EFFECT_UNAVAILABLE,
}


class PluginInstallTransaction:
    """Verify, plan, apply and, on failure, unwind one attempt's own effects."""

    def __init__(self, ports: PluginInstallPorts) -> None:
        self._ports = ports

    def run(self, request: PluginInstallRequest) -> PluginInstallResult:
        if type(request) is not PluginInstallRequest:
            return _blocked(PluginInstallFailure.REQUEST_INVALID)
        try:
            trusted = PluginInstallRequest.model_validate(request, strict=True)
        except ValidationError:
            return _blocked(PluginInstallFailure.REQUEST_INVALID)

        # RuntimeDependencyLock is closed by construction: a validated instance
        # always equals the approved lock, so no separate equality gate exists.
        if trusted.manifest.dependency_lock_digest != trusted.runtime_lock.lock_digest:
            return _blocked(PluginInstallFailure.LOCK_DIGEST_MISMATCH)
        if trusted.manifest.canonical_digest() != trusted.bundle.manifest_digest:
            return _blocked(PluginInstallFailure.MANIFEST_DIGEST_MISMATCH)

        try:
            observed_digest = self._ports.archive.read_archive_sha256()
        except Exception:
            return _blocked(PluginInstallFailure.ARCHIVE_UNAVAILABLE)
        if (
            type(observed_digest) is not str
            or len(observed_digest) != 64
            or any(character not in "0123456789abcdef" for character in observed_digest)
        ):
            return _blocked(PluginInstallFailure.ARCHIVE_UNAVAILABLE)
        if observed_digest != trusted.bundle.archive_sha256:
            return _blocked(PluginInstallFailure.ARCHIVE_HASH_MISMATCH)

        try:
            probe = PreflightProbe.model_validate(
                self._ports.host_probe.probe(), strict=True
            )
        except Exception:
            return _blocked(PluginInstallFailure.HOST_PROBE_UNAVAILABLE)
        if not probe.git_available:
            return _blocked(PluginInstallFailure.GIT_UNAVAILABLE)
        if probe.python_version is None:
            return _blocked(PluginInstallFailure.PYTHON_UNAVAILABLE)
        version_pair = (probe.python_version[0], probe.python_version[1])
        if version_pair < _MINIMUM_PYTHON or version_pair >= _EXCLUDED_PYTHON:
            return _blocked(PluginInstallFailure.PYTHON_INCOMPATIBLE)

        plan = _plan_from_lock(trusted.runtime_lock)

        try:
            admission = InstallJournalOpenResult.model_validate(
                self._ports.journal.open(trusted.attempt_id), strict=True
            )
        except Exception:
            return _blocked(PluginInstallFailure.JOURNAL_UNAVAILABLE)
        if admission.status is InstallJournalOpenStatus.CONFLICT:
            return _blocked(PluginInstallFailure.ATTEMPT_CONFLICT)
        if admission.status is not InstallJournalOpenStatus.OPENED:
            return _blocked(PluginInstallFailure.JOURNAL_UNAVAILABLE)

        recorded: list[InstallEffectRecord] = []

        failure = self._apply_effects(trusted, plan, recorded)
        if failure is not None:
            return self._unwind(failure, plan, recorded)

        try:
            readback_confirmed = self._ports.registration.readback(trusted.attempt_id)
        except Exception:
            readback_confirmed = False
        if readback_confirmed is not True:
            return self._unwind(
                PluginInstallFailure.REGISTRATION_READBACK_FAILED, plan, recorded
            )

        try:
            sealed = self._ports.journal.seal(trusted.attempt_id)
        except Exception:
            sealed = False
        if sealed is not True:
            return self._unwind(PluginInstallFailure.JOURNAL_UNAVAILABLE, plan, recorded)

        return PluginInstallResult(
            status=PluginInstallStatus.INSTALLED,
            plan=plan,
            effects=tuple(recorded),
        )

    def _apply_effects(
        self,
        trusted: PluginInstallRequest,
        plan: InstallDependencyPlan,
        recorded: list[InstallEffectRecord],
    ) -> PluginInstallFailure | None:
        def apply_one(
            kind: InstallEffectKind, outcome_supplier: "_OutcomeSupplier"
        ) -> PluginInstallFailure | None:
            try:
                outcome = InstallEffectOutcome.model_validate(
                    outcome_supplier(), strict=True
                )
            except ValidationError:
                return PluginInstallFailure.EFFECT_UNAVAILABLE
            except Exception:
                return PluginInstallFailure.EFFECT_INTERRUPTED
            if outcome.status is not InstallEffectOutcomeStatus.COMPLETED:
                return _EFFECT_FAILURES[outcome.status]
            receipt = outcome.receipt
            assert receipt is not None
            record = InstallEffectRecord(kind=kind, receipt=receipt)
            recorded.append(record)
            try:
                journaled = self._ports.journal.record(trusted.attempt_id, record)
            except Exception:
                journaled = False
            if journaled is not True:
                return PluginInstallFailure.JOURNAL_UNAVAILABLE
            return None

        steps: tuple[tuple[InstallEffectKind, _OutcomeSupplier], ...] = (
            (
                InstallEffectKind.VENV,
                lambda: self._ports.venv.create(trusted.attempt_id, plan),
            ),
            (
                InstallEffectKind.PLUGIN_PAYLOAD,
                lambda: self._ports.plugin_payload.install(
                    trusted.attempt_id, trusted.manifest
                ),
            ),
            (
                InstallEffectKind.LAUNCHER,
                lambda: self._ports.launcher.create(trusted.attempt_id),
            ),
        )
        for kind, supplier in steps:
            failure = apply_one(kind, supplier)
            if failure is not None:
                return failure
        return None

    def _unwind(
        self,
        failure: PluginInstallFailure,
        plan: InstallDependencyPlan,
        recorded: list[InstallEffectRecord],
    ) -> PluginInstallResult:
        if not recorded:
            return _blocked(failure)
        removers: dict[InstallEffectKind, "_ReceiptRemover"] = {
            InstallEffectKind.VENV: self._ports.venv.remove,
            InstallEffectKind.PLUGIN_PAYLOAD: self._ports.plugin_payload.remove,
            InstallEffectKind.LAUNCHER: self._ports.launcher.remove,
        }
        compensated: list[InstallEffectKind] = []
        uncompensated: list[InstallEffectKind] = []
        for record in reversed(recorded):
            try:
                removed = removers[record.kind](record.receipt)
            except Exception:
                removed = False
            if removed is True:
                compensated.append(record.kind)
            else:
                uncompensated.append(record.kind)
        status = (
            PluginInstallStatus.COMPENSATED
            if not uncompensated
            else PluginInstallStatus.COMPENSATION_INCOMPLETE
        )
        return PluginInstallResult(
            status=status,
            failure=failure,
            plan=plan,
            effects=tuple(recorded),
            compensated=tuple(compensated),
            uncompensated=tuple(uncompensated),
        )


__all__ = [
    "ApprovedBundleReference",
    "InstallAttemptJournalPort",
    "InstallDependencyPlan",
    "InstallDependencyPlanEntry",
    "InstallEffectKind",
    "InstallEffectOutcome",
    "InstallEffectOutcomeStatus",
    "InstallEffectRecord",
    "InstallHostProbePort",
    "InstallArchivePort",
    "InstallJournalOpenResult",
    "InstallJournalOpenStatus",
    "LauncherEffectPort",
    "PluginInstallFailure",
    "PluginInstallPorts",
    "PluginInstallRequest",
    "PluginInstallResult",
    "PluginInstallStatus",
    "PluginInstallTransaction",
    "PluginPayloadEffectPort",
    "RegistrationReadbackPort",
    "VenvEffectPort",
]
