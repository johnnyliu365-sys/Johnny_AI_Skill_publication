from __future__ import annotations

from .contracts import InstallationId
from .host_contracts import (
    AgentHostReceipt,
    AgentHostRemovalProof,
    HostCapabilityRequest,
    HostCommandResult,
    HostCommandStatus,
    HostEvidenceId,
    HostFailureCode,
    HostPortError,
    HostRemovalRequest,
)


class RecordedHostLifecycle:
    def __init__(self) -> None:
        self._registration: HostCapabilityRequest | None = None
        self._receipt: AgentHostReceipt | None = None
        self._last_proof: AgentHostRemovalProof | None = None
        self._failure: HostFailureCode | None = None
        self._calls: list[str] = []
        self.return_foreign_receipt = False
        self.mutation_count = 0
        self.unrelated_marker = "unrelated-effect"

    @property
    def call_order(self) -> tuple[str, ...]:
        return tuple(self._calls)

    @property
    def has_registration(self) -> bool:
        return self._registration is not None

    def fail_on(self, failure: HostFailureCode) -> None:
        self._failure = failure

    def detect(self, request: HostCapabilityRequest) -> HostCommandResult:
        self._calls.append("detect")
        failure = self._failure
        if failure is HostFailureCode.EXECUTABLE_UNAVAILABLE or failure is HostFailureCode.ACCESS_DENIED:
            self._failure = None
            raise HostPortError(failure)
        return _command(request, HostCommandStatus.DETECTED, "evidence-0000000000000001")

    def register(self, request: HostCapabilityRequest) -> HostCommandResult:
        self._calls.append("register")
        self._raise_if(HostFailureCode.REGISTER_FAILED)
        if self._registration is not None:
            raise HostPortError(HostFailureCode.FOREIGN_REGISTRATION)
        self._registration = request
        self._receipt = None
        self.mutation_count += 1
        return _command(request, HostCommandStatus.REGISTERED, "evidence-0000000000000002")

    def verify_registration(self, request: HostCapabilityRequest) -> HostCommandResult:
        self._calls.append("verify")
        self._raise_if(HostFailureCode.VERIFY_FAILED)
        if self._registration != request:
            raise HostPortError(HostFailureCode.VERIFY_FAILED)
        return _command(request, HostCommandStatus.VERIFIED, "evidence-0000000000000003")

    def issue_receipt(self, request: HostCapabilityRequest) -> AgentHostReceipt:
        self._calls.append("receipt")
        if self._registration != request:
            raise HostPortError(HostFailureCode.VERIFY_FAILED)
        receipt = AgentHostReceipt(
            installation_id=request.installation_id,
            host=request.host,
            registration_key=request.registration_key,
            evidence_id=HostEvidenceId(value="evidence-0000000000000004"),
        )
        self._receipt = receipt
        if self.return_foreign_receipt:
            return receipt.model_copy(
                update={"installation_id": InstallationId(value="installation-ffffffffffffffff")}
            )
        return receipt

    def unregister(self, request: HostRemovalRequest) -> AgentHostRemovalProof:
        self._calls.append("unregister")
        self._raise_if(HostFailureCode.REMOVAL_PROOF_FAILED)
        if self._registration is None:
            raise HostPortError(HostFailureCode.REMOVAL_PROOF_FAILED)
        if self._receipt != request.receipt:
            raise HostPortError(HostFailureCode.FOREIGN_REGISTRATION)
        proof = AgentHostRemovalProof(
            installation_id=request.installation_id,
            host=request.host,
            registration_key=request.registration_key,
            evidence_id=HostEvidenceId(value="evidence-0000000000000005"),
        )
        self._registration = None
        self._receipt = None
        self._last_proof = proof
        self.mutation_count += 1
        return proof

    def verify_absent(self, proof: AgentHostRemovalProof) -> HostCommandResult:
        self._calls.append("verify_absent")
        self._raise_if(HostFailureCode.REMOVAL_PROOF_FAILED)
        if self._registration is not None or self._last_proof != proof:
            raise HostPortError(HostFailureCode.REMOVAL_PROOF_FAILED)
        request = HostCapabilityRequest(
            installation_id=proof.installation_id,
            host=proof.host,
            registration_key=proof.registration_key,
        )
        return _command(request, HostCommandStatus.ABSENT, "evidence-0000000000000006")

    def seed_registration(self, request: HostCapabilityRequest) -> AgentHostReceipt:
        self.detect(request)
        self.register(request)
        self.verify_registration(request)
        return self.issue_receipt(request)

    def _raise_if(self, expected: HostFailureCode) -> None:
        if self._failure is expected:
            self._failure = None
            raise HostPortError(expected)


def _command(
    request: HostCapabilityRequest,
    status: HostCommandStatus,
    evidence: str,
) -> HostCommandResult:
    return HostCommandResult(
        installation_id=request.installation_id,
        host=request.host,
        registration_key=request.registration_key,
        status=status,
        evidence_id=HostEvidenceId(value=evidence),
    )
