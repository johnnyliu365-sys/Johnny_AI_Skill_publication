"""Build a deterministic, receipt-free plugin bundle from a clean local source tree."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Final
import zipfile

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from .runtime_dependency_lock import (
    RuntimeDependencyLockReadError,
    load_runtime_dependency_lock,
)
from .windows_package_manifest import (
    PayloadManifest,
    PayloadManifestBuildError,
    build_payload_manifest,
)


_SOURCE_COMMIT_PATTERN: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{40}\Z")
_SHA256_PATTERN: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{64}\Z")
_CANDIDATE_NAME: Final[str] = "johnny-ai-skill-0.4.9.zip"
_MANIFEST_NAME: Final[str] = "payload-manifest.json"
_UTF8_FLAG: Final[int] = 0x800
_REGULAR_FILE_MODE: Final[int] = 0o100644


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
    )


class PluginBundleBuildRequest(_StrictModel):
    """The source, destination and exact manifest authority for one build."""

    repository_root: Path
    output_root: Path
    manifest: PayloadManifest


class PluginBundleBuildStatus(str, Enum):
    BUNDLED = "BUNDLED"
    BLOCKED = "BLOCKED"


class PluginBundleBuildFailure(str, Enum):
    REQUEST_INVALID = "REQUEST_INVALID"
    GIT_READBACK_UNAVAILABLE = "GIT_READBACK_UNAVAILABLE"
    SOURCE_DIRTY = "SOURCE_DIRTY"
    SOURCE_IDENTITY_MISMATCH = "SOURCE_IDENTITY_MISMATCH"
    MANIFEST_MISMATCH = "MANIFEST_MISMATCH"
    ENTRY_UNAVAILABLE = "ENTRY_UNAVAILABLE"
    ENTRY_CONTENT_MISMATCH = "ENTRY_CONTENT_MISMATCH"
    OUTPUT_UNAVAILABLE = "OUTPUT_UNAVAILABLE"


class PluginBundleBuildResult(_StrictModel):
    """Finite build outcome with only digest and size evidence on success."""

    status: PluginBundleBuildStatus
    source_commit: str | None = None
    manifest_digest: str | None = None
    archive_sha256: str | None = None
    archive_byte_length: int | None = None
    failure: PluginBundleBuildFailure | None = None

    @field_validator("source_commit")
    @classmethod
    def canonical_source_commit(cls, value: str | None) -> str | None:
        if value is not None and _SOURCE_COMMIT_PATTERN.fullmatch(value) is None:
            raise ValueError("source_commit must be a canonical lowercase Git identity")
        return value

    @field_validator("manifest_digest", "archive_sha256")
    @classmethod
    def canonical_sha256(cls, value: str | None) -> str | None:
        if value is not None and _SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("digest must be canonical lowercase SHA-256")
        return value

    @model_validator(mode="after")
    def exact_success_or_failure(self) -> "PluginBundleBuildResult":
        success_fields = (
            self.source_commit,
            self.manifest_digest,
            self.archive_sha256,
            self.archive_byte_length,
        )
        if self.status is PluginBundleBuildStatus.BUNDLED:
            if any(value is None for value in success_fields):
                raise ValueError("bundled result requires complete success evidence")
            if self.archive_byte_length is not None and self.archive_byte_length <= 0:
                raise ValueError("bundled archive must have positive length")
            if self.failure is not None:
                raise ValueError("bundled result cannot expose a failure")
        elif any(value is not None for value in success_fields) or self.failure is None:
            raise ValueError("blocked result requires one failure and no success evidence")
        return self


@dataclass(frozen=True)
class _GitReadback:
    head: str
    porcelain: str


class _EntryUnavailableError(Exception):
    pass


class _EntryContentMismatchError(Exception):
    pass


def _blocked(failure: PluginBundleBuildFailure) -> PluginBundleBuildResult:
    return PluginBundleBuildResult(
        status=PluginBundleBuildStatus.BLOCKED,
        failure=failure,
    )


def _run_read_only_git(repository_root: Path, arguments: tuple[str, ...]) -> str | None:
    try:
        completed = subprocess.run(
            ("git", *arguments),
            cwd=repository_root,
            check=False,
            capture_output=True,
            text=True,
            shell=False,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def _read_git_state(repository_root: Path) -> _GitReadback | None:
    head_output = _run_read_only_git(repository_root, ("rev-parse", "HEAD"))
    status_output = _run_read_only_git(
        repository_root,
        ("status", "--porcelain=v1", "--untracked-files=all"),
    )
    if head_output is None or status_output is None:
        return None
    head = head_output.strip()
    if _SOURCE_COMMIT_PATTERN.fullmatch(head) is None:
        return None
    return _GitReadback(head=head, porcelain=status_output)


def _resolve_roots(request: PluginBundleBuildRequest) -> tuple[Path, Path] | None:
    try:
        repository_root = request.repository_root.resolve(strict=True)
        output_root = request.output_root.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not repository_root.is_dir() or not output_root.is_dir():
        return None
    if output_root == repository_root or repository_root in output_root.parents:
        return None
    return repository_root, output_root


def _entry_path(repository_root: Path, archive_relative_path: str) -> Path:
    return repository_root.joinpath(*archive_relative_path.split("/"))


def _read_verified_entries(
    repository_root: Path,
    manifest: PayloadManifest,
) -> tuple[tuple[str, bytes], ...]:
    verified: list[tuple[str, bytes]] = []
    for entry in manifest.entries:
        source = _entry_path(repository_root, entry.archive_relative_path)
        if source.is_symlink() or not source.is_file():
            raise _EntryUnavailableError
        try:
            content = source.read_bytes()
        except OSError as error:
            raise _EntryUnavailableError from error
        if len(content) != entry.byte_length or sha256(content).hexdigest() != entry.sha256:
            raise _EntryContentMismatchError
        verified.append((entry.archive_relative_path, content))
    return tuple(verified)


def _payload_tree_has_symlink(repository_root: Path) -> bool:
    for tree_name in ("skills", "library"):
        tree = repository_root / tree_name
        if tree.is_symlink():
            return True
        try:
            if any(path.is_symlink() for path in tree.rglob("*")):
                return True
        except OSError:
            return True
    return False


def _content_differs(
    requested: PayloadManifest,
    rebuilt: PayloadManifest,
) -> bool:
    return (
        requested.schema_version == rebuilt.schema_version
        and requested.plugin_id == rebuilt.plugin_id
        and requested.plugin_version == rebuilt.plugin_version
        and requested.source_commit == rebuilt.source_commit
        and requested.dependency_lock_digest == rebuilt.dependency_lock_digest
        and tuple(entry.archive_relative_path for entry in requested.entries)
        == tuple(entry.archive_relative_path for entry in rebuilt.entries)
        and requested.entries != rebuilt.entries
    )


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(filename=name, date_time=(1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.external_attr = _REGULAR_FILE_MODE << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    info.flag_bits |= _UTF8_FLAG
    info.extra = b""
    info.comment = b""
    return info


def _write_archive(
    temporary_path: Path,
    entries: tuple[tuple[str, bytes], ...],
    manifest: PayloadManifest,
) -> None:
    with zipfile.ZipFile(
        temporary_path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for archive_relative_path, content in entries:
            archive.writestr(_zip_info(archive_relative_path), content)
        archive.writestr(
            _zip_info(_MANIFEST_NAME),
            manifest.canonical_json().encode("utf-8"),
        )


class PluginBundleBuilder:
    """Build one deterministic candidate after all source gates pass."""

    def build(self, request: PluginBundleBuildRequest) -> PluginBundleBuildResult:
        """Return a finite result without exposing source or output paths."""

        validated_request = self._validated_request(request)
        if validated_request is None:
            return _blocked(PluginBundleBuildFailure.REQUEST_INVALID)
        roots = _resolve_roots(validated_request)
        if roots is None:
            return _blocked(PluginBundleBuildFailure.REQUEST_INVALID)
        repository_root, output_root = roots

        git_state = _read_git_state(repository_root)
        if git_state is None:
            return _blocked(PluginBundleBuildFailure.GIT_READBACK_UNAVAILABLE)
        if git_state.porcelain.strip():
            return _blocked(PluginBundleBuildFailure.SOURCE_DIRTY)
        if git_state.head != validated_request.manifest.source_commit:
            return _blocked(PluginBundleBuildFailure.SOURCE_IDENTITY_MISMATCH)

        try:
            verified_entries = _read_verified_entries(
                repository_root,
                validated_request.manifest,
            )
        except _EntryUnavailableError:
            return _blocked(PluginBundleBuildFailure.ENTRY_UNAVAILABLE)
        except _EntryContentMismatchError:
            return _blocked(PluginBundleBuildFailure.ENTRY_CONTENT_MISMATCH)

        lock_path = repository_root / "requirements-runtime.lock"
        if lock_path.is_symlink() or not lock_path.is_file():
            return _blocked(PluginBundleBuildFailure.ENTRY_UNAVAILABLE)
        try:
            committed_lock = load_runtime_dependency_lock(lock_path)
            rebuilt_manifest = build_payload_manifest(
                repository_root,
                git_state.head,
                committed_lock,
            )
        except RuntimeDependencyLockReadError:
            return _blocked(PluginBundleBuildFailure.MANIFEST_MISMATCH)
        except PayloadManifestBuildError:
            if _payload_tree_has_symlink(repository_root):
                return _blocked(PluginBundleBuildFailure.ENTRY_UNAVAILABLE)
            return _blocked(PluginBundleBuildFailure.MANIFEST_MISMATCH)

        if rebuilt_manifest != validated_request.manifest:
            if _content_differs(validated_request.manifest, rebuilt_manifest):
                return _blocked(PluginBundleBuildFailure.ENTRY_CONTENT_MISMATCH)
            return _blocked(PluginBundleBuildFailure.MANIFEST_MISMATCH)

        candidate = output_root / _CANDIDATE_NAME
        if candidate.exists() or candidate.is_symlink():
            return _blocked(PluginBundleBuildFailure.OUTPUT_UNAVAILABLE)

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=".johnny-ai-skill-0.4.9-",
                suffix=".tmp",
                dir=output_root,
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
            _write_archive(temporary_path, verified_entries, validated_request.manifest)
            archive_bytes = temporary_path.read_bytes()
            temporary_path.rename(candidate)
            temporary_path = None
        except (OSError, RuntimeError, ValueError, zipfile.LargeZipFile):
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
            return _blocked(PluginBundleBuildFailure.OUTPUT_UNAVAILABLE)

        return PluginBundleBuildResult(
            status=PluginBundleBuildStatus.BUNDLED,
            source_commit=git_state.head,
            manifest_digest=validated_request.manifest.canonical_digest(),
            archive_sha256=sha256(archive_bytes).hexdigest(),
            archive_byte_length=len(archive_bytes),
        )

    @staticmethod
    def _validated_request(
        request: PluginBundleBuildRequest,
    ) -> PluginBundleBuildRequest | None:
        if type(request) is not PluginBundleBuildRequest:
            return None
        try:
            return PluginBundleBuildRequest.model_validate(request, strict=True)
        except ValidationError:
            return None


__all__ = [
    "PluginBundleBuildFailure",
    "PluginBundleBuildRequest",
    "PluginBundleBuildResult",
    "PluginBundleBuildStatus",
    "PluginBundleBuilder",
]
