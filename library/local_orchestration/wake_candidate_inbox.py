"""Durable completion-candidate inbox used when no wake capability is proven.

Recording a candidate is not a wake. This port therefore always reports
`NO_EFFECT`: the reviewer was never invoked, and the caller keeps the typed
`HOST_WAKE_CAPABILITY_UNAVAILABLE` posture while the candidate survives for
the owner to forward manually.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from library.workflow_router.role_wake_contracts import (
    RoleWakeCommand,
    RoleWakeEffectResult,
    RoleWakeEffectStatus,
)

from .johnny_root_layout import JohnnyRootLayout

_INBOX_FILE_NAME = "wake-candidates.jsonl"


class WakeCandidateRecord(BaseModel):
    """One recorded completion candidate; identifiers and digests only."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
    )

    schema_version: int = Field(default=1, ge=1, le=1)
    attempt_id: str = Field(min_length=1, max_length=256)
    reviewer_task_id: str = Field(min_length=1, max_length=256)
    payload_digest: str = Field(pattern=r"^sha256_[0-9a-f]{64}$")
    payload_path: str = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def identifiers_carry_no_content(self) -> Self:
        if any(
            character in self.attempt_id or character in self.reviewer_task_id
            for character in ("\n", "\r")
        ):
            raise ValueError("identifiers must not carry line breaks")
        return self


def candidate_inbox_path(layout: JohnnyRootLayout) -> Path:
    return layout.queue_root / _INBOX_FILE_NAME


def read_candidates(layout: JohnnyRootLayout) -> tuple[WakeCandidateRecord, ...]:
    """Read every recorded candidate; an unreadable line invalidates the read."""

    path = candidate_inbox_path(layout)
    if not path.is_file():
        return ()
    records: list[WakeCandidateRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        records.append(WakeCandidateRecord.model_validate_json(stripped))
    return tuple(records)


class WakeCandidateInboxPort:
    """Record one deduplicated candidate per attempt; never claim a wake."""

    def __init__(self, layout: JohnnyRootLayout) -> None:
        self._layout = layout

    def _recorded_attempts(self) -> set[str] | None:
        try:
            return {record.attempt_id for record in read_candidates(self._layout)}
        except (OSError, ValidationError, ValueError):
            return None

    def wake(self, command: RoleWakeCommand) -> RoleWakeEffectResult:
        try:
            trusted = RoleWakeCommand.model_validate(command, strict=True)
        except Exception:
            return RoleWakeEffectResult(status=RoleWakeEffectStatus.NO_EFFECT)

        recorded = self._recorded_attempts()
        if recorded is None:
            return RoleWakeEffectResult(status=RoleWakeEffectStatus.NO_EFFECT)
        payload_path = (
            self._layout.queue_root / "wake-payloads" / f"{trusted.attempt_id}.json"
        )
        if trusted.attempt_id in recorded:
            # Already recorded; recording again would double-count one handoff.
            return RoleWakeEffectResult(status=RoleWakeEffectStatus.NO_EFFECT)
        record = WakeCandidateRecord(
            attempt_id=trusted.attempt_id,
            reviewer_task_id=trusted.reviewer_task_id,
            payload_digest=trusted.payload_digest,
            payload_path=str(payload_path),
        )
        try:
            payload_path.parent.mkdir(parents=True, exist_ok=True)
            payload_path.write_text(trusted.payload, encoding="utf-8")
            inbox = candidate_inbox_path(self._layout)
            with inbox.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(record.model_dump_json() + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            return RoleWakeEffectResult(status=RoleWakeEffectStatus.NO_EFFECT)
        # A recorded candidate is explicitly not a wake.
        return RoleWakeEffectResult(status=RoleWakeEffectStatus.NO_EFFECT)


__all__ = [
    "WakeCandidateInboxPort",
    "WakeCandidateRecord",
    "candidate_inbox_path",
    "read_candidates",
]
