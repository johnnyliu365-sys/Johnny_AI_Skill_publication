"""Post-install registration readback: prove the assembled runtime executes.

The proof is not file existence alone: the installed venv python runs the
installed runtime entry, which imports the live CLI out of the installed
payload and reports typed status. Any break in that chain fails the readback.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .johnny_root_layout import JohnnyRootLayout

_LAUNCHER_SCRIPT = "johnny-router.ps1"


class RealRegistrationReadbackPort:
    """Read back one installed runtime by executing its own entry chain."""

    def __init__(
        self,
        layout: JohnnyRootLayout,
        python_executable: Path | None = None,
        timeout_seconds: int = 120,
    ) -> None:
        self._layout = layout
        self._python = python_executable
        self._timeout = timeout_seconds

    def readback(self, attempt_id: str) -> bool:
        layout = self._layout
        python = self._python if self._python is not None else layout.venv_python
        required = (
            python,
            layout.runtime_entry,
            layout.launcher_root / _LAUNCHER_SCRIPT,
            layout.plugin_root / "payload-manifest.json",
        )
        if any(not path.is_file() for path in required):
            return False
        try:
            completed = subprocess.run(
                (str(python), str(layout.runtime_entry), "status"),
                capture_output=True,
                shell=False,
                timeout=self._timeout,
            )
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return False
        if completed.returncode != 0:
            return False
        try:
            lines = completed.stdout.decode("utf-8", errors="replace").splitlines()
            payload = json.loads(lines[-1]) if lines else None
        except ValueError:
            return False
        if type(payload) is not dict:
            return False
        return (
            payload.get("status") == "OK"
            and payload.get("venv_present") is True
            and payload.get("launcher_present") is True
        )


__all__ = ["RealRegistrationReadbackPort"]
