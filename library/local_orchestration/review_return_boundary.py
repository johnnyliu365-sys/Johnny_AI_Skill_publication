"""The review-return surface: two reads, and nothing that can write.

The third facade in the authority split. The wake side may read, claim and
settle; the dispatch side may register, issue and read; the return side may
only *read* — a reviewer proving it was asked to review must not be able to
issue a receipt, claim a wake, or settle one. Capability held is capability
used, per facade.

Within one Python process any code can still import and construct the full
boundary; that residual is inherent to the single-process architecture and is
closed only by the workstation process boundary. What this buys is that no
write-capable object flows through the return composition.
"""

from __future__ import annotations

from pathlib import Path

from library.workflow_router.live_dispatch_contracts import (
    TicketReceiptReadRequest,
    TicketReceiptReadResult,
)
from library.workflow_router.role_wake_contracts import (
    RoleWakeAttemptReadRequest,
    RoleWakeAttemptReadResult,
)

from .live_dispatch_metadata_boundary import (
    JohnnyMetadataRoot,
    LiveDispatchMetadataBoundary,
)


class ReviewReturnScopedDispatchBoundary:
    """Exactly the two reads a returning reviewer needs."""

    def __init__(self, metadata_root: Path) -> None:
        self.__full_boundary = LiveDispatchMetadataBoundary(
            JohnnyMetadataRoot(metadata_root.resolve(strict=True))
        )

    def read_receipt(
        self, request: TicketReceiptReadRequest
    ) -> TicketReceiptReadResult:
        return self.__full_boundary.read_receipt(request)

    def read_role_wake_attempt(
        self, request: RoleWakeAttemptReadRequest
    ) -> RoleWakeAttemptReadResult:
        return self.__full_boundary.read_role_wake_attempt(request)


__all__ = ["ReviewReturnScopedDispatchBoundary"]
