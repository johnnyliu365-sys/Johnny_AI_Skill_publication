"""Per-user Johnny root layout and durable install bookkeeping stores.

Every path derives from one base directory so a disposable override
(`JOHNNY_ROOT`) relocates the entire runtime for qualification, and the
canonical per-user location is used only when no override exists.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from .plugin_install_transaction import (
    InstallEffectRecord,
    InstallJournalOpenResult,
    InstallJournalOpenStatus,
)
from .plugin_uninstall_transaction import (
    PluginUninstallLedger,
    UninstallLedgerReadResult,
    UninstallLedgerReadStatus,
)

_ENVIRONMENT_KEY = "JOHNNY_ROOT"
_DEFAULT_DIRECTORY_NAME = "JohnnyRouter"
_JOURNAL_FILE_NAME = "install-journal.jsonl"
_LEDGER_FILE_NAME = "ledger.json"

_OWNED_DIRECTORY_NAMES: tuple[str, ...] = (
    "plugin",
    "venv",
    "launcher",
    "queue",
    "telemetry",
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
        arbitrary_types_allowed=True,
    )


class JohnnyRootLayout(_StrictModel):
    """One absolute per-user root; every owned path is derived, never configured."""

    base: Path

    @model_validator(mode="after")
    def base_is_absolute(self) -> Self:
        if not self.base.is_absolute():
            raise ValueError("the Johnny root must be an absolute path")
        return self

    @classmethod
    def resolve(cls, environ: Mapping[str, str] | None = None) -> "JohnnyRootLayout":
        """Resolve the override root when present, else the canonical per-user root."""

        source = os.environ if environ is None else environ
        override = source.get(_ENVIRONMENT_KEY)
        if override:
            return cls(base=Path(override))
        local_app_data = source.get("LOCALAPPDATA")
        if not local_app_data:
            raise ValueError("LOCALAPPDATA is required to locate the per-user root")
        return cls(base=Path(local_app_data) / _DEFAULT_DIRECTORY_NAME)

    @property
    def plugin_root(self) -> Path:
        return self.base / "plugin"

    @property
    def venv_root(self) -> Path:
        return self.base / "venv"

    @property
    def launcher_root(self) -> Path:
        return self.base / "launcher"

    @property
    def queue_root(self) -> Path:
        return self.base / "queue"

    @property
    def telemetry_root(self) -> Path:
        return self.base / "telemetry"

    @property
    def runtime_root(self) -> Path:
        return self.base / "runtime"

    @property
    def venv_python(self) -> Path:
        return self.venv_root / "Scripts" / "python.exe"

    @property
    def runtime_entry(self) -> Path:
        return self.runtime_root / "johnny_router_entry.py"

    @property
    def journal_path(self) -> Path:
        return self.base / _JOURNAL_FILE_NAME

    @property
    def ledger_path(self) -> Path:
        return self.base / _LEDGER_FILE_NAME

    def owned_receipt_path(self, receipt: str) -> Path:
        """Map one ledger receipt to its owned directory; foreign names stay out."""

        if receipt not in _OWNED_DIRECTORY_NAMES and receipt != "runtime":
            raise ValueError("unknown owned receipt name")
        return self.base / receipt


class FileInstallAttemptJournal:
    """Append-only JSONL journal implementing the frozen install journal port."""

    def __init__(self, journal_path: Path) -> None:
        self._path = journal_path

    def _replay(self) -> dict[str, str] | None:
        """Return {attempt_id: OPEN|SEALED}, or None when the journal is unreadable."""

        if not self._path.exists():
            return {}
        try:
            text = self._path.read_text(encoding="utf-8")
        except OSError:
            return None
        states: dict[str, str] = {}
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                event = json.loads(stripped)
            except ValueError:
                return None
            if type(event) is not dict:
                return None
            kind = event.get("event")
            attempt_id = event.get("attempt_id")
            if type(kind) is not str or type(attempt_id) is not str:
                return None
            if kind == "open":
                if attempt_id in states:
                    return None
                states[attempt_id] = "OPEN"
            elif kind == "record":
                if states.get(attempt_id) != "OPEN":
                    return None
            elif kind == "seal":
                if states.get(attempt_id) != "OPEN":
                    return None
                states[attempt_id] = "SEALED"
            else:
                return None
        return states

    def _append(self, event: dict[str, str]) -> bool:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(event, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            return False
        return True

    def open(self, attempt_id: str) -> InstallJournalOpenResult:
        states = self._replay()
        if states is None:
            return InstallJournalOpenResult(status=InstallJournalOpenStatus.UNAVAILABLE)
        if attempt_id in states or any(
            state == "OPEN" for state in states.values()
        ):
            return InstallJournalOpenResult(status=InstallJournalOpenStatus.CONFLICT)
        if not self._append({"event": "open", "attempt_id": attempt_id}):
            return InstallJournalOpenResult(status=InstallJournalOpenStatus.UNAVAILABLE)
        return InstallJournalOpenResult(status=InstallJournalOpenStatus.OPENED)

    def record(self, attempt_id: str, record: InstallEffectRecord) -> bool:
        states = self._replay()
        if states is None or states.get(attempt_id) != "OPEN":
            return False
        return self._append(
            {
                "event": "record",
                "attempt_id": attempt_id,
                "kind": record.kind.value,
                "receipt": record.receipt,
            }
        )

    def seal(self, attempt_id: str) -> bool:
        states = self._replay()
        if states is None or states.get(attempt_id) != "OPEN":
            return False
        return self._append({"event": "seal", "attempt_id": attempt_id})


class FileUninstallLedgerStore:
    """Atomic single-file ledger store implementing the frozen uninstall port."""

    def __init__(self, ledger_path: Path) -> None:
        self._path = ledger_path

    def read(self) -> UninstallLedgerReadResult:
        if not self._path.exists():
            return UninstallLedgerReadResult(
                status=UninstallLedgerReadStatus.ABSENT, ledger=None
            )
        ledger = PluginUninstallLedger.model_validate_json(
            self._path.read_text(encoding="utf-8")
        )
        return UninstallLedgerReadResult(
            status=UninstallLedgerReadStatus.PRESENT, ledger=ledger
        )

    def write(self, ledger: PluginUninstallLedger) -> bool:
        try:
            trusted = PluginUninstallLedger.model_validate(ledger, strict=True)
        except ValidationError:
            return False
        temporary = self._path.with_suffix(".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(trusted.model_dump_json(), encoding="utf-8")
            os.replace(temporary, self._path)
        except OSError:
            try:
                temporary.unlink()
            except OSError:
                pass
            return False
        return True

    def remove(self, receipt_id: str) -> bool:
        try:
            current = self.read()
        except (OSError, ValueError):
            return False
        if current.status is UninstallLedgerReadStatus.ABSENT:
            return True
        ledger = current.ledger
        assert ledger is not None
        if ledger.receipt_id != receipt_id:
            return False
        try:
            self._path.unlink()
        except OSError:
            return False
        return True


__all__ = [
    "FileInstallAttemptJournal",
    "FileUninstallLedgerStore",
    "JohnnyRootLayout",
]
