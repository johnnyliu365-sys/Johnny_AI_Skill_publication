"""The `dispatch` family of the live CLI: grant and issue.

Each path prints exactly one typed JSON line. Exit 0 on success, 2 on a
typed refusal — the same convention as the runner family.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from .dispatch_authority import (
    DispatchAdmissionRequest,
    DispatchAdmissionStatus,
    DispatchGrantStatus,
    admit_dispatch,
    create_dispatch_grant,
)
from .johnny_root_layout import JohnnyRootLayout


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True))


def run_dispatch_family(arguments: tuple[str, ...], johnny_root: Path) -> int:
    """Dispatch one `dispatch` subcommand against the resolved Johnny root."""

    try:
        layout = JohnnyRootLayout(base=johnny_root.resolve())
    except (OSError, ValueError):
        _emit({"status": "BLOCKED", "code": "ROOT_UNAVAILABLE"})
        return 2
    subcommand = arguments[0] if arguments else ""
    if subcommand == "grant":
        status, grant = create_dispatch_grant(layout)
        if status is DispatchGrantStatus.REFUSED or grant is None:
            _emit({"status": "BLOCKED", "code": "GRANT_UNWRITABLE"})
            return 2
        _emit({"status": status.value, "grant_id": grant.grant_id})
        return 0
    if subcommand == "issue":
        if len(arguments) < 2:
            _emit({"status": "BLOCKED", "code": "REQUEST_FILE_REQUIRED"})
            return 2
        request_path = Path(arguments[1])
        try:
            request = DispatchAdmissionRequest.model_validate_json(
                request_path.read_text(encoding="utf-8")
            )
        except (OSError, ValidationError, ValueError):
            _emit({"status": "BLOCKED", "code": "REQUEST_INVALID"})
            return 2
        result = admit_dispatch(layout, request)
        if result.status is not DispatchAdmissionStatus.DISPATCHED or result.receipt is None:
            _emit(
                {
                    "status": "BLOCKED",
                    "code": result.failure.value if result.failure else "REFUSED",
                }
            )
            return 2
        _emit(
            {
                "status": "DISPATCHED",
                "receipt_id": result.receipt.receipt_id,
                "ticket_reference": result.receipt.ticket_reference,
            }
        )
        return 0
    _emit({"status": "BLOCKED", "code": "UNKNOWN_SUBCOMMAND"})
    return 2


__all__ = ["run_dispatch_family"]
