"""Owner-declared wake capability: configuration, probe and honest degradation.

Automatic wake may be claimed only when the owner declares a host wake command
and that exact command passes its own probe. Anything else stays
`HOST_WAKE_CAPABILITY_UNAVAILABLE`, and the runner records a completion
candidate instead of pretending a reviewer was woken.
"""

from __future__ import annotations

import subprocess
from enum import Enum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .johnny_root_layout import JohnnyRootLayout

_CONFIG_FILE_NAME = "wake-capability.json"
_PAYLOAD_PLACEHOLDER = "{payload_file}"
_ATTEMPT_PLACEHOLDER = "{attempt_id}"
_PROBE_TIMEOUT_SECONDS = 30
_PROBE_PAYLOAD_NAME = "wake-capability-probe.json"
_PROBE_ATTEMPT_ID = "wake-attempt-capability-probe"
_PROBE_PAYLOAD_BODY = '{"probe":true,"note":"johnny wake capability probe"}'


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
    )


class WakeChannelKind(str, Enum):
    """The finite delivery channels; only HOST_COMMAND can wake automatically."""

    HOST_COMMAND = "HOST_COMMAND"
    CANDIDATE_INBOX = "CANDIDATE_INBOX"


class WakeCapabilityStatus(str, Enum):
    """Finite outcomes of one capability probe."""

    PROVEN = "PROVEN"
    UNAVAILABLE = "UNAVAILABLE"


class WakeCapabilityFailure(str, Enum):
    """Finite reasons a declared wake command cannot be claimed."""

    NOT_CONFIGURED = "NOT_CONFIGURED"
    CONFIG_INVALID = "CONFIG_INVALID"
    EXECUTABLE_UNAVAILABLE = "EXECUTABLE_UNAVAILABLE"
    PROBE_FAILED = "PROBE_FAILED"
    PROBE_TIMEOUT = "PROBE_TIMEOUT"


class WakeCommandConfig(_StrictModel):
    """One owner-declared host wake command.

    `command` is an argument vector, never a shell string: the runner executes
    it with `shell=False`. Exactly one argument must carry the payload-file
    placeholder so the wake payload never rides on a command line.
    """

    schema_version: int = Field(default=1, ge=1, le=1)
    command: tuple[str, ...] = Field(min_length=1)
    reviewer_ref: str = Field(pattern=r"^[a-z][a-z0-9-]{2,127}$")
    timeout_seconds: int = Field(default=120, ge=5, le=900)

    @model_validator(mode="after")
    def placeholders_are_exact(self) -> Self:
        payload_slots = [
            argument
            for argument in self.command
            if _PAYLOAD_PLACEHOLDER in argument
        ]
        if len(payload_slots) != 1:
            raise ValueError(
                "the wake command must carry exactly one payload-file placeholder"
            )
        return self

    def rendered(self, payload_file: Path, attempt_id: str) -> tuple[str, ...]:
        """Substitute the declared placeholders; no other expansion happens."""

        return tuple(
            argument.replace(_PAYLOAD_PLACEHOLDER, str(payload_file)).replace(
                _ATTEMPT_PLACEHOLDER, attempt_id
            )
            for argument in self.command
        )


class WakeCapabilityProbeResult(_StrictModel):
    """Exactly one proven configuration or exactly one finite failure."""

    status: WakeCapabilityStatus
    channel: WakeChannelKind
    failure: WakeCapabilityFailure | None = None
    config: WakeCommandConfig | None = None

    @model_validator(mode="after")
    def exact_probe_shape(self) -> Self:
        if self.status is WakeCapabilityStatus.PROVEN:
            if self.channel is not WakeChannelKind.HOST_COMMAND:
                raise ValueError("only a host command channel can be proven")
            if self.failure is not None or self.config is None:
                raise ValueError("a proven probe carries its config and no failure")
        else:
            if self.channel is not WakeChannelKind.CANDIDATE_INBOX:
                raise ValueError("an unavailable probe degrades to the inbox channel")
            if self.failure is None or self.config is not None:
                raise ValueError("an unavailable probe carries one failure only")
        return self


def wake_config_path(layout: JohnnyRootLayout) -> Path:
    """Where the owner declares the wake command inside the Johnny root."""

    return layout.base / _CONFIG_FILE_NAME


def _unavailable(failure: WakeCapabilityFailure) -> WakeCapabilityProbeResult:
    return WakeCapabilityProbeResult(
        status=WakeCapabilityStatus.UNAVAILABLE,
        channel=WakeChannelKind.CANDIDATE_INBOX,
        failure=failure,
    )


def probe_wake_capability(
    layout: JohnnyRootLayout, timeout_seconds: int = _PROBE_TIMEOUT_SECONDS
) -> WakeCapabilityProbeResult:
    """Prove the capability by running the declared wake command itself.

    A separate probe command would only prove that some unrelated process can
    exit zero, so `PROVEN` would not mean the reviewer can actually be woken.
    The probe therefore renders the exact wake command against a disposable
    probe payload and requires that exact invocation to succeed.
    """

    path = wake_config_path(layout)
    if not path.is_file():
        return _unavailable(WakeCapabilityFailure.NOT_CONFIGURED)
    try:
        config = WakeCommandConfig.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError, ValueError):
        return _unavailable(WakeCapabilityFailure.CONFIG_INVALID)

    probe_payload = layout.queue_root / _PROBE_PAYLOAD_NAME
    try:
        probe_payload.parent.mkdir(parents=True, exist_ok=True)
        probe_payload.write_text(_PROBE_PAYLOAD_BODY, encoding="utf-8")
    except OSError:
        return _unavailable(WakeCapabilityFailure.PROBE_FAILED)
    rendered = config.rendered(probe_payload, _PROBE_ATTEMPT_ID)
    try:
        completed = subprocess.run(
            rendered,
            capture_output=True,
            shell=False,
            timeout=min(timeout_seconds, config.timeout_seconds),
        )
    except subprocess.TimeoutExpired:
        return _unavailable(WakeCapabilityFailure.PROBE_TIMEOUT)
    except (OSError, ValueError):
        return _unavailable(WakeCapabilityFailure.EXECUTABLE_UNAVAILABLE)
    finally:
        try:
            probe_payload.unlink(missing_ok=True)
        except OSError:
            pass
    if completed.returncode != 0:
        return _unavailable(WakeCapabilityFailure.PROBE_FAILED)
    return WakeCapabilityProbeResult(
        status=WakeCapabilityStatus.PROVEN,
        channel=WakeChannelKind.HOST_COMMAND,
        config=config,
    )


__all__ = [
    "WakeCapabilityFailure",
    "WakeCapabilityProbeResult",
    "WakeCapabilityStatus",
    "WakeChannelKind",
    "WakeCommandConfig",
    "probe_wake_capability",
    "wake_config_path",
]
