"""One exact proof-claim settlement through an already admitted registration port."""

from __future__ import annotations

from typing import TypeAlias

from .codex_registration_contracts import (
    CodexRegistrationReceipt,
    CodexRegistrationRejected,
    CodexRegistrationRejectReason,
    issue_registration_receipt,
)
from .codex_registration_port import (
    CodexRegistrationPortCapability,
    admit_codex_registration_port,
)
from .codex_registration_reducer import CodexRegistrationProofRequired
from .codex_registration_settlement_authority import (
    CodexRegistrationSettlementClaimBlocked,
    consume_codex_registration_proof_claim,
)


CodexRegistrationProofSettlement: TypeAlias = (
    CodexRegistrationReceipt
    | CodexRegistrationRejected
    | CodexRegistrationSettlementClaimBlocked
)


def settle_codex_registration_proof(
    claim: object,
    port_candidate: object,
) -> CodexRegistrationProofSettlement:
    """Consume one live proof claim only after static port admission succeeds."""

    admitted = admit_codex_registration_port(port_candidate)
    if type(admitted) is not CodexRegistrationPortCapability:
        return CodexRegistrationRejected(reason=CodexRegistrationRejectReason.INVALID_PROOF_PORT)
    consumed = consume_codex_registration_proof_claim(claim)
    if isinstance(consumed, CodexRegistrationSettlementClaimBlocked):
        return consumed
    return issue_registration_receipt(consumed.proof_request, admitted)
