"""Forward-only composition for an admitted Codex registration capability."""

from __future__ import annotations

from enum import Enum
from threading import RLock
from types import MethodType
from typing import Callable, Final, Literal, NoReturn, TypeAlias
from weakref import ReferenceType, ref

from pydantic import BaseModel, ConfigDict

from .codex_registration_port import (
    CodexRegistrationPortAdmitted,
    CodexRegistrationPortCapability,
    admit_codex_registration_port,
)
from .codex_registration_reducer import (
    CodexFreshPreflightPending,
    CodexMarketplaceAddPending,
    CodexPluginAddPending,
)
from .codex_registration_transaction import (
    CodexRegistrationRecoveryView,
    CodexRegistrationStartedPhase,
    CodexRegistrationTransactionBegin,
    CodexRegistrationTransactionBlockReason,
    CodexRegistrationTransactionBlocked,
    CodexRegistrationTransactionComplete,
    CodexRegistrationTransactionCoordinator,
)


class _StrictModel(BaseModel):
    """Frozen strict metadata that never carries an admitted operation."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, revalidate_instances="always")


class CodexRegistrationForwardRejectReason(str, Enum):
    """Finite forward-composition admission failures."""

    INVALID_PORT = "INVALID_PORT"


class CodexRegistrationForwardBlocked(_StrictModel):
    """Metadata-only rejection of an untrusted capability value."""

    status: Literal["FORWARD_BLOCKED"] = "FORWARD_BLOCKED"
    reason: CodexRegistrationForwardRejectReason


class CodexRegistrationForwardAdmitted(_StrictModel):
    """Safe public view of a live forward coordinator."""

    status: Literal["FORWARD_ADMITTED"] = "FORWARD_ADMITTED"
    operation_count: Literal[3] = 3


class _CoordinatorToken:
    """Private construction authority for one forward coordinator."""


_COORDINATOR_TOKEN: Final[_CoordinatorToken] = _CoordinatorToken()


class _CoordinatorAuthority:
    """One owner-bound capability and transaction identity."""

    __slots__ = ("_capability", "_owner", "_transaction")

    _capability: CodexRegistrationPortCapability
    _owner: CodexRegistrationForwardCoordinator
    _transaction: CodexRegistrationTransactionCoordinator

    def __init__(
        self,
        token: object,
        owner: CodexRegistrationForwardCoordinator,
        capability: CodexRegistrationPortCapability,
        transaction: CodexRegistrationTransactionCoordinator,
    ) -> None:
        if token is not _COORDINATOR_TOKEN:
            raise TypeError("forward authority construction is forbidden")
        object.__setattr__(self, "_owner", owner)
        object.__setattr__(self, "_capability", capability)
        object.__setattr__(self, "_transaction", transaction)

    def __setattr__(self, name: str, value: object) -> NoReturn:
        raise AttributeError("forward authority is immutable")


class CodexRegistrationForwardCoordinator:
    """Own one rebuilt capability and one private transaction coordinator."""

    __slots__ = ("_capability", "_token", "_transaction", "__weakref__")

    _capability: CodexRegistrationPortCapability
    _token: _CoordinatorAuthority
    _transaction: CodexRegistrationTransactionCoordinator

    def __init__(
        self,
        token: object,
        capability: CodexRegistrationPortCapability,
        transaction: CodexRegistrationTransactionCoordinator,
    ) -> None:
        raise TypeError("forward coordinator construction is forbidden")

    def __setattr__(self, name: str, value: object) -> NoReturn:
        raise AttributeError("forward coordinator is immutable")

    def __copy__(self) -> NoReturn:
        raise TypeError("forward coordinator transfer is forbidden")

    def __deepcopy__(self, memo: dict[int, object]) -> NoReturn:
        raise TypeError("forward coordinator transfer is forbidden")

    def __reduce__(self) -> NoReturn:
        raise TypeError("forward coordinator transfer is forbidden")

    def __reduce_ex__(self, protocol: object) -> NoReturn:
        raise TypeError("forward coordinator transfer is forbidden")

    def _has_exact_authority(self) -> bool:
        if type(self) is not CodexRegistrationForwardCoordinator:
            return False
        try:
            authority_value: object = object.__getattribute__(self, "_token")
            capability_value: object = object.__getattribute__(self, "_capability")
            transaction_value: object = object.__getattribute__(self, "_transaction")
        except (AttributeError, TypeError):
            return False
        if (
            type(authority_value) is not _CoordinatorAuthority
            or type(capability_value) is not CodexRegistrationPortCapability
            or type(transaction_value) is not CodexRegistrationTransactionCoordinator
        ):
            return False
        authority = authority_value
        try:
            owner_value: object = object.__getattribute__(authority, "_owner")
            admitted_capability_value: object = object.__getattribute__(authority, "_capability")
            admitted_transaction_value: object = object.__getattribute__(authority, "_transaction")
        except (AttributeError, TypeError):
            return False
        if (
            owner_value is not self
            or admitted_capability_value is not capability_value
            or admitted_transaction_value is not transaction_value
        ):
            return False
        return _has_registered_coordinator(self, capability_value, transaction_value)

    def metadata(self) -> CodexRegistrationForwardAdmitted:
        """Return only finite status and operation-count metadata."""

        if not self._has_exact_authority():
            raise TypeError("forward coordinator authority is invalid")
        return CodexRegistrationForwardAdmitted()

    def begin(self, value: object) -> CodexRegistrationTransactionBegin:
        """Begin one exact request through the private transaction authority."""

        if not self._has_exact_authority():
            return _transaction_blocked(CodexRegistrationTransactionBlockReason.INVALID_STATE)
        return self._transaction.begin(value)

    def execute(self, value: object) -> CodexRegistrationTransactionComplete:
        """Consume one lease, invoke one exact operation, and complete it once."""

        if not self._has_exact_authority():
            return _transaction_blocked(CodexRegistrationTransactionBlockReason.INVALID_STATE)
        started = self._transaction.start(value)
        if type(started) is CodexRegistrationTransactionBlocked:
            return started
        if type(started) is not CodexRegistrationStartedPhase:
            return _transaction_blocked(CodexRegistrationTransactionBlockReason.INVALID_STATE)
        pending: object = started.pending
        if type(pending) is CodexFreshPreflightPending:
            returned: object = self._capability.fresh_preflight(pending.request)
        elif type(pending) is CodexMarketplaceAddPending:
            returned = self._capability.add_marketplace(pending.request)
        elif type(pending) is CodexPluginAddPending:
            returned = self._capability.add_plugin(pending.request)
        else:
            return _transaction_blocked(CodexRegistrationTransactionBlockReason.INVALID_STATE)
        return self._transaction.complete(value, returned)

    def recovery(self, value: object) -> CodexRegistrationRecoveryView:
        """Expose only B2A conservative recovery data for one started add."""

        if not self._has_exact_authority():
            return _transaction_blocked(CodexRegistrationTransactionBlockReason.INVALID_STATE)
        return self._transaction.recovery(value)

    def __repr__(self) -> str:
        metadata = self.metadata()
        return (
            "CodexRegistrationForwardCoordinator("
            f"status='{metadata.status}', operation_count={metadata.operation_count})"
        )


CodexRegistrationForwardAdmission: TypeAlias = (
    CodexRegistrationForwardCoordinator | CodexRegistrationForwardBlocked
)


_CoordinatorValidator: TypeAlias = Callable[
    [
        CodexRegistrationForwardCoordinator,
        CodexRegistrationPortCapability,
        CodexRegistrationTransactionCoordinator,
    ],
    bool,
]
_ForwardAdmissionFactory: TypeAlias = Callable[[object], CodexRegistrationForwardAdmission]


def _build_forward_admission_system() -> tuple[_ForwardAdmissionFactory, _CoordinatorValidator]:
    """Bind registration provenance to the one public admission closure."""

    class CoordinatorProvenance:
        """Weakly owned identity record inaccessible through module attributes."""

        __slots__ = ("capability", "owner_reference", "transaction")

        capability: CodexRegistrationPortCapability
        owner_reference: ReferenceType[CodexRegistrationForwardCoordinator]
        transaction: CodexRegistrationTransactionCoordinator

        def __init__(
            self,
            owner_reference: ReferenceType[CodexRegistrationForwardCoordinator],
            capability: CodexRegistrationPortCapability,
            transaction: CodexRegistrationTransactionCoordinator,
        ) -> None:
            self.owner_reference = owner_reference
            self.capability = capability
            self.transaction = transaction

    registry_lock = RLock()
    registry: dict[int, CoordinatorProvenance] = {}

    def validate(
        coordinator: CodexRegistrationForwardCoordinator,
        capability: CodexRegistrationPortCapability,
        transaction: CodexRegistrationTransactionCoordinator,
    ) -> bool:
        coordinator_identity = id(coordinator)
        with registry_lock:
            try:
                provenance = registry[coordinator_identity]
            except KeyError:
                return False
            return (
                provenance.owner_reference() is coordinator
                and provenance.capability is capability
                and provenance.transaction is transaction
            )

    def register(
        capability: CodexRegistrationPortCapability,
        transaction: CodexRegistrationTransactionCoordinator,
    ) -> CodexRegistrationForwardCoordinator:
        coordinator = object.__new__(CodexRegistrationForwardCoordinator)
        authority = _CoordinatorAuthority(_COORDINATOR_TOKEN, coordinator, capability, transaction)
        object.__setattr__(coordinator, "_token", authority)
        object.__setattr__(coordinator, "_capability", capability)
        object.__setattr__(coordinator, "_transaction", transaction)
        coordinator_identity = id(coordinator)

        def owner_collected(
            owner_reference: ReferenceType[CodexRegistrationForwardCoordinator],
        ) -> None:
            with registry_lock:
                try:
                    provenance = registry[coordinator_identity]
                except KeyError:
                    return
                if provenance.owner_reference is owner_reference:
                    del registry[coordinator_identity]

        owner_reference = ref(coordinator, owner_collected)
        with registry_lock:
            registry[coordinator_identity] = CoordinatorProvenance(
                owner_reference,
                capability,
                transaction,
            )
        return coordinator

    def admit(capability: object) -> CodexRegistrationForwardAdmission:
        rebuilt = _rebuild_capability(capability)
        if isinstance(rebuilt, CodexRegistrationForwardBlocked):
            return rebuilt
        return register(rebuilt, CodexRegistrationTransactionCoordinator())

    return admit, validate


admit_codex_registration_forward, _has_registered_coordinator = _build_forward_admission_system()
del _build_forward_admission_system


def _rebuild_capability(
    candidate: object,
) -> CodexRegistrationPortCapability | CodexRegistrationForwardBlocked:
    if type(candidate) is not CodexRegistrationPortCapability:
        return _forward_blocked()
    capability = candidate
    try:
        status_value: object = capability.status
        fresh_value: object = capability.fresh_preflight
        marketplace_value: object = capability.add_marketplace
        plugin_value: object = capability.add_plugin
        proof_value: object = capability.prove
        metadata_value: object = capability.metadata()
    except (AttributeError, TypeError, ValueError):
        return _forward_blocked()
    if (
        type(status_value) is not str
        or type(fresh_value) is not MethodType
        or type(marketplace_value) is not MethodType
        or type(plugin_value) is not MethodType
        or type(proof_value) is not MethodType
        or type(metadata_value) is not CodexRegistrationPortAdmitted
    ):
        return _forward_blocked()
    metadata = metadata_value
    try:
        metadata_status_value: object = metadata.status
        operation_count_value: object = metadata.operation_count
    except (AttributeError, TypeError, ValueError):
        return _forward_blocked()
    if type(metadata_status_value) is not str or type(operation_count_value) is not int:
        return _forward_blocked()
    if status_value != "ADMITTED" or metadata_status_value != "ADMITTED" or operation_count_value != 4:
        return _forward_blocked()
    fresh = fresh_value
    marketplace = marketplace_value
    plugin = plugin_value
    proof = proof_value
    owner: object = fresh.__self__
    if marketplace.__self__ is not owner or plugin.__self__ is not owner or proof.__self__ is not owner:
        return _forward_blocked()
    rebuilt_value = admit_codex_registration_port(owner)
    if type(rebuilt_value) is not CodexRegistrationPortCapability:
        return _forward_blocked()
    rebuilt = rebuilt_value
    rebuilt_fresh_value: object = rebuilt.fresh_preflight
    rebuilt_marketplace_value: object = rebuilt.add_marketplace
    rebuilt_plugin_value: object = rebuilt.add_plugin
    rebuilt_proof_value: object = rebuilt.prove
    if (
        type(rebuilt_fresh_value) is not MethodType
        or type(rebuilt_marketplace_value) is not MethodType
        or type(rebuilt_plugin_value) is not MethodType
        or type(rebuilt_proof_value) is not MethodType
    ):
        return _forward_blocked()
    if (
        fresh.__func__ is not rebuilt_fresh_value.__func__
        or marketplace.__func__ is not rebuilt_marketplace_value.__func__
        or plugin.__func__ is not rebuilt_plugin_value.__func__
        or proof.__func__ is not rebuilt_proof_value.__func__
    ):
        return _forward_blocked()
    return rebuilt


def _forward_blocked() -> CodexRegistrationForwardBlocked:
    return CodexRegistrationForwardBlocked(reason=CodexRegistrationForwardRejectReason.INVALID_PORT)


def _transaction_blocked(
    reason: CodexRegistrationTransactionBlockReason,
) -> CodexRegistrationTransactionBlocked:
    return CodexRegistrationTransactionBlocked(reason=reason)
