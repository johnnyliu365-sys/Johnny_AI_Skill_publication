"""Typed live install composition; runs inside the bootstrap-created venv.

Composes the frozen Ticket 11 transaction with every real port, then
provisions the remaining owned directories, ownership markers and the
uninstall ledger. Prints exactly one typed JSON line and returns a finite
exit code: 0 installed, 2 blocked, 3 compensated/incomplete.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
import zipfile
from pathlib import Path

from .johnny_root_layout import (
    FileInstallAttemptJournal,
    FileUninstallLedgerStore,
    JohnnyRootLayout,
)
from .johnny_router_contracts import PreflightProbe
from .payload_effect_ports import (
    RealLauncherEffectPort,
    RealPluginPayloadEffectPort,
)
from .plugin_install_transaction import (
    ApprovedBundleReference,
    PluginInstallPorts,
    PluginInstallRequest,
    PluginInstallStatus,
    PluginInstallTransaction,
)
from .plugin_uninstall_transaction import (
    OwnedStateKind,
    OwnedStateRecord,
    PluginUninstallLedger,
)
from .registration_readback_port import RealRegistrationReadbackPort
from .runtime_dependency_lock import build_approved_runtime_lock
from .verifying_venv_port import VerifyingVenvPort
from .windows_package_manifest import PayloadManifest

_OWNED_MARKER_NAME = ".johnny-owned"

_LEDGER_RECEIPTS: tuple[tuple[OwnedStateKind, str], ...] = (
    (OwnedStateKind.PLUGIN_PAYLOAD, "plugin"),
    (OwnedStateKind.VENV, "venv"),
    (OwnedStateKind.LAUNCHER, "launcher"),
    (OwnedStateKind.QUEUE, "queue"),
    (OwnedStateKind.TELEMETRY, "telemetry"),
)

# Uninstall proves ownership per directory before deleting it, so every
# directory a receipt owns — including the ones it owns beyond its own name —
# must be marked at install time or removal will correctly refuse.
_SECONDARY_OWNED_DIRECTORIES: tuple[str, ...] = ("runtime",)


class _ZipDigestPort:
    def __init__(self, bundle_zip: Path) -> None:
        self._bundle_zip = bundle_zip

    def read_archive_sha256(self) -> str:
        return hashlib.sha256(self._bundle_zip.read_bytes()).hexdigest()


class _HostProbePort:
    def probe(self) -> PreflightProbe:
        version = (
            sys.version_info.major,
            sys.version_info.minor,
            sys.version_info.micro,
        )
        return PreflightProbe(
            git_available=shutil.which("git") is not None,
            python_version=version,
        )


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True))


def _provision_owned_state(
    layout: JohnnyRootLayout, receipt_id: str
) -> PluginUninstallLedger:
    layout.queue_root.mkdir(parents=True, exist_ok=True)
    layout.telemetry_root.mkdir(parents=True, exist_ok=True)
    records = []
    for kind, receipt in _LEDGER_RECEIPTS:
        owned_root = layout.owned_receipt_path(receipt)
        owned_root.mkdir(parents=True, exist_ok=True)
        (owned_root / _OWNED_MARKER_NAME).write_text(receipt_id, encoding="utf-8")
        records.append(OwnedStateRecord(kind=kind, receipt=receipt))
    for secondary in _SECONDARY_OWNED_DIRECTORIES:
        secondary_root = layout.owned_receipt_path(secondary)
        secondary_root.mkdir(parents=True, exist_ok=True)
        (secondary_root / _OWNED_MARKER_NAME).write_text(
            receipt_id, encoding="utf-8"
        )
    return PluginUninstallLedger(receipt_id=receipt_id, records=tuple(records))


def run_live_install(bundle_zip: Path, johnny_root: Path) -> int:
    layout = JohnnyRootLayout(base=johnny_root)
    try:
        manifest = PayloadManifest.model_validate_json(
            _read_manifest_from_zip(bundle_zip)
        )
    except (OSError, ValueError, KeyError, zipfile.BadZipFile):
        _emit({"status": "BLOCKED", "failure": "MANIFEST_UNREADABLE"})
        return 2

    stamp = time.strftime("%Y%m%d%H%M%S")
    attempt_id = f"attempt-live-{stamp}"
    receipt_id = f"receipt-live-{stamp}"
    request = PluginInstallRequest(
        attempt_id=attempt_id,
        bundle=ApprovedBundleReference(
            archive_sha256=_ZipDigestPort(bundle_zip).read_archive_sha256(),
            manifest_digest=manifest.canonical_digest(),
        ),
        manifest=manifest,
        runtime_lock=build_approved_runtime_lock(),
    )
    transaction = PluginInstallTransaction(
        PluginInstallPorts(
            host_probe=_HostProbePort(),
            archive=_ZipDigestPort(bundle_zip),
            journal=FileInstallAttemptJournal(layout.journal_path),
            venv=VerifyingVenvPort(layout),
            plugin_payload=RealPluginPayloadEffectPort(layout, bundle_zip),
            launcher=RealLauncherEffectPort(layout),
            registration=RealRegistrationReadbackPort(layout),
        )
    )
    result = transaction.run(request)
    if result.status is PluginInstallStatus.INSTALLED:
        ledger = _provision_owned_state(layout, receipt_id)
        if not FileUninstallLedgerStore(layout.ledger_path).write(ledger):
            _emit({"status": "BLOCKED", "failure": "LEDGER_WRITE_FAILED"})
            return 2
        _emit(
            {
                "status": "INSTALLED",
                "attempt_id": attempt_id,
                "receipt_id": receipt_id,
                "plugin_version": manifest.plugin_version,
                "root": str(layout.base),
            }
        )
        return 0
    _emit(
        {
            "status": result.status.value,
            "failure": result.failure.value if result.failure else None,
            "compensated": [kind.value for kind in result.compensated],
            "uncompensated": [kind.value for kind in result.uncompensated],
        }
    )
    return 2 if result.status is PluginInstallStatus.BLOCKED else 3


def _read_manifest_from_zip(bundle_zip: Path) -> str:
    with zipfile.ZipFile(bundle_zip) as archive:
        return archive.read("payload-manifest.json").decode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Johnny live install composition.")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    arguments = parser.parse_args(argv)
    return run_live_install(arguments.bundle, arguments.root)


if __name__ == "__main__":
    raise SystemExit(main())
