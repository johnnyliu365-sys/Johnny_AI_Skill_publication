"""Real control-plane venv effect port with locked-hash wheel installation.

Every subprocess runs shell-free with a finite timeout; every failure maps to
the finite Ticket 11 outcome set. The port only ever touches the venv root
derived from the injected layout.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

from .johnny_root_layout import JohnnyRootLayout
from .plugin_install_transaction import (
    InstallDependencyPlan,
    InstallEffectOutcome,
    InstallEffectOutcomeStatus,
)

_VENV_RECEIPT = "venv"
_HASH_MISMATCH_MARKER = "do not match the hashes"
_DEFAULT_BOOTSTRAP_COMMAND: tuple[str, ...] = ("py", "-3.11")
_IMPORT_PROOF = "import pydantic, pydantic_core"


def render_locked_requirements(plan: InstallDependencyPlan) -> str:
    """Render the exact hash-locked requirements text; nothing else installs."""

    lines = [
        "# Generated from the approved runtime dependency lock; do not edit.",
    ]
    for entry in sorted(plan.entries, key=lambda item: item.name):
        hashes = " ".join(
            f"--hash=sha256:{digest}" for digest in entry.artifact_sha256s
        )
        lines.append(f"{entry.name}=={entry.version} {hashes}")
    return "\n".join(lines) + "\n"


def _unavailable() -> InstallEffectOutcome:
    return InstallEffectOutcome(status=InstallEffectOutcomeStatus.UNAVAILABLE)


def _clear_read_only(function: object, path: str, excinfo: object) -> None:
    os.chmod(path, stat.S_IWRITE)
    if os.path.isfile(path):
        os.unlink(path)
    else:
        os.rmdir(path)


class RealVenvEffectPort:
    """Create and remove exactly one Johnny-owned control-plane environment."""

    def __init__(
        self,
        layout: JohnnyRootLayout,
        bootstrap_command: tuple[str, ...] = _DEFAULT_BOOTSTRAP_COMMAND,
        create_timeout_seconds: int = 300,
        install_timeout_seconds: int = 900,
    ) -> None:
        self._layout = layout
        self._bootstrap_command = bootstrap_command
        self._create_timeout = create_timeout_seconds
        self._install_timeout = install_timeout_seconds

    def _run(
        self, command: tuple[str, ...], timeout_seconds: int
    ) -> tuple[int, str] | None:
        """Run one shell-free child; None means it never produced a result."""

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                shell=False,
                timeout=timeout_seconds,
            )
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return None
        output = (completed.stdout + completed.stderr).decode(
            "utf-8", errors="replace"
        )
        return completed.returncode, output

    def create(
        self, attempt_id: str, plan: InstallDependencyPlan
    ) -> InstallEffectOutcome:
        venv_root = self._layout.venv_root
        if venv_root.exists() and any(venv_root.iterdir()):
            # A populated location is never clobbered; ownership is unproven.
            return _unavailable()

        created = self._run(
            (*self._bootstrap_command, "-m", "venv", str(venv_root)),
            self._create_timeout,
        )
        if created is None or created[0] != 0:
            self._best_effort_delete(venv_root)
            return _unavailable()
        venv_python = self._layout.venv_python
        if not venv_python.is_file():
            self._best_effort_delete(venv_root)
            return _unavailable()

        requirements_path = venv_root / "locked-requirements.txt"
        try:
            requirements_path.write_text(
                render_locked_requirements(plan), encoding="utf-8"
            )
        except OSError:
            self._best_effort_delete(venv_root)
            return _unavailable()

        installed = self._run(
            (
                str(venv_python),
                "-m",
                "pip",
                "install",
                "--require-hashes",
                "--only-binary",
                ":all:",
                "--no-deps",
                "--disable-pip-version-check",
                "-r",
                str(requirements_path),
            ),
            self._install_timeout,
        )
        if installed is None:
            self._best_effort_delete(venv_root)
            return _unavailable()
        if installed[0] != 0:
            mismatch = _HASH_MISMATCH_MARKER in installed[1].lower()
            self._best_effort_delete(venv_root)
            if mismatch:
                return InstallEffectOutcome(
                    status=InstallEffectOutcomeStatus.HASH_MISMATCH
                )
            return _unavailable()

        proof = self._run(
            (str(venv_python), "-c", _IMPORT_PROOF), self._create_timeout
        )
        if proof is None or proof[0] != 0:
            self._best_effort_delete(venv_root)
            return _unavailable()

        return InstallEffectOutcome(
            status=InstallEffectOutcomeStatus.COMPLETED, receipt=_VENV_RECEIPT
        )

    def remove(self, receipt: str) -> bool:
        if receipt != _VENV_RECEIPT:
            return False
        venv_root = self._layout.venv_root
        if not venv_root.exists():
            return True
        try:
            shutil.rmtree(venv_root, onerror=_clear_read_only)
        except OSError:
            return False
        return not venv_root.exists()

    @staticmethod
    def _best_effort_delete(venv_root: Path) -> None:
        try:
            if venv_root.exists():
                shutil.rmtree(venv_root, onerror=_clear_read_only)
        except OSError:
            pass


__all__ = ["RealVenvEffectPort", "render_locked_requirements"]
