"""Verify a subscription's receipt is already claimable; never mint authority.

`claim_role_wake_attempt` admits a wake only for a canonical `TicketReceipt`
that already exists in the durable checkpoint as `ACTIVE` with a matching
digest. The runner's sole capability here is to *verify* that this is true
before arming supervision: the subscription file is caller data, so any path
that turned it into approved durable state would let a fabricated receipt
satisfy its own wake claim.

No issuing function exists in this module or anywhere in the runtime payload.
Receipt issuance is a dispatch-authority effect owned by the control plane
(`LiveDispatchMetadataStore.register_artifact` + `issue_receipt` behind the
dispatch flow's own admission); qualifications that stand in for a dispatcher
exercise those store calls directly as test fixtures, exactly like the
established 05B-series tests.
"""

from __future__ import annotations

from enum import Enum
from typing import Protocol

from library.workflow_router.live_dispatch_contracts import (
    ReceiptLifecycle,
    ReceiptReadStatus,
    TicketReceipt,
    TicketReceiptReadRequest,
    TicketReceiptReadResult,
)


class ReceiptReadPort(Protocol):
    """The only durable-store capability verification needs: one read."""

    def read_receipt(
        self, request: TicketReceiptReadRequest
    ) -> TicketReceiptReadResult: ...


class ReceiptVerificationStatus(str, Enum):
    """Finite outcomes of one claimability verification."""

    CLAIMABLE = "CLAIMABLE"
    BLOCKED = "BLOCKED"


class ReceiptVerificationFailure(str, Enum):
    """Finite reasons a subscription's receipt is not claimable."""

    RECEIPT_NOT_FOUND = "RECEIPT_NOT_FOUND"
    RECEIPT_MISMATCH = "RECEIPT_MISMATCH"


def verify_receipt_claimable(
    boundary: ReceiptReadPort, receipt: TicketReceipt
) -> tuple[ReceiptVerificationStatus, ReceiptVerificationFailure | None]:
    """Prove the receipt is already the exact active canonical one, or refuse.

    This never writes. A runner whose receipt cannot be found has not been
    dispatched through an authorized path, and saying so is the correct
    fail-closed outcome.
    """

    read = boundary.read_receipt(
        TicketReceiptReadRequest(
            project_id=receipt.project_id,
            ticket_reference=receipt.ticket_reference,
            ticket_revision=receipt.ticket_revision,
        )
    )
    if read.status is not ReceiptReadStatus.FOUND or read.receipt is None:
        return (
            ReceiptVerificationStatus.BLOCKED,
            ReceiptVerificationFailure.RECEIPT_NOT_FOUND,
        )
    stored = read.receipt
    if (
        stored.receipt_id != receipt.receipt_id
        or stored.lifecycle is not ReceiptLifecycle.ACTIVE
        or stored != receipt
    ):
        return (
            ReceiptVerificationStatus.BLOCKED,
            ReceiptVerificationFailure.RECEIPT_MISMATCH,
        )
    return ReceiptVerificationStatus.CLAIMABLE, None


__all__ = [
    "ReceiptReadPort",
    "ReceiptVerificationFailure",
    "ReceiptVerificationStatus",
    "verify_receipt_claimable",
]
