"""Live uninstall composition: the real Ticket 12 transaction on real state.

Ownership is proven per directory through the `.johnny-owned` marker written
at install time; anything unmarked is foreign and halts the whole removal
with the ledger retained. After a complete removal the bookkeeping files and
the (then empty) root itself are cleared, honoring the canonical-uninstall
zero-residue guarantee.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path

from .johnny_root_layout import FileUninstallLedgerStore, JohnnyRootLayout
from .plugin_uninstall_transaction import (
    OwnedStateRecord,
    PluginUninstallPorts,
    PluginUninstallRequest,
    PluginUninstallStatus,
    PluginUninstallTransaction,
    UninstallLedgerReadStatus,
    UninstallOwnershipProbe,
)

_OWNED_MARKER_NAME = ".johnny-owned"
_ABSENT_PROBE_RECEIPT = "receipt-live-absent-probe"

_RECEIPT_DIRECTORIES: dict[str, tuple[str, ...]] = {
    "plugin": ("plugin",),
    "venv": ("venv",),
    "launcher": ("launcher", "runtime"),
    "queue": ("queue",),
    "telemetry": ("telemetry",),
}


def _clear_read_only(function: object, path: str, excinfo: object) -> None:
    os.chmod(path, stat.S_IWRITE)
    if os.path.isfile(path):
        os.unlink(path)
    else:
        os.rmdir(path)


def _delete_tree(root: Path) -> bool:
    try:
        if root.exists():
            shutil.rmtree(root, onerror=_clear_read_only)
    except OSError:
        return False
    return not root.exists()


class _ScriptedShutdownPort:
    """No live runner runtime exists in 0.4.x; the event-runner line replaces this."""

    def block(self, receipt_id: str) -> bool:
        return True

    def cancel_all(self, receipt_id: str) -> bool:
        return True

    def stop_all(self, receipt_id: str) -> bool:
        return True


class LiveOwnedStatePort:
    """Marker-proven ownership over the receipt-mapped directories."""

    def __init__(self, layout: JohnnyRootLayout, receipt_id: str) -> None:
        self._layout = layout
        self._receipt_id = receipt_id

    def _directories(self, receipt: str) -> tuple[Path, ...]:
        names = _RECEIPT_DIRECTORIES.get(receipt, ())
        return tuple(self._layout.base / name for name in names)

    def probe(self, record: OwnedStateRecord) -> UninstallOwnershipProbe:
        directories = self._directories(record.receipt)
        if not directories:
            return UninstallOwnershipProbe.FOREIGN
        for directory in directories:
            if not directory.exists():
                continue
            # Every existing directory this receipt would delete must carry its
            # own ownership proof; a secondary directory is not covered by the
            # primary's marker.
            marker = directory / _OWNED_MARKER_NAME
            if not marker.is_file():
                return UninstallOwnershipProbe.FOREIGN
            try:
                if marker.read_text(encoding="utf-8") != self._receipt_id:
                    return UninstallOwnershipProbe.FOREIGN
            except OSError:
                return UninstallOwnershipProbe.UNKNOWN
        return UninstallOwnershipProbe.OWNED

    def remove(self, record: OwnedStateRecord) -> bool:
        return all(
            _delete_tree(directory)
            for directory in self._directories(record.receipt)
        )

    def has_owned_state(self, receipt_id: str) -> bool:
        """Report any Johnny-owned residue, whichever receipt marked it.

        With the ledger gone the caller has no receipt to compare against, so
        matching only the caller's identity would report real owned residue as
        "not installed". Any well-formed marker is residue.
        """

        for names in _RECEIPT_DIRECTORIES.values():
            for name in names:
                marker = self._layout.base / name / _OWNED_MARKER_NAME
                try:
                    if marker.is_file() and marker.read_text(encoding="utf-8"):
                        return True
                except OSError:
                    return True
        return False


class LiveAbsencePort:
    def __init__(self, layout: JohnnyRootLayout) -> None:
        self._layout = layout

    def verify_absent(self, record: OwnedStateRecord) -> bool:
        names = _RECEIPT_DIRECTORIES.get(record.receipt, ())
        return all(not (self._layout.base / name).exists() for name in names)


def run_live_uninstall(johnny_root: Path) -> int:
    """Run the real receipt-owned uninstall; print one typed JSON line."""

    layout = JohnnyRootLayout(base=johnny_root)
    store = FileUninstallLedgerStore(layout.ledger_path)
    try:
        current = store.read()
    except (OSError, ValueError):
        print(json.dumps({"status": "BLOCKED", "failure": "LEDGER_UNAVAILABLE"}))
        return 2
    receipt_id = (
        current.ledger.receipt_id
        if current.status is UninstallLedgerReadStatus.PRESENT
        and current.ledger is not None
        else _ABSENT_PROBE_RECEIPT
    )
    transaction = PluginUninstallTransaction(
        PluginUninstallPorts(
            ledger=store,
            work_admission=_ScriptedShutdownPort(),
            subscriptions=_ScriptedShutdownPort(),
            runners=_ScriptedShutdownPort(),
            owned_state=LiveOwnedStatePort(layout, receipt_id),
            absence=LiveAbsencePort(layout),
        )
    )
    result = transaction.run(PluginUninstallRequest(receipt_id=receipt_id))
    if result.status is PluginUninstallStatus.REMOVED:
        # Bookkeeping and the then-empty root are the final owned residue.
        try:
            layout.journal_path.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            if layout.base.exists() and not any(layout.base.iterdir()):
                layout.base.rmdir()
        except OSError:
            pass
    print(
        json.dumps(
            {
                "status": result.status.value,
                "failure": result.failure.value if result.failure else None,
                "removed": [kind.value for kind in result.removed],
                "remaining": [kind.value for kind in result.remaining],
                "root_deleted": not layout.base.exists(),
            },
            sort_keys=True,
        )
    )
    if result.status in (
        PluginUninstallStatus.REMOVED,
        PluginUninstallStatus.NOT_INSTALLED,
    ):
        return 0
    return 2


__all__ = [
    "LiveAbsencePort",
    "LiveOwnedStatePort",
    "run_live_uninstall",
]
