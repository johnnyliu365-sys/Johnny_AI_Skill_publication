"""The wake-scoped durable-store surface: read, claim, settle — nothing else.

The event runner must not hold an object whose type carries issuance methods,
even unused ones. This facade owns the full boundary privately and exposes
exactly the three operations supervision needs. Within one Python process any
code can still import and construct the full boundary — that residual is
inherent to the single-process architecture and is closed only by the
workstation process boundary — but no issuance-capable object flows through
the runner composition.
"""

from __future__ import annotations

from pathlib import Path

from library.workflow_router.live_dispatch_contracts import (
    TicketReceiptReadRequest,
    TicketReceiptReadResult,
)
from library.workflow_router.role_wake_contracts import (
    RoleWakeAttemptClaimRequest,
    RoleWakeAttemptClaimResult,
    RoleWakeAttemptSettleRequest,
    RoleWakeAttemptSettleResult,
)

from .live_dispatch_metadata_boundary import (
    JohnnyMetadataRoot,
    LiveDispatchMetadataBoundary,
)


class WakeScopedDispatchBoundary:
    """Exactly the surface a runner may hold; no issuance method exists here."""

    def __init__(self, metadata_root: Path) -> None:
        self.__full_boundary = LiveDispatchMetadataBoundary(
            JohnnyMetadataRoot(metadata_root.resolve(strict=True))
        )

    def read_receipt(
        self, request: TicketReceiptReadRequest
    ) -> TicketReceiptReadResult:
        return self.__full_boundary.read_receipt(request)

    def claim_role_wake_attempt(
        self, request: RoleWakeAttemptClaimRequest
    ) -> RoleWakeAttemptClaimResult:
        return self.__full_boundary.claim_role_wake_attempt(request)

    def settle_role_wake_attempt(
        self, request: RoleWakeAttemptSettleRequest
    ) -> RoleWakeAttemptSettleResult:
        return self.__full_boundary.settle_role_wake_attempt(request)


__all__ = ["WakeScopedDispatchBoundary"]
