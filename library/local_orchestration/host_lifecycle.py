from __future__ import annotations

from typing import Protocol
from pydantic import ValidationError

from .host_contracts import (
    AgentHost,
    AgentHostReceipt,
    AgentHostRemovalProof,
    HostBlockReason,
    HostCapabilityBlocked,
    HostCapabilityReport,
    HostCapabilityRequest,
    HostCapabilitySupported,
    HostCapabilityUnverified,
    HostCommandResult,
    HostCommandStatus,
    HostFailureCode,
    HostPortError,
    HostRemovalBlocked,
    HostRemovalRequest,
    HostRemovalResult,
    HostRemovalSucceeded,
)


class RecordedHostLifecyclePort(Protocol):
    def detect(self, request: HostCapabilityRequest) -> HostCommandResult: ...

    def register(self, request: HostCapabilityRequest) -> HostCommandResult: ...

    def verify_registration(self, request: HostCapabilityRequest) -> HostCommandResult: ...

    def issue_receipt(self, request: HostCapabilityRequest) -> AgentHostReceipt: ...

    def unregister(self, request: HostRemovalRequest) -> AgentHostRemovalProof: ...

    def verify_absent(self, proof: AgentHostRemovalProof) -> HostCommandResult: ...


FAILURE_REASONS: dict[HostFailureCode, HostBlockReason] = {
    HostFailureCode.EXECUTABLE_UNAVAILABLE: HostBlockReason.EXECUTABLE_UNAVAILABLE,
    HostFailureCode.ACCESS_DENIED: HostBlockReason.ACCESS_DENIED,
    HostFailureCode.REGISTER_FAILED: HostBlockReason.REGISTER_FAILED,
    HostFailureCode.VERIFY_FAILED: HostBlockReason.VERIFY_FAILED,
    HostFailureCode.REMOVAL_PROOF_FAILED: HostBlockReason.REMOVAL_PROOF_FAILED,
    HostFailureCode.FOREIGN_REGISTRATION: HostBlockReason.FOREIGN_REGISTRATION,
}


class ReversibleHostCapabilityGate:
    def __init__(self, lifecycle: RecordedHostLifecyclePort) -> None:
        self._lifecycle = lifecycle

    def public_capability(self, host: AgentHost) -> HostCapabilityReport:
        if host in (AgentHost.CODEX, AgentHost.CLAUDE):
            return HostCapabilityUnverified(host=host)
        return HostCapabilityBlocked(host=host, reason=HostBlockReason.UNVERIFIED_HOST)

    def verify_recorded(self, request: HostCapabilityRequest) -> HostCapabilityReport:
        try:
            request = HostCapabilityRequest.model_validate_json(request.model_dump_json())
        except ValidationError:
            return HostCapabilityBlocked(host=AgentHost.RECORDED, reason=HostBlockReason.UNVERIFIED_HOST)
        try:
            commands = (
                (self._lifecycle.detect(request), HostCommandStatus.DETECTED),
                (self._lifecycle.register(request), HostCommandStatus.REGISTERED),
                (self._lifecycle.verify_registration(request), HostCommandStatus.VERIFIED),
            )
            for command, expected in commands:
                if not _command_matches(command, request, expected):
                    return HostCapabilityBlocked(
                        host=request.host, reason=HostBlockReason.COMMAND_RESULT_MISMATCH
                    )
            receipt = self._lifecycle.issue_receipt(request)
            if not _receipt_matches(receipt, request):
                return HostCapabilityBlocked(
                    host=request.host, reason=HostBlockReason.RECEIPT_MISMATCH
                )
            removal = self.remove(HostRemovalRequest.from_receipt(receipt))
            if isinstance(removal, HostRemovalBlocked):
                return HostCapabilityBlocked(host=request.host, reason=removal.reason)
            return HostCapabilitySupported(
                host=request.host, receipt=receipt, removal_proof=removal.proof
            )
        except HostPortError as error:
            return HostCapabilityBlocked(host=request.host, reason=FAILURE_REASONS[error.code])

    def remove(self, request: HostRemovalRequest) -> HostRemovalResult:
        try:
            request = HostRemovalRequest.model_validate_json(request.model_dump_json())
        except ValidationError:
            return HostRemovalBlocked(reason=HostBlockReason.FOREIGN_REGISTRATION)
        try:
            proof = self._lifecycle.unregister(request)
            try:
                proof = AgentHostRemovalProof.model_validate_json(proof.model_dump_json())
            except ValidationError:
                return HostRemovalBlocked(reason=HostBlockReason.REMOVAL_PROOF_MISMATCH)
            if not _proof_matches(proof, request):
                return HostRemovalBlocked(reason=HostBlockReason.REMOVAL_PROOF_MISMATCH)
            absent = self._lifecycle.verify_absent(proof)
            capability = HostCapabilityRequest(
                installation_id=request.installation_id,
                host=request.host,
                registration_key=request.registration_key,
            )
            if not _command_matches(absent, capability, HostCommandStatus.ABSENT):
                return HostRemovalBlocked(reason=HostBlockReason.REMOVAL_PROOF_MISMATCH)
            return HostRemovalSucceeded(proof=proof)
        except HostPortError as error:
            return HostRemovalBlocked(reason=FAILURE_REASONS[error.code])


def _command_matches(
    command: HostCommandResult,
    request: HostCapabilityRequest,
    expected: HostCommandStatus,
) -> bool:
    return (
        command.installation_id == request.installation_id
        and command.host == request.host
        and command.registration_key == request.registration_key
        and command.status is expected
    )


def _receipt_matches(receipt: AgentHostReceipt, request: HostCapabilityRequest) -> bool:
    return (
        receipt.installation_id == request.installation_id
        and receipt.host == request.host
        and receipt.registration_key == request.registration_key
    )


def _proof_matches(proof: AgentHostRemovalProof, request: HostRemovalRequest) -> bool:
    return (
        proof.installation_id == request.installation_id
        and proof.host == request.host
        and proof.registration_key == request.registration_key
    )
