"""The issuance-scoped durable-store surface: register, issue, read.

The mirror of `WakeScopedDispatchBoundary`, for the other side of the
authority split. Dispatch admission must not hold an object whose type
carries wake-attempt methods, exactly as the runner must not hold one whose
type carries issuance methods: capability held is capability used, per
facade. Within one Python process any code can still import and construct
the full boundary — that residual is inherent to the single-process
architecture and is closed only by the workstation process boundary — but
no wake-capable object flows through the dispatch composition, and no
issuance-capable object flows through the runner's.
"""

from __future__ import annotations

from pathlib import Path

from library.workflow_router.live_dispatch_contracts import (
    ApprovedDispatchArtifactRegisterRequest,
    ApprovedDispatchArtifactRegisterResult,
    TicketReceiptIssueRequest,
    TicketReceiptIssueResult,
    TicketReceiptReadRequest,
    TicketReceiptReadResult,
)

from .live_dispatch_metadata_boundary import (
    JohnnyMetadataRoot,
    LiveDispatchMetadataBoundary,
)


class IssuanceScopedDispatchBoundary:
    """Exactly the surface dispatch admission may hold; no wake method exists here."""

    def __init__(self, metadata_root: Path) -> None:
        self.__full_boundary = LiveDispatchMetadataBoundary(
            JohnnyMetadataRoot(metadata_root.resolve(strict=True))
        )

    def register_artifact(
        self, request: ApprovedDispatchArtifactRegisterRequest
    ) -> ApprovedDispatchArtifactRegisterResult:
        return self.__full_boundary.register_artifact(request)

    def issue_receipt(
        self, request: TicketReceiptIssueRequest
    ) -> TicketReceiptIssueResult:
        return self.__full_boundary.issue_receipt(request)

    def read_receipt(
        self, request: TicketReceiptReadRequest
    ) -> TicketReceiptReadResult:
        return self.__full_boundary.read_receipt(request)


__all__ = ["IssuanceScopedDispatchBoundary"]
