"""Receipt-owned uninstall transaction: block, close, remove, prove, idempotent."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

_BoolAction: TypeAlias = Callable[[], bool]


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
    )


class OwnedStateKind(str, Enum):
    """The finite receipt-owned state surfaces removed by uninstall."""

    PLUGIN_PAYLOAD = "PLUGIN_PAYLOAD"
    VENV = "VENV"
    LAUNCHER = "LAUNCHER"
    QUEUE = "QUEUE"
    TELEMETRY = "TELEMETRY"


_REMOVAL_ORDER: tuple[OwnedStateKind, ...] = (
    OwnedStateKind.PLUGIN_PAYLOAD,
    OwnedStateKind.VENV,
    OwnedStateKind.LAUNCHER,
    OwnedStateKind.QUEUE,
    OwnedStateKind.TELEMETRY,
)


class PluginUninstallStatus(str, Enum):
    """Finite outcomes of one uninstall attempt."""

    REMOVED = "REMOVED"
    NOT_INSTALLED = "NOT_INSTALLED"
    BLOCKED = "BLOCKED"


class PluginUninstallFailure(str, Enum):
    """Finite reasons an uninstall attempt halts with the ledger retained."""

    REQUEST_INVALID = "REQUEST_INVALID"
    LEDGER_UNAVAILABLE = "LEDGER_UNAVAILABLE"
    LEDGER_FOREIGN = "LEDGER_FOREIGN"
    RESIDUAL_OWNED_STATE = "RESIDUAL_OWNED_STATE"
    WORK_BLOCK_FAILED = "WORK_BLOCK_FAILED"
    SUBSCRIPTION_CLOSE_FAILED = "SUBSCRIPTION_CLOSE_FAILED"
    RUNNER_STOP_FAILED = "RUNNER_STOP_FAILED"
    FOREIGN_STATE_PRESENT = "FOREIGN_STATE_PRESENT"
    REMOVAL_FAILED = "REMOVAL_FAILED"
    ABSENCE_READBACK_FAILED = "ABSENCE_READBACK_FAILED"
    LEDGER_REMOVE_FAILED = "LEDGER_REMOVE_FAILED"


class OwnedStateRecord(_StrictModel):
    """One receipt-owned state location recorded by the ownership ledger."""

    kind: OwnedStateKind
    receipt: str = Field(min_length=1, max_length=256)


class PluginUninstallLedger(_StrictModel):
    """The ownership ledger naming every receipt-owned state location."""

    receipt_id: str = Field(pattern=r"^[a-z][a-z0-9-]{2,127}$")
    records: tuple[OwnedStateRecord, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def one_record_per_kind(self) -> Self:
        kinds = tuple(record.kind for record in self.records)
        if len(set(kinds)) != len(kinds):
            raise ValueError("the ledger records at most one location per kind")
        return self


class PluginUninstallRequest(_StrictModel):
    """One exact uninstall bound to the owning receipt identity."""

    receipt_id: str = Field(pattern=r"^[a-z][a-z0-9-]{2,127}$")


class UninstallLedgerReadStatus(str, Enum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"


class UninstallLedgerReadResult(_StrictModel):
    """One ledger read; a ledger exists exactly when present."""

    status: UninstallLedgerReadStatus
    ledger: PluginUninstallLedger | None = None

    @model_validator(mode="after")
    def ledger_matches_status(self) -> Self:
        if (self.status is UninstallLedgerReadStatus.PRESENT) != (
            self.ledger is not None
        ):
            raise ValueError("a ledger exists exactly on a present read")
        return self


class UninstallOwnershipProbe(str, Enum):
    """Finite pre-delete ownership evidence for one recorded location."""

    OWNED = "OWNED"
    FOREIGN = "FOREIGN"
    UNKNOWN = "UNKNOWN"


class PluginUninstallResult(_StrictModel):
    """Exactly one finite uninstall outcome with metadata-only evidence."""

    status: PluginUninstallStatus
    failure: PluginUninstallFailure | None = None
    removed: tuple[OwnedStateKind, ...] = ()
    remaining: tuple[OwnedStateKind, ...] = ()
    ledger_retained: bool

    @model_validator(mode="after")
    def exact_outcome_shape(self) -> Self:
        if self.status is PluginUninstallStatus.REMOVED:
            if self.failure is not None or not self.removed or self.remaining:
                raise ValueError("a removed result lists every removal and no failure")
            if self.ledger_retained:
                raise ValueError("a removed result closes the ledger")
        elif self.status is PluginUninstallStatus.NOT_INSTALLED:
            if self.failure is not None or self.removed or self.remaining:
                raise ValueError("a not-installed result carries no evidence")
            if self.ledger_retained:
                raise ValueError("a not-installed result has no ledger to retain")
        else:
            if self.failure is None:
                raise ValueError("a blocked result requires its failure")
            if not self.ledger_retained and self.failure is not (
                PluginUninstallFailure.RESIDUAL_OWNED_STATE
            ):
                raise ValueError("a blocked result retains the ownership ledger")
        return self


class UninstallLedgerPort(Protocol):
    """Durable ownership ledger boundary."""

    def read(self) -> UninstallLedgerReadResult: ...

    def remove(self, receipt_id: str) -> bool: ...


class UninstallWorkAdmissionPort(Protocol):
    """Blocks new receipt-owned work before removal begins."""

    def block(self, receipt_id: str) -> bool: ...


class UninstallSubscriptionShutdownPort(Protocol):
    """Cancels every receipt-owned subscription."""

    def cancel_all(self, receipt_id: str) -> bool: ...


class UninstallRunnerShutdownPort(Protocol):
    """Stops every receipt-owned runner."""

    def stop_all(self, receipt_id: str) -> bool: ...


class UninstallOwnedStatePort(Protocol):
    """Ownership-checked removal of recorded state locations."""

    def probe(self, record: OwnedStateRecord) -> UninstallOwnershipProbe: ...

    def remove(self, record: OwnedStateRecord) -> bool: ...

    def has_owned_state(self, receipt_id: str) -> bool: ...


class UninstallAbsencePort(Protocol):
    """Post-removal absence readback for one recorded location."""

    def verify_absent(self, record: OwnedStateRecord) -> bool: ...


@dataclass(frozen=True, slots=True)
class PluginUninstallPorts:
    """Every injected boundary of one uninstall transaction."""

    ledger: UninstallLedgerPort
    work_admission: UninstallWorkAdmissionPort
    subscriptions: UninstallSubscriptionShutdownPort
    runners: UninstallRunnerShutdownPort
    owned_state: UninstallOwnedStatePort
    absence: UninstallAbsencePort


def _blocked(
    failure: PluginUninstallFailure,
    removed: tuple[OwnedStateKind, ...] = (),
    remaining: tuple[OwnedStateKind, ...] = (),
    ledger_retained: bool = True,
) -> PluginUninstallResult:
    return PluginUninstallResult(
        status=PluginUninstallStatus.BLOCKED,
        failure=failure,
        removed=removed,
        remaining=remaining,
        ledger_retained=ledger_retained,
    )


def _ordered_records(
    ledger: PluginUninstallLedger,
) -> tuple[OwnedStateRecord, ...]:
    by_kind = {record.kind: record for record in ledger.records}
    return tuple(
        by_kind[kind] for kind in _REMOVAL_ORDER if kind in by_kind
    )


class PluginUninstallTransaction:
    """Remove exactly the receipt-owned state or halt with the ledger intact."""

    def __init__(self, ports: PluginUninstallPorts) -> None:
        self._ports = ports

    def run(self, request: PluginUninstallRequest) -> PluginUninstallResult:
        if type(request) is not PluginUninstallRequest:
            return _blocked(PluginUninstallFailure.REQUEST_INVALID)
        try:
            trusted = PluginUninstallRequest.model_validate(request, strict=True)
        except ValidationError:
            return _blocked(PluginUninstallFailure.REQUEST_INVALID)

        try:
            read = UninstallLedgerReadResult.model_validate(
                self._ports.ledger.read(), strict=True
            )
        except Exception:
            return _blocked(PluginUninstallFailure.LEDGER_UNAVAILABLE)

        if read.status is UninstallLedgerReadStatus.ABSENT:
            try:
                residue = self._ports.owned_state.has_owned_state(trusted.receipt_id)
            except Exception:
                return _blocked(PluginUninstallFailure.LEDGER_UNAVAILABLE)
            if residue:
                return _blocked(
                    PluginUninstallFailure.RESIDUAL_OWNED_STATE,
                    ledger_retained=False,
                )
            return PluginUninstallResult(
                status=PluginUninstallStatus.NOT_INSTALLED,
                ledger_retained=False,
            )

        ledger = read.ledger
        assert ledger is not None
        if ledger.receipt_id != trusted.receipt_id:
            return _blocked(PluginUninstallFailure.LEDGER_FOREIGN)

        records = _ordered_records(ledger)
        all_kinds = tuple(record.kind for record in records)

        if not self._call_bool(
            lambda: self._ports.work_admission.block(trusted.receipt_id)
        ):
            return _blocked(
                PluginUninstallFailure.WORK_BLOCK_FAILED, remaining=all_kinds
            )
        if not self._call_bool(
            lambda: self._ports.subscriptions.cancel_all(trusted.receipt_id)
        ):
            return _blocked(
                PluginUninstallFailure.SUBSCRIPTION_CLOSE_FAILED, remaining=all_kinds
            )
        if not self._call_bool(
            lambda: self._ports.runners.stop_all(trusted.receipt_id)
        ):
            return _blocked(
                PluginUninstallFailure.RUNNER_STOP_FAILED, remaining=all_kinds
            )

        for record in records:
            try:
                probe = self._ports.owned_state.probe(record)
            except Exception:
                probe = UninstallOwnershipProbe.UNKNOWN
            if probe is not UninstallOwnershipProbe.OWNED:
                return _blocked(
                    PluginUninstallFailure.FOREIGN_STATE_PRESENT,
                    remaining=all_kinds,
                )

        removed: list[OwnedStateKind] = []
        for index, record in enumerate(records):
            if not self._call_bool(lambda: self._ports.owned_state.remove(record)):
                return _blocked(
                    PluginUninstallFailure.REMOVAL_FAILED,
                    removed=tuple(removed),
                    remaining=tuple(item.kind for item in records[index:]),
                )
            removed.append(record.kind)

        for record in records:
            if not self._call_bool(
                lambda: self._ports.absence.verify_absent(record)
            ):
                return _blocked(
                    PluginUninstallFailure.ABSENCE_READBACK_FAILED,
                    removed=tuple(removed),
                )

        if not self._call_bool(
            lambda: self._ports.ledger.remove(trusted.receipt_id)
        ):
            return _blocked(
                PluginUninstallFailure.LEDGER_REMOVE_FAILED,
                removed=tuple(removed),
            )

        return PluginUninstallResult(
            status=PluginUninstallStatus.REMOVED,
            removed=tuple(removed),
            ledger_retained=False,
        )

    @staticmethod
    def _call_bool(action: _BoolAction) -> bool:
        try:
            return action() is True
        except Exception:
            return False


__all__ = [
    "OwnedStateKind",
    "OwnedStateRecord",
    "PluginUninstallFailure",
    "PluginUninstallLedger",
    "PluginUninstallPorts",
    "PluginUninstallRequest",
    "PluginUninstallResult",
    "PluginUninstallStatus",
    "PluginUninstallTransaction",
    "UninstallAbsencePort",
    "UninstallLedgerPort",
    "UninstallLedgerReadResult",
    "UninstallLedgerReadStatus",
    "UninstallOwnedStatePort",
    "UninstallOwnershipProbe",
    "UninstallRunnerShutdownPort",
    "UninstallSubscriptionShutdownPort",
    "UninstallWorkAdmissionPort",
]
