"""Process-local authority for one exact Codex registration transaction."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from operator import index
from threading import RLock
from typing import Literal, NoReturn, SupportsIndex, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from .codex_registration_contracts import (
    CodexAttemptEffectState,
    CodexRegistrationAttemptId,
    CodexRegistrationAttemptJournal,
)
from .codex_registration_port import CodexRegistrationPortRequest
from .codex_registration_reducer import (
    CodexFreshPreflightPending,
    CodexMarketplaceAddPending,
    CodexPluginAddPending,
    CodexRegistrationBlocked,
    CodexRegistrationCompensationRequired,
    CodexRegistrationPending,
    CodexRegistrationProofRequired,
    advance_codex_registration,
    begin_codex_registration,
)


class _StrictModel(BaseModel):
    """Frozen strict transaction data that never executes an operation."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
        arbitrary_types_allowed=True,
    )


class CodexRegistrationPhase(str, Enum):
    """The finite registration phase bound to one lease generation."""

    FRESH_PREFLIGHT = "FRESH_PREFLIGHT"
    MARKETPLACE_ADD = "MARKETPLACE_ADD"
    PLUGIN_ADD = "PLUGIN_ADD"


class CodexRegistrationTransactionBlockReason(str, Enum):
    """Finite metadata-only transaction admission failures."""

    INVALID_REQUEST = "INVALID_REQUEST"
    DUPLICATE_ATTEMPT = "DUPLICATE_ATTEMPT"
    INVALID_LEASE = "INVALID_LEASE"
    REPLAYED = "REPLAYED"
    PHASE_MISMATCH = "PHASE_MISMATCH"
    INVALID_RESULT = "INVALID_RESULT"
    INVALID_STATE = "INVALID_STATE"


class CodexRegistrationGeneration(_StrictModel):
    """A positive, monotonically increasing phase generation."""

    value: int = Field(ge=1)


class CodexRegistrationLeaseMetadata(_StrictModel):
    """Safe lease metadata that is never sufficient transaction authority."""

    status: Literal["PHASE_LEASE"] = "PHASE_LEASE"
    attempt_id: CodexRegistrationAttemptId
    phase: CodexRegistrationPhase
    generation: CodexRegistrationGeneration


class _LeaseToken:
    """Per-coordinator construction authority, never exported by metadata."""


class CodexRegistrationPhaseLease:
    """Opaque, immutable, non-transferable authority for one live phase."""

    __slots__ = ("_metadata", "_owner", "_token")

    _metadata: CodexRegistrationLeaseMetadata
    _owner: CodexRegistrationTransactionCoordinator
    _token: _LeaseToken

    def __init__(
        self,
        token: object,
        owner: CodexRegistrationTransactionCoordinator,
        metadata: CodexRegistrationLeaseMetadata,
    ) -> None:
        raise TypeError("transaction lease construction is forbidden")

    def __setattr__(self, name: str, value: object) -> NoReturn:
        raise AttributeError("transaction lease is immutable")

    def __copy__(self) -> NoReturn:
        raise TypeError("transaction lease transfer is forbidden")

    def __deepcopy__(self, memo: dict[int, object]) -> NoReturn:
        raise TypeError("transaction lease transfer is forbidden")

    def __reduce__(self) -> NoReturn:
        raise TypeError("transaction lease transfer is forbidden")

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        index(protocol)
        raise TypeError("transaction lease transfer is forbidden")

    def metadata(self) -> CodexRegistrationLeaseMetadata:
        """Return a rebuilt metadata view without transferable authority."""

        metadata = self._metadata
        if type(metadata) is not CodexRegistrationLeaseMetadata:
            raise TypeError("transaction lease metadata is invalid")
        try:
            return CodexRegistrationLeaseMetadata(
                attempt_id=metadata.attempt_id,
                phase=metadata.phase,
                generation=CodexRegistrationGeneration(value=metadata.generation.value),
            )
        except (AttributeError, TypeError, ValueError):
            raise TypeError("transaction lease metadata is invalid") from None

    def __repr__(self) -> str:
        metadata = self.metadata()
        return (
            "CodexRegistrationPhaseLease("
            f"status='{metadata.status}', phase='{metadata.phase.value}', "
            f"generation={metadata.generation.value})"
        )


class _LeaseBearingModel(_StrictModel):
    lease: CodexRegistrationPhaseLease

    @field_serializer("lease")
    def serialize_lease(self, lease: CodexRegistrationPhaseLease) -> CodexRegistrationLeaseMetadata:
        return lease.metadata()


class CodexRegistrationReadyLease(_LeaseBearingModel):
    """Initial fresh-preflight lease and rebuilt B1 pending decision."""

    status: Literal["READY"] = "READY"
    pending: CodexFreshPreflightPending


class CodexRegistrationNextReadyPhase(_LeaseBearingModel):
    """Next marketplace/plugin phase with a distinct generation lease."""

    status: Literal["NEXT_READY"] = "NEXT_READY"
    pending: CodexMarketplaceAddPending | CodexPluginAddPending


class CodexRegistrationStartedPhase(_StrictModel):
    """Atomic start acknowledgement containing no transferable lease."""

    status: Literal["STARTED"] = "STARTED"
    metadata: CodexRegistrationLeaseMetadata
    pending: CodexRegistrationPending


CodexRegistrationTerminalDecision: TypeAlias = (
    CodexRegistrationProofRequired
    | CodexRegistrationCompensationRequired
    | CodexRegistrationBlocked
)


class CodexRegistrationTerminal(_StrictModel):
    """One exact terminal B1 decision retained behind a tombstone."""

    status: Literal["TERMINAL"] = "TERMINAL"
    metadata: CodexRegistrationLeaseMetadata
    decision: CodexRegistrationTerminalDecision


class CodexRegistrationAddRecovery(_StrictModel):
    """Conservative started-add data for a later compensation composer."""

    status: Literal["ADD_RECOVERY_REQUIRED"] = "ADD_RECOVERY_REQUIRED"
    phase: CodexRegistrationPhase
    request: CodexRegistrationPortRequest
    journal: CodexRegistrationAttemptJournal


class CodexRegistrationTransactionBlocked(_StrictModel):
    """Finite transaction rejection without caller values or diagnostics."""

    status: Literal["TRANSACTION_BLOCKED"] = "TRANSACTION_BLOCKED"
    reason: CodexRegistrationTransactionBlockReason


CodexRegistrationTransactionBegin: TypeAlias = (
    CodexRegistrationReadyLease | CodexRegistrationTransactionBlocked
)
CodexRegistrationTransactionStart: TypeAlias = (
    CodexRegistrationStartedPhase | CodexRegistrationTransactionBlocked
)
CodexRegistrationTransactionComplete: TypeAlias = (
    CodexRegistrationNextReadyPhase
    | CodexRegistrationTerminal
    | CodexRegistrationTransactionBlocked
)
CodexRegistrationRecoveryView: TypeAlias = (
    CodexRegistrationAddRecovery | CodexRegistrationTransactionBlocked
)


class _LiveState(str, Enum):
    READY = "READY"
    STARTED = "STARTED"


@dataclass(slots=True)
class _LiveAttempt:
    request: CodexRegistrationPortRequest
    pending: CodexRegistrationPending
    phase: CodexRegistrationPhase
    generation: int
    state: _LiveState
    lease: CodexRegistrationPhaseLease


@dataclass(frozen=True, slots=True)
class _TerminalAttempt:
    attempt_id: CodexRegistrationAttemptId


_AttemptRecord: TypeAlias = _LiveAttempt | _TerminalAttempt


class CodexRegistrationTransactionCoordinator:
    """Own atomic, process-local registration phase admission and tombstones."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._lease_token = _LeaseToken()
        self._attempts: dict[str, _AttemptRecord] = {}

    def begin(self, value: object) -> CodexRegistrationTransactionBegin:
        """Admit one exact attempt and issue its generation-one fresh lease."""

        pending = begin_codex_registration(value)
        if type(pending) is not CodexFreshPreflightPending:
            return _blocked(CodexRegistrationTransactionBlockReason.INVALID_REQUEST)
        fresh = pending
        try:
            request = CodexRegistrationPortRequest.model_validate(fresh.request.model_dump())
            rebuilt = CodexFreshPreflightPending.model_validate(fresh.model_dump())
            attempt_key = request.attempt_id.value
        except (AttributeError, TypeError, ValueError):
            return _blocked(CodexRegistrationTransactionBlockReason.INVALID_REQUEST)
        with self._lock:
            if attempt_key in self._attempts:
                return _blocked(CodexRegistrationTransactionBlockReason.DUPLICATE_ATTEMPT)
            lease = self._new_lease(request.attempt_id, CodexRegistrationPhase.FRESH_PREFLIGHT, 1)
            self._attempts[attempt_key] = _LiveAttempt(
                request=request,
                pending=rebuilt,
                phase=CodexRegistrationPhase.FRESH_PREFLIGHT,
                generation=1,
                state=_LiveState.READY,
                lease=lease,
            )
            return CodexRegistrationReadyLease(lease=lease, pending=rebuilt)

    def start(self, value: object) -> CodexRegistrationTransactionStart:
        """Atomically consume the ready state before returning continuation data."""

        with self._lock:
            admitted = self._admit_live_lease(value)
            if isinstance(admitted, CodexRegistrationTransactionBlocked):
                return admitted
            if admitted.state is not _LiveState.READY:
                return _blocked(CodexRegistrationTransactionBlockReason.REPLAYED)
            admitted.state = _LiveState.STARTED
            return CodexRegistrationStartedPhase(
                metadata=admitted.lease.metadata(),
                pending=_rebuild_pending(admitted.pending),
            )

    def complete(self, value: object, result: object) -> CodexRegistrationTransactionComplete:
        """Complete one started generation and advance or retain a tombstone."""

        with self._lock:
            admitted = self._admit_live_lease(value)
            if isinstance(admitted, CodexRegistrationTransactionBlocked):
                return admitted
            if admitted.state is not _LiveState.STARTED:
                return _blocked(CodexRegistrationTransactionBlockReason.INVALID_STATE)
            decision = advance_codex_registration(admitted.pending, result)
            if isinstance(decision, CodexFreshPreflightPending):
                return _blocked(CodexRegistrationTransactionBlockReason.INVALID_STATE)
            if isinstance(decision, CodexMarketplaceAddPending):
                return self._advance_ready(admitted, decision, CodexRegistrationPhase.MARKETPLACE_ADD)
            if isinstance(decision, CodexPluginAddPending):
                return self._advance_ready(admitted, decision, CodexRegistrationPhase.PLUGIN_ADD)
            metadata = admitted.lease.metadata()
            attempt_id = admitted.request.attempt_id
            self._attempts[attempt_id.value] = _TerminalAttempt(attempt_id=attempt_id)
            return CodexRegistrationTerminal(metadata=metadata, decision=decision)

    def recovery(self, value: object) -> CodexRegistrationRecoveryView:
        """Return conservative data only for an already-started add phase."""

        with self._lock:
            admitted = self._admit_live_lease(value)
            if isinstance(admitted, CodexRegistrationTransactionBlocked):
                return admitted
            if admitted.phase is CodexRegistrationPhase.FRESH_PREFLIGHT:
                return _blocked(CodexRegistrationTransactionBlockReason.PHASE_MISMATCH)
            if admitted.state is not _LiveState.STARTED:
                return _blocked(CodexRegistrationTransactionBlockReason.INVALID_STATE)
            marketplace_state = (
                CodexAttemptEffectState.MAY_EXIST
                if admitted.phase is CodexRegistrationPhase.MARKETPLACE_ADD
                else CodexAttemptEffectState.OWNED
            )
            plugin_state = (
                CodexAttemptEffectState.MAY_EXIST
                if admitted.phase is CodexRegistrationPhase.PLUGIN_ADD
                else CodexAttemptEffectState.NOT_ATTEMPTED
            )
            journal = CodexRegistrationAttemptJournal(
                request=admitted.request.preflight,
                attempt_id=admitted.request.attempt_id,
                marketplace_state=marketplace_state,
                plugin_state=plugin_state,
            )
            return CodexRegistrationAddRecovery(
                phase=admitted.phase,
                request=CodexRegistrationPortRequest.model_validate(admitted.request.model_dump()),
                journal=journal,
            )

    def _new_lease(
        self,
        attempt_id: CodexRegistrationAttemptId,
        phase: CodexRegistrationPhase,
        generation: int,
    ) -> CodexRegistrationPhaseLease:
        metadata = CodexRegistrationLeaseMetadata(
            attempt_id=attempt_id,
            phase=phase,
            generation=CodexRegistrationGeneration(value=generation),
        )
        lease = object.__new__(CodexRegistrationPhaseLease)
        object.__setattr__(lease, "_token", self._lease_token)
        object.__setattr__(lease, "_owner", self)
        object.__setattr__(lease, "_metadata", metadata)
        return lease

    def _advance_ready(
        self,
        current: _LiveAttempt,
        pending: CodexMarketplaceAddPending | CodexPluginAddPending,
        phase: CodexRegistrationPhase,
    ) -> CodexRegistrationNextReadyPhase | CodexRegistrationTransactionBlocked:
        generation = current.generation + 1
        rebuilt = _rebuild_pending(pending)
        if not isinstance(rebuilt, (CodexMarketplaceAddPending, CodexPluginAddPending)):
            return _blocked(CodexRegistrationTransactionBlockReason.INVALID_STATE)
        lease = self._new_lease(current.request.attempt_id, phase, generation)
        self._attempts[current.request.attempt_id.value] = _LiveAttempt(
            request=current.request,
            pending=rebuilt,
            phase=phase,
            generation=generation,
            state=_LiveState.READY,
            lease=lease,
        )
        return CodexRegistrationNextReadyPhase(lease=lease, pending=rebuilt)

    def _admit_live_lease(self, value: object) -> _LiveAttempt | CodexRegistrationTransactionBlocked:
        if type(value) is not CodexRegistrationPhaseLease:
            return _blocked(CodexRegistrationTransactionBlockReason.INVALID_LEASE)
        lease = value
        try:
            token_value: object = lease._token
            owner_value: object = lease._owner
            metadata_value: object = lease._metadata
        except (AttributeError, TypeError):
            return _blocked(CodexRegistrationTransactionBlockReason.INVALID_LEASE)
        if token_value is not self._lease_token or owner_value is not self:
            return _blocked(CodexRegistrationTransactionBlockReason.INVALID_LEASE)
        if type(metadata_value) is not CodexRegistrationLeaseMetadata:
            return _blocked(CodexRegistrationTransactionBlockReason.INVALID_LEASE)
        metadata = metadata_value
        try:
            status_value: object = metadata.status
            attempt_id_value: object = metadata.attempt_id
            phase_value: object = metadata.phase
            generation_value: object = metadata.generation
        except (AttributeError, TypeError, ValueError):
            return _blocked(CodexRegistrationTransactionBlockReason.INVALID_LEASE)
        if (
            type(status_value) is not str
            or type(attempt_id_value) is not CodexRegistrationAttemptId
            or type(phase_value) is not CodexRegistrationPhase
            or type(generation_value) is not CodexRegistrationGeneration
        ):
            return _blocked(CodexRegistrationTransactionBlockReason.INVALID_LEASE)
        attempt_id = attempt_id_value
        phase = phase_value
        generation = generation_value
        try:
            attempt_key_value: object = attempt_id.value
            generation_number_value: object = generation.value
        except (AttributeError, TypeError, ValueError):
            return _blocked(CodexRegistrationTransactionBlockReason.INVALID_LEASE)
        if type(attempt_key_value) is not str or type(generation_number_value) is not int:
            return _blocked(CodexRegistrationTransactionBlockReason.INVALID_LEASE)
        attempt_key = attempt_key_value
        generation_number = generation_number_value
        if status_value != "PHASE_LEASE" or generation_number < 1:
            return _blocked(CodexRegistrationTransactionBlockReason.INVALID_LEASE)
        record = self._attempts.get(attempt_key)
        if record is None:
            return _blocked(CodexRegistrationTransactionBlockReason.INVALID_LEASE)
        if isinstance(record, _TerminalAttempt):
            return _blocked(CodexRegistrationTransactionBlockReason.REPLAYED)
        if generation_number != record.generation:
            return _blocked(CodexRegistrationTransactionBlockReason.REPLAYED)
        if phase is not record.phase:
            return _blocked(CodexRegistrationTransactionBlockReason.PHASE_MISMATCH)
        if record.lease is not lease:
            return _blocked(CodexRegistrationTransactionBlockReason.INVALID_LEASE)
        return record


def _rebuild_pending(value: CodexRegistrationPending) -> CodexRegistrationPending:
    if type(value) is CodexFreshPreflightPending:
        return CodexFreshPreflightPending.model_validate(value.model_dump())
    if type(value) is CodexMarketplaceAddPending:
        return CodexMarketplaceAddPending.model_validate(value.model_dump())
    if type(value) is CodexPluginAddPending:
        return CodexPluginAddPending.model_validate(value.model_dump())
    raise TypeError("transaction pending state is invalid")


def _blocked(reason: CodexRegistrationTransactionBlockReason) -> CodexRegistrationTransactionBlocked:
    return CodexRegistrationTransactionBlocked(reason=reason)
