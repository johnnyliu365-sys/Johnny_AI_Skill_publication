"""Venv effect port that verifies the bootstrap-created environment.

The live install chain must create the venv before typed code can run
(pydantic lives inside it), so the transaction's venv step verifies that
exact environment instead of creating it: interpreter present, imports
prove, and `pip freeze` matches every approved pin. Removal is the real
receipt-bound deletion shared with the from-scratch port.
"""

from __future__ import annotations

import subprocess

from .johnny_root_layout import JohnnyRootLayout
from .plugin_install_transaction import (
    InstallDependencyPlan,
    InstallEffectOutcome,
    InstallEffectOutcomeStatus,
)
from .venv_effect_port import RealVenvEffectPort

_VENV_RECEIPT = "venv"
_IMPORT_PROOF = "import pydantic, pydantic_core"


def _canonical(name: str) -> str:
    return name.replace("-", "_").lower()


class VerifyingVenvPort:
    """Prove the pre-created control venv matches the approved plan exactly."""

    def __init__(
        self, layout: JohnnyRootLayout, timeout_seconds: int = 120
    ) -> None:
        self._layout = layout
        self._timeout = timeout_seconds
        self._remover = RealVenvEffectPort(layout)

    def _run(self, command: tuple[str, ...]) -> tuple[int, str] | None:
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                shell=False,
                timeout=self._timeout,
            )
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return None
        return completed.returncode, completed.stdout.decode(
            "utf-8", errors="replace"
        )

    def create(
        self, attempt_id: str, plan: InstallDependencyPlan
    ) -> InstallEffectOutcome:
        python = self._layout.venv_python
        if not python.is_file():
            return InstallEffectOutcome(
                status=InstallEffectOutcomeStatus.UNAVAILABLE
            )
        proof = self._run((str(python), "-c", _IMPORT_PROOF))
        if proof is None or proof[0] != 0:
            return InstallEffectOutcome(
                status=InstallEffectOutcomeStatus.UNAVAILABLE
            )
        frozen = self._run((str(python), "-m", "pip", "freeze", "--all"))
        if frozen is None or frozen[0] != 0:
            return InstallEffectOutcome(
                status=InstallEffectOutcomeStatus.UNAVAILABLE
            )
        installed = {
            _canonical(line.split("==")[0]): line.split("==")[1].strip()
            for line in frozen[1].splitlines()
            if "==" in line
        }
        for entry in plan.entries:
            if installed.get(_canonical(entry.name)) != entry.version:
                # The environment does not match the approved pin set; treat
                # it as a supply-chain mismatch rather than mere absence.
                return InstallEffectOutcome(
                    status=InstallEffectOutcomeStatus.HASH_MISMATCH
                )
        return InstallEffectOutcome(
            status=InstallEffectOutcomeStatus.COMPLETED, receipt=_VENV_RECEIPT
        )

    def remove(self, receipt: str) -> bool:
        return self._remover.remove(receipt)


__all__ = ["VerifyingVenvPort"]
