"""Real `RoleWakePort` over the owner-declared host wake command.

The payload never rides on a command line: it is written to one attempt-owned
file inside the Johnny root and the declared command receives that path. An
ambiguous outcome (timeout, or failure to observe the child at all) is
reported as `EFFECT_UNCERTAIN` and is never retried by this port.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from library.workflow_router.role_wake_contracts import (
    RoleWakeCommand,
    RoleWakeEffectResult,
    RoleWakeEffectStatus,
)

from .johnny_root_layout import JohnnyRootLayout
from .wake_capability import WakeCommandConfig

_PAYLOAD_DIRECTORY = "wake-payloads"


class CommandRoleWakePort:
    """Deliver exactly one wake through the proven host command."""

    def __init__(
        self,
        layout: JohnnyRootLayout,
        config: WakeCommandConfig,
    ) -> None:
        self._layout = layout
        self._config = config

    def _payload_path(self, attempt_id: str) -> Path:
        return self._layout.queue_root / _PAYLOAD_DIRECTORY / f"{attempt_id}.json"

    def wake(self, command: RoleWakeCommand) -> RoleWakeEffectResult:
        try:
            trusted = RoleWakeCommand.model_validate(command, strict=True)
        except Exception:
            return RoleWakeEffectResult(status=RoleWakeEffectStatus.NO_EFFECT)

        payload_path = self._payload_path(trusted.attempt_id)
        try:
            payload_path.parent.mkdir(parents=True, exist_ok=True)
            payload_path.write_text(trusted.payload, encoding="utf-8")
        except OSError:
            return RoleWakeEffectResult(status=RoleWakeEffectStatus.NO_EFFECT)

        rendered = self._config.rendered(payload_path, trusted.attempt_id)
        try:
            completed = subprocess.run(
                rendered,
                capture_output=True,
                shell=False,
                timeout=self._config.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            # The child started and may have delivered; ambiguity is terminal.
            return RoleWakeEffectResult(status=RoleWakeEffectStatus.EFFECT_UNCERTAIN)
        except (OSError, ValueError):
            # The command never started, so no effect can have reached the host.
            return RoleWakeEffectResult(status=RoleWakeEffectStatus.NO_EFFECT)
        if completed.returncode != 0:
            return RoleWakeEffectResult(status=RoleWakeEffectStatus.NO_EFFECT)
        return RoleWakeEffectResult(
            status=RoleWakeEffectStatus.HOST_ACCEPTED,
            delivery_reference=f"delivery-command-{trusted.attempt_id}",
        )


__all__ = ["CommandRoleWakePort"]
