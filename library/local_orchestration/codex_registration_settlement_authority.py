"""One-shot, process-local authority for terminal Codex registration data."""

from __future__ import annotations

from enum import Enum
from threading import RLock
from types import FunctionType
from typing import Callable, Literal, NoReturn, TypeAlias, cast
from weakref import ReferenceType, ref

from pydantic import BaseModel, ConfigDict

from .codex_registration_contracts import CodexRegistrationAttemptId
from .codex_registration_forward import (
    CodexRegistrationForwardAdmitted,
    CodexRegistrationForwardCoordinator,
)
from .codex_registration_reducer import (
    CodexRegistrationCompensationRequired,
    CodexRegistrationProofRequired,
)
from .codex_registration_transaction import (
    CodexRegistrationAddRecovery,
    CodexRegistrationGeneration,
    CodexRegistrationLeaseMetadata,
    CodexRegistrationNextReadyPhase,
    CodexRegistrationPhase,
    CodexRegistrationPhaseLease,
    CodexRegistrationReadyLease,
    CodexRegistrationTerminal,
    CodexRegistrationTransactionBlockReason,
    CodexRegistrationTransactionBegin,
    CodexRegistrationTransactionBlocked,
    CodexRegistrationTransactionComplete,
    CodexRegistrationRecoveryView,
)



class _StrictModel(BaseModel):
    """Frozen metadata that carries no executable registration authority."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, revalidate_instances="always")


class CodexRegistrationSettlementAuthorityRejectReason(str, Enum):
    """Finite reasons why a forward coordinator cannot be wrapped."""

    INVALID_COORDINATOR = "INVALID_COORDINATOR"


class CodexRegistrationSettlementAuthorityBlocked(_StrictModel):
    """Metadata-only rejection before any forward state or operation call."""

    status: Literal["SETTLEMENT_AUTHORITY_BLOCKED"] = "SETTLEMENT_AUTHORITY_BLOCKED"
    reason: CodexRegistrationSettlementAuthorityRejectReason


class CodexRegistrationSettlementAuthorityAdmitted(_StrictModel):
    """Public view of one factory-proven settlement wrapper."""

    status: Literal["SETTLEMENT_AUTHORITY_ADMITTED"] = "SETTLEMENT_AUTHORITY_ADMITTED"
    operation_count: Literal[3] = 3


class CodexRegistrationSettlementClaimKind(str, Enum):
    """The finite settlement lane bound to a one-shot claim."""

    PROOF = "PROOF"
    COMPENSATION = "COMPENSATION"


class CodexRegistrationSettlementClaimBlockReason(str, Enum):
    """Finite claim consumption rejections."""

    INVALID_CLAIM = "INVALID_CLAIM"


class CodexRegistrationSettlementClaimBlocked(_StrictModel):
    """Finite rejection for a non-live, mismatched, or replayed claim."""

    status: Literal["CLAIM_BLOCKED"] = "CLAIM_BLOCKED"
    reason: CodexRegistrationSettlementClaimBlockReason


class CodexRegistrationSettlementClaimMetadata(_StrictModel):
    """Transferable metadata that is never sufficient claim authority."""

    status: Literal["SETTLEMENT_CLAIM"] = "SETTLEMENT_CLAIM"
    attempt_id: CodexRegistrationAttemptId
    phase: CodexRegistrationPhase
    generation: CodexRegistrationGeneration
    kind: CodexRegistrationSettlementClaimKind


class _CodexRegistrationSettlementClaim:
    """Common opaque shape for the two public, non-transferable claim types."""

    __slots__ = ("_metadata", "__weakref__")

    _metadata: CodexRegistrationSettlementClaimMetadata

    def __init__(self, metadata: CodexRegistrationSettlementClaimMetadata) -> None:
        raise TypeError("settlement claim construction is forbidden")

    def __setattr__(self, name: str, value: object) -> NoReturn:
        raise AttributeError("settlement claim is immutable")

    def __copy__(self) -> NoReturn:
        raise TypeError("settlement claim transfer is forbidden")

    def __deepcopy__(self, memo: dict[int, object]) -> NoReturn:
        raise TypeError("settlement claim transfer is forbidden")

    def __reduce__(self) -> NoReturn:
        raise TypeError("settlement claim transfer is forbidden")

    def __reduce_ex__(self, protocol: object) -> NoReturn:
        raise TypeError("settlement claim transfer is forbidden")

    def metadata(self) -> CodexRegistrationSettlementClaimMetadata:
        """Return only rebuilt finite metadata, never the live claim record."""

        raw_value: object
        try:
            raw_value = object.__getattribute__(self, "_metadata")
        except AttributeError:
            raise TypeError("settlement claim metadata is invalid") from None
        return _rebuild_claim_metadata(raw_value)

    def __repr__(self) -> str:
        metadata = self.metadata()
        return (
            f"{type(self).__name__}(status='{metadata.status}', "
            f"phase='{metadata.phase.value}', generation={metadata.generation.value}, "
            f"kind='{metadata.kind.value}')"
        )


class CodexRegistrationProofClaim(_CodexRegistrationSettlementClaim):
    """One live claim for exactly one terminal proof-required decision."""

    __slots__ = ()


class CodexRegistrationCompensationClaim(_CodexRegistrationSettlementClaim):
    """One live claim for terminal compensation or started-add recovery data."""

    __slots__ = ()


class CodexRegistrationSettlementAuthority:
    """Proxy one exact forward coordinator and issue only one-shot terminal claims."""

    __slots__ = ("_coordinator", "__weakref__")

    _coordinator: CodexRegistrationForwardCoordinator

    def __init__(self, coordinator: CodexRegistrationForwardCoordinator) -> None:
        raise TypeError("settlement authority construction is forbidden")

    def __setattr__(self, name: str, value: object) -> NoReturn:
        raise AttributeError("settlement authority is immutable")

    def __copy__(self) -> NoReturn:
        raise TypeError("settlement authority transfer is forbidden")

    def __deepcopy__(self, memo: dict[int, object]) -> NoReturn:
        raise TypeError("settlement authority transfer is forbidden")

    def __reduce__(self) -> NoReturn:
        raise TypeError("settlement authority transfer is forbidden")

    def __reduce_ex__(self, protocol: object) -> NoReturn:
        raise TypeError("settlement authority transfer is forbidden")

    def metadata(self) -> CodexRegistrationSettlementAuthorityAdmitted:
        """Return finite admission metadata only for a live closure registration."""

        registered = _registered_settlement_coordinator(self)
        if type(registered) is CodexRegistrationSettlementAuthorityBlocked:
            raise TypeError("settlement authority is invalid")
        return CodexRegistrationSettlementAuthorityAdmitted()

    def begin(
        self,
        value: object,
    ) -> CodexRegistrationTransactionBegin | CodexRegistrationSettlementAuthorityBlocked:
        """Delegate begin exactly once after closure-owned identity validation."""

        return _begin_with_settlement_authority(self, value)

    def execute(
        self,
        value: object,
    ) -> (
        CodexRegistrationNextReadyPhase
        | CodexRegistrationTerminal
        | CodexRegistrationTransactionBlocked
        | CodexRegistrationProofClaim
        | CodexRegistrationCompensationClaim
        | CodexRegistrationSettlementAuthorityBlocked
    ):
        """Delegate execute once and replace only exact terminal decision kinds."""

        return _execute_with_settlement_authority(self, value)

    def recovery(
        self,
        value: object,
    ) -> (
        CodexRegistrationTransactionBlocked
        | CodexRegistrationCompensationClaim
        | CodexRegistrationSettlementAuthorityBlocked
    ):
        """Delegate recovery once and claim only exact started-add recovery data."""

        return _recover_with_settlement_authority(self, value)

    def __repr__(self) -> str:
        metadata = self.metadata()
        return (
            "CodexRegistrationSettlementAuthority("
            f"status='{metadata.status}', operation_count={metadata.operation_count})"
        )


CodexRegistrationSettlementAdmission: TypeAlias = (
    CodexRegistrationSettlementAuthority | CodexRegistrationSettlementAuthorityBlocked
)
CodexRegistrationSettlementProofConsumption: TypeAlias = (
    CodexRegistrationProofRequired | CodexRegistrationSettlementClaimBlocked
)
CodexRegistrationSettlementCompensationConsumption: TypeAlias = (
    CodexRegistrationCompensationRequired
    | CodexRegistrationAddRecovery
    | CodexRegistrationSettlementClaimBlocked
)


_ForwardMetadataMethod: TypeAlias = Callable[
    [CodexRegistrationForwardCoordinator], CodexRegistrationForwardAdmitted
]
_ForwardBeginMethod: TypeAlias = Callable[
    [CodexRegistrationForwardCoordinator, object], CodexRegistrationTransactionBegin
]
_ForwardExecuteMethod: TypeAlias = Callable[
    [CodexRegistrationForwardCoordinator, object], CodexRegistrationTransactionComplete
]
_ForwardRecoveryMethod: TypeAlias = Callable[
    [CodexRegistrationForwardCoordinator, object], CodexRegistrationRecoveryView
]
_RegisteredCoordinator: TypeAlias = (
    CodexRegistrationForwardCoordinator | CodexRegistrationSettlementAuthorityBlocked
)
_SettlementPayload: TypeAlias = (
    CodexRegistrationProofRequired
    | CodexRegistrationCompensationRequired
    | CodexRegistrationAddRecovery
)
_SettlementAuthorityValidator: TypeAlias = Callable[
    [CodexRegistrationSettlementAuthority], _RegisteredCoordinator
]
_SettlementAdmissionFactory: TypeAlias = Callable[[object], CodexRegistrationSettlementAdmission]
_SettlementBegin: TypeAlias = Callable[
    [CodexRegistrationSettlementAuthority, object],
    CodexRegistrationTransactionBegin | CodexRegistrationSettlementAuthorityBlocked,
]
_SettlementExecute: TypeAlias = Callable[
    [CodexRegistrationSettlementAuthority, object],
    CodexRegistrationNextReadyPhase
    | CodexRegistrationTerminal
    | CodexRegistrationTransactionBlocked
    | CodexRegistrationProofClaim
    | CodexRegistrationCompensationClaim
    | CodexRegistrationSettlementAuthorityBlocked,
]
_SettlementRecovery: TypeAlias = Callable[
    [CodexRegistrationSettlementAuthority, object],
    CodexRegistrationTransactionBlocked
    | CodexRegistrationCompensationClaim
    | CodexRegistrationSettlementAuthorityBlocked,
]
_ProofClaimConsumer: TypeAlias = Callable[[object], CodexRegistrationSettlementProofConsumption]
_CompensationClaimConsumer: TypeAlias = Callable[[object], CodexRegistrationSettlementCompensationConsumption]


def _build_settlement_authority_system() -> tuple[
    _SettlementAdmissionFactory,
    _SettlementAuthorityValidator,
    _SettlementBegin,
    _SettlementExecute,
    _SettlementRecovery,
    _ProofClaimConsumer,
    _CompensationClaimConsumer,
]:
    """Keep all live wrapper/claim registration state inside this lexical closure."""

    class AuthorityRecord:
        """Weakly owner-bound exact forward coordinator, never a module attribute."""

        __slots__ = ("coordinator", "owner_reference")

        coordinator: CodexRegistrationForwardCoordinator
        owner_reference: ReferenceType[CodexRegistrationSettlementAuthority]

        def __init__(
            self,
            owner_reference: ReferenceType[CodexRegistrationSettlementAuthority],
            coordinator: CodexRegistrationForwardCoordinator,
        ) -> None:
            self.owner_reference = owner_reference
            self.coordinator = coordinator

    class ClaimBinding:
        """Canonical primitive fields isolated from public claim metadata."""

        __slots__ = ("attempt_value", "generation_number", "kind", "phase")

        attempt_value: str
        generation_number: int
        kind: CodexRegistrationSettlementClaimKind
        phase: CodexRegistrationPhase

        def __init__(
            self,
            attempt_value: str,
            phase: CodexRegistrationPhase,
            generation_number: int,
            kind: CodexRegistrationSettlementClaimKind,
        ) -> None:
            self.attempt_value = attempt_value
            self.phase = phase
            self.generation_number = generation_number
            self.kind = kind

    class ClaimRecord:
        """Weakly claim-bound one-shot data retained only until consume or collection."""

        __slots__ = ("binding", "claim_reference", "kind", "owner_reference", "payload")

        binding: ClaimBinding
        claim_reference: ReferenceType[_CodexRegistrationSettlementClaim]
        kind: CodexRegistrationSettlementClaimKind
        owner_reference: ReferenceType[CodexRegistrationSettlementAuthority]
        payload: _SettlementPayload

        def __init__(
            self,
            claim_reference: ReferenceType[_CodexRegistrationSettlementClaim],
            owner_reference: ReferenceType[CodexRegistrationSettlementAuthority],
            binding: ClaimBinding,
            kind: CodexRegistrationSettlementClaimKind,
            payload: _SettlementPayload,
        ) -> None:
            self.claim_reference = claim_reference
            self.owner_reference = owner_reference
            self.binding = binding
            self.kind = kind
            self.payload = payload

    registry_lock = RLock()
    authority_registry: dict[int, AuthorityRecord] = {}
    claim_registry: dict[int, ClaimRecord] = {}

    def blocked_authority() -> CodexRegistrationSettlementAuthorityBlocked:
        return CodexRegistrationSettlementAuthorityBlocked(
            reason=CodexRegistrationSettlementAuthorityRejectReason.INVALID_COORDINATOR
        )

    def blocked_claim() -> CodexRegistrationSettlementClaimBlocked:
        return CodexRegistrationSettlementClaimBlocked(
            reason=CodexRegistrationSettlementClaimBlockReason.INVALID_CLAIM
        )

    def canonical_claim_binding(
        metadata: CodexRegistrationSettlementClaimMetadata,
    ) -> ClaimBinding:
        if type(metadata) is not CodexRegistrationSettlementClaimMetadata:
            raise TypeError("settlement claim metadata is invalid")
        try:
            status_value: object = object.__getattribute__(metadata, "status")
            attempt_id_value: object = object.__getattribute__(metadata, "attempt_id")
            phase_value: object = object.__getattribute__(metadata, "phase")
            generation_value: object = object.__getattribute__(metadata, "generation")
            kind_value: object = object.__getattribute__(metadata, "kind")
        except AttributeError:
            raise TypeError("settlement claim metadata is invalid") from None
        if (
            type(status_value) is not str
            or type(attempt_id_value) is not CodexRegistrationAttemptId
            or type(phase_value) is not CodexRegistrationPhase
            or type(generation_value) is not CodexRegistrationGeneration
            or type(kind_value) is not CodexRegistrationSettlementClaimKind
            or status_value != "SETTLEMENT_CLAIM"
        ):
            raise TypeError("settlement claim metadata is invalid")
        attempt_id = attempt_id_value
        generation = generation_value
        try:
            attempt_value: object = object.__getattribute__(attempt_id, "value")
            generation_number: object = object.__getattribute__(generation, "value")
        except AttributeError:
            raise TypeError("settlement claim metadata is invalid") from None
        if (
            type(attempt_value) is not str
            or type(generation_number) is not int
            or generation_number < 1
        ):
            raise TypeError("settlement claim metadata is invalid")
        return ClaimBinding(attempt_value, phase_value, generation_number, kind_value)

    def live_metadata_matches_binding(
        value: object,
        binding: ClaimBinding,
        expected_kind: CodexRegistrationSettlementClaimKind,
    ) -> bool:
        if type(value) is not CodexRegistrationSettlementClaimMetadata:
            return False
        metadata = value
        try:
            status_value: object = object.__getattribute__(metadata, "status")
            attempt_id_value: object = object.__getattribute__(metadata, "attempt_id")
            phase_value: object = object.__getattribute__(metadata, "phase")
            generation_value: object = object.__getattribute__(metadata, "generation")
            kind_value: object = object.__getattribute__(metadata, "kind")
        except AttributeError:
            return False
        if (
            type(status_value) is not str
            or type(attempt_id_value) is not CodexRegistrationAttemptId
            or type(phase_value) is not CodexRegistrationPhase
            or type(generation_value) is not CodexRegistrationGeneration
            or type(kind_value) is not CodexRegistrationSettlementClaimKind
            or status_value != "SETTLEMENT_CLAIM"
            or phase_value is not binding.phase
            or kind_value is not expected_kind
            or kind_value is not binding.kind
        ):
            return False
        attempt_id = attempt_id_value
        generation = generation_value
        try:
            attempt_value: object = object.__getattribute__(attempt_id, "value")
            generation_number: object = object.__getattribute__(generation, "value")
        except AttributeError:
            return False
        if type(attempt_value) is not str or type(generation_number) is not int:
            return False
        return attempt_value == binding.attempt_value and generation_number == binding.generation_number

    def registered(
        owner: CodexRegistrationSettlementAuthority,
    ) -> _RegisteredCoordinator:
        if type(owner) is not CodexRegistrationSettlementAuthority:
            return blocked_authority()
        owner_identity = id(owner)
        with registry_lock:
            try:
                record = authority_registry[owner_identity]
            except KeyError:
                return blocked_authority()
            if record.owner_reference() is not owner:
                return blocked_authority()
            try:
                coordinator_value: object = object.__getattribute__(owner, "_coordinator")
            except AttributeError:
                return blocked_authority()
            if coordinator_value is not record.coordinator:
                return blocked_authority()
            return record.coordinator

    def remove_claims_for_owner(
        owner_reference: ReferenceType[CodexRegistrationSettlementAuthority],
    ) -> None:
        claim_identities = [
            claim_identity
            for claim_identity, record in claim_registry.items()
            if record.owner_reference is owner_reference
        ]
        for claim_identity in claim_identities:
            del claim_registry[claim_identity]

    def register(
        coordinator: CodexRegistrationForwardCoordinator,
    ) -> CodexRegistrationSettlementAuthority:
        owner = object.__new__(CodexRegistrationSettlementAuthority)
        object.__setattr__(owner, "_coordinator", coordinator)
        owner_identity = id(owner)

        def owner_collected(
            owner_reference: ReferenceType[CodexRegistrationSettlementAuthority],
        ) -> None:
            with registry_lock:
                try:
                    record = authority_registry[owner_identity]
                except KeyError:
                    return
                if record.owner_reference is owner_reference:
                    del authority_registry[owner_identity]
                    remove_claims_for_owner(owner_reference)

        owner_reference = ref(owner, owner_collected)
        with registry_lock:
            authority_registry[owner_identity] = AuthorityRecord(owner_reference, coordinator)
        return owner

    def admit(candidate: object) -> CodexRegistrationSettlementAdmission:
        if type(candidate) is not CodexRegistrationForwardCoordinator:
            return blocked_authority()
        metadata_member: object = CodexRegistrationForwardCoordinator.__dict__["metadata"]
        if type(metadata_member) is not FunctionType:
            return blocked_authority()
        metadata_method = cast(_ForwardMetadataMethod, metadata_member)
        try:
            metadata_value: object = metadata_method(candidate)
        except TypeError:
            return blocked_authority()
        if type(metadata_value) is not CodexRegistrationForwardAdmitted:
            return blocked_authority()
        metadata = metadata_value
        if (
            type(metadata.status) is not str
            or type(metadata.operation_count) is not int
            or metadata.status != "FORWARD_ADMITTED"
            or metadata.operation_count != 3
        ):
            return blocked_authority()
        return register(candidate)

    def forward_begin(
        coordinator: CodexRegistrationForwardCoordinator,
        value: object,
    ) -> CodexRegistrationTransactionBegin:
        member: object = CodexRegistrationForwardCoordinator.__dict__["begin"]
        if type(member) is not FunctionType:
            return CodexRegistrationTransactionBlocked(
                reason=CodexRegistrationTransactionBlockReason.INVALID_STATE
            )
        return cast(_ForwardBeginMethod, member)(coordinator, value)

    def forward_execute(
        coordinator: CodexRegistrationForwardCoordinator,
        value: object,
    ) -> CodexRegistrationTransactionComplete:
        member: object = CodexRegistrationForwardCoordinator.__dict__["execute"]
        if type(member) is not FunctionType:
            return CodexRegistrationTransactionBlocked(
                reason=CodexRegistrationTransactionBlockReason.INVALID_STATE
            )
        return cast(_ForwardExecuteMethod, member)(coordinator, value)

    def forward_recovery(
        coordinator: CodexRegistrationForwardCoordinator,
        value: object,
    ) -> CodexRegistrationRecoveryView:
        member: object = CodexRegistrationForwardCoordinator.__dict__["recovery"]
        if type(member) is not FunctionType:
            return CodexRegistrationTransactionBlocked(
                reason=CodexRegistrationTransactionBlockReason.INVALID_STATE
            )
        return cast(_ForwardRecoveryMethod, member)(coordinator, value)

    def issue_claim(
        owner: CodexRegistrationSettlementAuthority,
        metadata: CodexRegistrationSettlementClaimMetadata,
        kind: CodexRegistrationSettlementClaimKind,
        payload: _SettlementPayload,
    ) -> CodexRegistrationProofClaim | CodexRegistrationCompensationClaim:
        binding = canonical_claim_binding(metadata)
        if kind is CodexRegistrationSettlementClaimKind.PROOF:
            claim: _CodexRegistrationSettlementClaim = object.__new__(CodexRegistrationProofClaim)
        else:
            claim = object.__new__(CodexRegistrationCompensationClaim)
        object.__setattr__(claim, "_metadata", metadata)
        claim_identity = id(claim)
        owner_identity = id(owner)
        with registry_lock:
            try:
                authority_record = authority_registry[owner_identity]
            except KeyError:
                raise TypeError("settlement authority is invalid") from None
            owner_reference = authority_record.owner_reference
            if owner_reference() is not owner:
                raise TypeError("settlement authority is invalid")

            def claim_collected(
                claim_reference: ReferenceType[_CodexRegistrationSettlementClaim],
            ) -> None:
                with registry_lock:
                    try:
                        claim_record = claim_registry[claim_identity]
                    except KeyError:
                        return
                    if claim_record.claim_reference is claim_reference:
                        del claim_registry[claim_identity]

            claim_reference = ref(claim, claim_collected)
            claim_registry[claim_identity] = ClaimRecord(
                claim_reference,
                owner_reference,
                binding,
                kind,
                payload,
            )
        if type(claim) is CodexRegistrationProofClaim:
            return claim
        return cast(CodexRegistrationCompensationClaim, claim)

    def terminal_metadata(
        value: CodexRegistrationTerminal,
        kind: CodexRegistrationSettlementClaimKind,
    ) -> CodexRegistrationSettlementClaimMetadata:
        metadata_value: object = value.metadata
        return metadata_from_lease(metadata_value, kind)

    def metadata_from_lease(
        metadata_value: object,
        kind: CodexRegistrationSettlementClaimKind,
    ) -> CodexRegistrationSettlementClaimMetadata:
        if type(metadata_value) is not CodexRegistrationLeaseMetadata:
            raise TypeError("terminal metadata is invalid")
        metadata = metadata_value
        return CodexRegistrationSettlementClaimMetadata(
            attempt_id=metadata.attempt_id,
            phase=metadata.phase,
            generation=CodexRegistrationGeneration(value=metadata.generation.value),
            kind=kind,
        )

    def recovery_metadata(
        value: object,
        kind: CodexRegistrationSettlementClaimKind,
    ) -> CodexRegistrationSettlementClaimMetadata:
        if type(value) is not CodexRegistrationPhaseLease:
            raise TypeError("recovery lease is invalid")
        metadata_member: object = CodexRegistrationPhaseLease.__dict__["metadata"]
        if type(metadata_member) is not FunctionType:
            raise TypeError("recovery lease is invalid")
        metadata_value = cast(
            Callable[[CodexRegistrationPhaseLease], CodexRegistrationLeaseMetadata],
            metadata_member,
        )(value)
        return metadata_from_lease(metadata_value, kind)

    def execute(
        owner: CodexRegistrationSettlementAuthority,
        value: object,
    ) -> (
        CodexRegistrationNextReadyPhase
        | CodexRegistrationTerminal
        | CodexRegistrationTransactionBlocked
        | CodexRegistrationProofClaim
        | CodexRegistrationCompensationClaim
        | CodexRegistrationSettlementAuthorityBlocked
    ):
        coordinator = registered(owner)
        if type(coordinator) is CodexRegistrationSettlementAuthorityBlocked:
            return coordinator
        admitted_coordinator = cast(CodexRegistrationForwardCoordinator, coordinator)
        completed = forward_execute(admitted_coordinator, value)
        if type(completed) is not CodexRegistrationTerminal:
            return completed
        decision_value: object = completed.decision
        if type(decision_value) is CodexRegistrationProofRequired:
            metadata = terminal_metadata(completed, CodexRegistrationSettlementClaimKind.PROOF)
            proof_payload = _rebuild_proof_required(decision_value)
            return issue_claim(owner, metadata, CodexRegistrationSettlementClaimKind.PROOF, proof_payload)
        if type(decision_value) is CodexRegistrationCompensationRequired:
            metadata = terminal_metadata(completed, CodexRegistrationSettlementClaimKind.COMPENSATION)
            compensation_payload = _rebuild_compensation_required(decision_value)
            return issue_claim(
                owner,
                metadata,
                CodexRegistrationSettlementClaimKind.COMPENSATION,
                compensation_payload,
            )
        return completed

    def begin(
        owner: CodexRegistrationSettlementAuthority,
        value: object,
    ) -> CodexRegistrationTransactionBegin | CodexRegistrationSettlementAuthorityBlocked:
        coordinator = registered(owner)
        if type(coordinator) is CodexRegistrationSettlementAuthorityBlocked:
            return coordinator
        return forward_begin(cast(CodexRegistrationForwardCoordinator, coordinator), value)

    def recovery(
        owner: CodexRegistrationSettlementAuthority,
        value: object,
    ) -> (
        CodexRegistrationTransactionBlocked
        | CodexRegistrationCompensationClaim
        | CodexRegistrationSettlementAuthorityBlocked
    ):
        coordinator = registered(owner)
        if type(coordinator) is CodexRegistrationSettlementAuthorityBlocked:
            return coordinator
        recovered = forward_recovery(cast(CodexRegistrationForwardCoordinator, coordinator), value)
        if type(recovered) is not CodexRegistrationAddRecovery:
            return cast(CodexRegistrationTransactionBlocked, recovered)
        metadata = recovery_metadata(value, CodexRegistrationSettlementClaimKind.COMPENSATION)
        payload = _rebuild_add_recovery(recovered)
        issued = issue_claim(owner, metadata, CodexRegistrationSettlementClaimKind.COMPENSATION, payload)
        return cast(CodexRegistrationCompensationClaim, issued)

    def consume_proof(value: object) -> CodexRegistrationSettlementProofConsumption:
        payload = consume(value, CodexRegistrationSettlementClaimKind.PROOF)
        if type(payload) is CodexRegistrationSettlementClaimBlocked:
            return payload
        if type(payload) is not CodexRegistrationProofRequired:
            return blocked_claim()
        return _rebuild_proof_required(payload)

    def consume_compensation(value: object) -> CodexRegistrationSettlementCompensationConsumption:
        payload = consume(value, CodexRegistrationSettlementClaimKind.COMPENSATION)
        if type(payload) is CodexRegistrationSettlementClaimBlocked:
            return payload
        if type(payload) is CodexRegistrationCompensationRequired:
            return _rebuild_compensation_required(payload)
        if type(payload) is CodexRegistrationAddRecovery:
            return _rebuild_add_recovery(payload)
        return blocked_claim()

    def consume(
        value: object,
        expected_kind: CodexRegistrationSettlementClaimKind,
    ) -> _SettlementPayload | CodexRegistrationSettlementClaimBlocked:
        expected_type = (
            CodexRegistrationProofClaim
            if expected_kind is CodexRegistrationSettlementClaimKind.PROOF
            else CodexRegistrationCompensationClaim
        )
        if type(value) is not expected_type:
            return blocked_claim()
        claim = cast(_CodexRegistrationSettlementClaim, value)
        claim_identity = id(claim)
        with registry_lock:
            try:
                record = claim_registry[claim_identity]
            except KeyError:
                return blocked_claim()
            if (
                record.claim_reference() is not claim
                or record.owner_reference() is None
                or record.kind is not expected_kind
                or record.binding.kind is not expected_kind
            ):
                return blocked_claim()
            try:
                claim_metadata_value: object = object.__getattribute__(claim, "_metadata")
            except AttributeError:
                return blocked_claim()
            if not live_metadata_matches_binding(
                claim_metadata_value,
                record.binding,
                expected_kind,
            ):
                return blocked_claim()
            del claim_registry[claim_identity]
            return record.payload

    return admit, registered, begin, execute, recovery, consume_proof, consume_compensation


def _rebuild_claim_metadata(value: object) -> CodexRegistrationSettlementClaimMetadata:
    if type(value) is not CodexRegistrationSettlementClaimMetadata:
        raise TypeError("settlement claim metadata is invalid")
    metadata = value
    try:
        attempt_id_value: object = metadata.attempt_id
        phase_value: object = metadata.phase
        generation_value: object = metadata.generation
        kind_value: object = metadata.kind
    except AttributeError:
        raise TypeError("settlement claim metadata is invalid") from None
    if (
        type(attempt_id_value) is not CodexRegistrationAttemptId
        or type(phase_value) is not CodexRegistrationPhase
        or type(generation_value) is not CodexRegistrationGeneration
        or type(kind_value) is not CodexRegistrationSettlementClaimKind
    ):
        raise TypeError("settlement claim metadata is invalid")
    attempt_id = attempt_id_value
    generation = generation_value
    try:
        attempt_value: object = attempt_id.value
        generation_number: object = generation.value
    except AttributeError:
        raise TypeError("settlement claim metadata is invalid") from None
    if type(attempt_value) is not str or type(generation_number) is not int or generation_number < 1:
        raise TypeError("settlement claim metadata is invalid")
    return CodexRegistrationSettlementClaimMetadata(
        attempt_id=CodexRegistrationAttemptId(value=attempt_value),
        phase=phase_value,
        generation=CodexRegistrationGeneration(value=generation_number),
        kind=kind_value,
    )


def _rebuild_proof_required(value: CodexRegistrationProofRequired) -> CodexRegistrationProofRequired:
    return CodexRegistrationProofRequired.model_validate(value.model_dump())


def _rebuild_compensation_required(
    value: CodexRegistrationCompensationRequired,
) -> CodexRegistrationCompensationRequired:
    return CodexRegistrationCompensationRequired.model_validate(value.model_dump())


def _rebuild_add_recovery(value: CodexRegistrationAddRecovery) -> CodexRegistrationAddRecovery:
    return CodexRegistrationAddRecovery.model_validate(value.model_dump())


(
    admit_codex_registration_settlement_authority,
    _registered_settlement_coordinator,
    _begin_with_settlement_authority,
    _execute_with_settlement_authority,
    _recover_with_settlement_authority,
    consume_codex_registration_proof_claim,
    consume_codex_registration_compensation_claim,
) = _build_settlement_authority_system()
del _build_settlement_authority_system
