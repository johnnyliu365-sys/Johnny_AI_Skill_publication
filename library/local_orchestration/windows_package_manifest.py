"""Strict payload manifest contracts and a read-only source-tree builder."""

from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path
from typing import Final, Literal, Self, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .runtime_dependency_lock import (
    RuntimeDependencyLock,
    RuntimeDependencyLockReadError,
    load_runtime_dependency_lock,
)


_SHA256_PATTERN: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{64}\Z")
_SOURCE_COMMIT_PATTERN: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{40}\Z")
_PLUGIN_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\Z")
_PLUGIN_VERSION_PATTERN: Final[re.Pattern[str]] = re.compile(r"[0-9]+(?:\.[0-9]+){2}\Z")
_PAYLOAD_TREE_ROOTS: Final[frozenset[str]] = frozenset({"library", "skills"})
_ALLOWED_FILES: Final[frozenset[str]] = frozenset(
    {
        ".codex-plugin/plugin.json",
        "AGENTS.md",
        "Workflow.md",
        "CodeReview.md",
        "README.md",
        "install.ps1",
        "johnny-router.ps1",
        "requirements-runtime.lock",
    }
)
_REQUIRED_FILES: Final[tuple[str, ...]] = (
    ".codex-plugin/plugin.json",
    "AGENTS.md",
    "Workflow.md",
    "CodeReview.md",
    "README.md",
    "requirements-runtime.lock",
)
_EXCLUDED_SEGMENTS: Final[frozenset[str]] = frozenset(
    {
        ".agents",
        ".cache",
        ".claude-plugin",
        ".coverage",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        "__pycache__",
        "build",
        "cache",
        "caches",
        "coverage",
        "dist",
        "doc",
        "modules",
        "queues",
        "receipts",
        "review",
        "reviews",
        "secret",
        "secrets",
        "staging",
        "target",
        "targets",
        "telemetry",
        "tests",
    }
)
_EXCLUDED_SUFFIXES: Final[tuple[str, ...]] = (".pyc", ".pyo")


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
    )


class PayloadManifestEntry(_StrictModel):
    """One canonical archive-relative file path and its immutable byte evidence."""

    archive_relative_path: str
    sha256: str
    byte_length: int = Field(ge=0)

    @field_validator("archive_relative_path")
    @classmethod
    def _validate_archive_relative_path(cls, value: str) -> str:
        if not _is_admitted_archive_path(value):
            raise ValueError("archive_relative_path is outside the package allowlist")
        return value

    @field_validator("sha256")
    @classmethod
    def _validate_sha256(cls, value: str) -> str:
        if _SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
        return value


class PayloadManifest(_StrictModel):
    """The closed, canonical payload manifest without a self-referential entry."""

    schema_version: Literal[1] = 1
    plugin_id: str
    plugin_version: str
    source_commit: str
    dependency_lock_digest: str
    entries: tuple[PayloadManifestEntry, ...] = Field(min_length=1)

    @field_validator("plugin_id")
    @classmethod
    def _validate_plugin_id(cls, value: str) -> str:
        if _PLUGIN_ID_PATTERN.fullmatch(value) is None:
            raise ValueError("plugin_id must be a canonical plugin identifier")
        return value

    @field_validator("plugin_version")
    @classmethod
    def _validate_plugin_version(cls, value: str) -> str:
        if _PLUGIN_VERSION_PATTERN.fullmatch(value) is None:
            raise ValueError("plugin_version must be a three-part numeric version")
        return value

    @field_validator("source_commit")
    @classmethod
    def _validate_source_commit(cls, value: str) -> str:
        if _SOURCE_COMMIT_PATTERN.fullmatch(value) is None:
            raise ValueError("source_commit must be a lowercase Git commit SHA-1")
        return value

    @field_validator("dependency_lock_digest")
    @classmethod
    def _validate_dependency_lock_digest(cls, value: str) -> str:
        if _SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("dependency_lock_digest must be 64 lowercase hexadecimal characters")
        return value

    @model_validator(mode="after")
    def _validate_canonical_entries(self) -> Self:
        paths = tuple(entry.archive_relative_path for entry in self.entries)
        if len(set(paths)) != len(paths):
            raise ValueError("entries must not contain duplicate archive paths")
        if paths != tuple(sorted(paths)):
            raise ValueError("entries must be ordinal-sorted by archive path")
        return self

    def canonical_json(self) -> str:
        return _canonical_json(
            self.schema_version,
            self.plugin_id,
            self.plugin_version,
            self.source_commit,
            self.dependency_lock_digest,
            self.entries,
        )

    def canonical_digest(self) -> str:
        return sha256(self.canonical_json().encode("utf-8")).hexdigest()


class PayloadManifestBuildError(ValueError):
    """Raised when a source tree cannot produce a closed payload manifest."""


class _PluginMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    name: str
    version: str

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if _PLUGIN_ID_PATTERN.fullmatch(value) is None:
            raise ValueError("plugin metadata name is invalid")
        return value

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        if _PLUGIN_VERSION_PATTERN.fullmatch(value) is None:
            raise ValueError("plugin metadata version is invalid")
        return value


class _EntryRecord(TypedDict):
    archive_relative_path: str
    byte_length: int
    sha256: str


class _ManifestRecord(TypedDict):
    schema_version: Literal[1]
    plugin_id: str
    plugin_version: str
    source_commit: str
    dependency_lock_digest: str
    entries: tuple[_EntryRecord, ...]


def _is_excluded_archive_path(value: str) -> bool:
    parts = value.split("/")
    folded_parts = tuple(part.casefold() for part in parts)
    if value.casefold() == "payload-manifest.json":
        return True
    if any(part in _EXCLUDED_SEGMENTS for part in folded_parts):
        return True
    if any(part == ".env" or part.startswith(".env.") for part in folded_parts):
        return True
    return value.casefold().endswith(_EXCLUDED_SUFFIXES)


def _is_admitted_archive_path(value: str) -> bool:
    if (
        not value
        or value != value.strip()
        or "\\" in value
        or ":" in value
        or "%" in value
        or value.startswith("/")
        or re.match(r"[A-Za-z]:", value) is not None
        or any(ord(character) < 32 for character in value)
    ):
        return False
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return False
    if _is_excluded_archive_path(value):
        return False
    return value in _ALLOWED_FILES or (len(parts) > 1 and parts[0] in _PAYLOAD_TREE_ROOTS)


def _entry_record(entry: PayloadManifestEntry) -> _EntryRecord:
    return {
        "archive_relative_path": entry.archive_relative_path,
        "byte_length": entry.byte_length,
        "sha256": entry.sha256,
    }


def _manifest_record(
    schema_version: Literal[1],
    plugin_id: str,
    plugin_version: str,
    source_commit: str,
    dependency_lock_digest: str,
    entries: tuple[PayloadManifestEntry, ...],
) -> _ManifestRecord:
    return {
        "schema_version": schema_version,
        "plugin_id": plugin_id,
        "plugin_version": plugin_version,
        "source_commit": source_commit,
        "dependency_lock_digest": dependency_lock_digest,
        "entries": tuple(_entry_record(entry) for entry in entries),
    }


def _canonical_json(
    schema_version: Literal[1],
    plugin_id: str,
    plugin_version: str,
    source_commit: str,
    dependency_lock_digest: str,
    entries: tuple[PayloadManifestEntry, ...],
) -> str:
    return json.dumps(
        _manifest_record(
            schema_version,
            plugin_id,
            plugin_version,
            source_commit,
            dependency_lock_digest,
            entries,
        ),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _required_file(root: Path, relative_path: str) -> Path:
    candidate = root.joinpath(*relative_path.split("/"))
    if candidate.is_symlink() or not candidate.is_file():
        raise PayloadManifestBuildError("required payload file is absent")
    return candidate


def _optional_file(root: Path, relative_path: str) -> Path | None:
    candidate = root.joinpath(*relative_path.split("/"))
    if not candidate.exists() and not candidate.is_symlink():
        return None
    if candidate.is_symlink() or not candidate.is_file():
        raise PayloadManifestBuildError("optional payload file is invalid")
    return candidate


def _payload_files(root: Path) -> tuple[tuple[str, Path], ...]:
    files: list[tuple[str, Path]] = []
    for relative_path in _REQUIRED_FILES:
        files.append((relative_path, _required_file(root, relative_path)))
    for relative_path in ("install.ps1", "johnny-router.ps1"):
        optional = _optional_file(root, relative_path)
        if optional is not None:
            files.append((relative_path, optional))

    for tree_name in ("skills", "library"):
        tree = root / tree_name
        if tree.is_symlink() or not tree.is_dir():
            raise PayloadManifestBuildError("required payload root is absent")
        for candidate in sorted(tree.rglob("*"), key=lambda path: path.as_posix()):
            if candidate.is_symlink():
                raise PayloadManifestBuildError("payload tree contains a symlink")
            if candidate.is_file():
                relative_path = candidate.relative_to(root).as_posix()
                if not _is_admitted_archive_path(relative_path):
                    if _is_excluded_archive_path(relative_path):
                        continue
                    raise PayloadManifestBuildError("payload path identity is invalid")
                files.append((relative_path, candidate))
    return tuple(sorted(files, key=lambda item: item[0]))


def _file_entry(root: Path, relative_path: str, source: Path) -> PayloadManifestEntry:
    try:
        content = source.read_bytes()
    except OSError as error:
        raise PayloadManifestBuildError("payload file cannot be read") from error
    return PayloadManifestEntry(
        archive_relative_path=relative_path,
        sha256=sha256(content).hexdigest(),
        byte_length=len(content),
    )


def build_payload_manifest(
    repository_root: Path,
    source_commit: str,
    dependency_lock: RuntimeDependencyLock,
) -> PayloadManifest:
    """Build a digestable manifest from only the approved repository payload roots."""

    if type(dependency_lock) is not RuntimeDependencyLock:
        raise PayloadManifestBuildError("dependency lock type is not the approved lock")
    try:
        root = repository_root.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise PayloadManifestBuildError("repository root cannot be resolved") from error
    if not root.is_dir():
        raise PayloadManifestBuildError("repository root is not a directory")

    lock_path = _required_file(root, "requirements-runtime.lock")
    try:
        committed_lock = load_runtime_dependency_lock(lock_path)
    except RuntimeDependencyLockReadError as error:
        raise PayloadManifestBuildError("committed dependency lock is invalid") from error
    if committed_lock != dependency_lock:
        raise PayloadManifestBuildError("committed dependency lock does not match supplied lock")

    metadata_path = _required_file(root, ".codex-plugin/plugin.json")
    try:
        metadata = _PluginMetadata.model_validate_json(metadata_path.read_bytes(), strict=True)
    except (OSError, ValueError) as error:
        raise PayloadManifestBuildError("plugin metadata is invalid") from error

    entries = tuple(
        _file_entry(root, relative_path, source)
        for relative_path, source in _payload_files(root)
    )
    return PayloadManifest(
        schema_version=1,
        plugin_id=metadata.name,
        plugin_version=metadata.version,
        source_commit=source_commit,
        dependency_lock_digest=dependency_lock.lock_digest,
        entries=entries,
    )


__all__ = [
    "PayloadManifest",
    "PayloadManifestBuildError",
    "PayloadManifestEntry",
    "build_payload_manifest",
]
