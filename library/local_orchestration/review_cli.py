"""The `review` family of the live CLI: the reviewer's way back.

One typed JSON line per path. Exit 0 when the verdict is on record (whether
this call wrote it or a previous identical one did), 2 on a typed refusal.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from .johnny_root_layout import JohnnyRootLayout
from .review_return import (
    ReviewReturnRequest,
    ReviewReturnStatus,
    read_returns,
    submit_review_return,
)
from .review_return_consumption import (
    ConsumptionStatus,
    consume_next_return,
    pending_returns,
)


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True))


def run_review_family(arguments: tuple[str, ...], johnny_root: Path) -> int:
    """Dispatch one `review` subcommand against the resolved Johnny root."""

    try:
        layout = JohnnyRootLayout(base=johnny_root.resolve())
    except (OSError, ValueError):
        _emit({"status": "BLOCKED", "code": "ROOT_UNAVAILABLE"})
        return 2

    subcommand = arguments[0] if arguments else ""
    if subcommand == "submit":
        if len(arguments) < 2:
            _emit({"status": "BLOCKED", "code": "VERDICT_FILE_REQUIRED"})
            return 2
        try:
            request = ReviewReturnRequest.model_validate_json(
                Path(arguments[1]).read_text(encoding="utf-8")
            )
        except (OSError, ValidationError, ValueError):
            _emit({"status": "BLOCKED", "code": "REQUEST_INVALID"})
            return 2
        status, failure = submit_review_return(layout, request)
        if status is ReviewReturnStatus.REFUSED:
            _emit(
                {
                    "status": "BLOCKED",
                    "code": failure.value if failure else "REFUSED",
                }
            )
            return 2
        _emit(
            {
                "status": status.value,
                "receipt_id": request.receipt_id,
                "verdict": request.verdict.value,
            }
        )
        return 0
    if subcommand == "consume":
        consumption, event, refusal = consume_next_return(layout)
        if consumption is ConsumptionStatus.NOTHING_PENDING:
            _emit({"status": consumption.value, "pending": 0})
            return 0
        if consumption is not ConsumptionStatus.EMITTED or event is None:
            _emit(
                {
                    "status": "BLOCKED",
                    "code": refusal.value if refusal else "REFUSED",
                    "pending": len(pending_returns(layout)),
                }
            )
            return 2
        # The marker is already durable at this point: the event has been
        # consumed whether or not the caller acts on this line.
        _emit(
            {
                "status": consumption.value,
                "event_id": event.event_id,
                "event_kind": event.kind.value,
            }
        )
        return 0
    if subcommand == "list":
        records = read_returns(layout)
        _emit(
            {
                "status": "OK",
                "returns": [
                    {
                        "receipt_id": record.receipt_id,
                        "handoff_id": record.handoff_id,
                        "reviewer_ref": record.reviewer_ref,
                        "verdict": record.verdict.value,
                    }
                    for record in records
                ],
            }
        )
        return 0
    _emit({"status": "BLOCKED", "code": "UNKNOWN_SUBCOMMAND"})
    return 2


__all__ = ["run_review_family"]
