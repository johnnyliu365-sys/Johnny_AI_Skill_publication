"""Strict, read-only runtime dependency lock contracts."""

from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path
from typing import Literal, Self, TypedDict

from pydantic import ConfigDict, Field, field_validator, model_validator
from pydantic import BaseModel


_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_NAME_PATTERN = re.compile(r"[a-z0-9]+(?:_[a-z0-9]+)*\Z")
_VERSION_PATTERN = re.compile(r"[0-9]+(?:\.[0-9]+){0,2}\Z")
_WHEEL_FILENAME_PATTERN = re.compile(r"[A-Za-z0-9_.-]+\.whl\Z")
_PYTHON_CONSTRAINT = ">=3.11,<3.14"
_WINDOWS_MARKER = "platform_system == 'Windows'"


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
    )


class LockedArtifact(_StrictModel):
    """One immutable wheel filename and its lowercase SHA-256 digest."""

    filename: str
    sha256: str

    @field_validator("filename")
    @classmethod
    def _validate_filename(cls, value: str) -> str:
        if (
            not _WHEEL_FILENAME_PATTERN.fullmatch(value)
            or value != value.strip()
            or "/" in value
            or "\\" in value
            or ".." in value
        ):
            raise ValueError("filename must be one canonical wheel basename")
        return value

    @field_validator("sha256")
    @classmethod
    def _validate_sha256(cls, value: str) -> str:
        if _SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
        return value


class RuntimeDependency(_StrictModel):
    """One exact dependency identity with only immutable wheel artifacts."""

    normalized_name: str
    exact_version: str
    environment_marker: str | None = None
    source_kind: Literal["wheel"] = "wheel"
    artifacts: tuple[LockedArtifact, ...] = Field(min_length=1)

    @field_validator("normalized_name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if _NAME_PATTERN.fullmatch(value) is None:
            raise ValueError("normalized_name must use lowercase underscore form")
        return value

    @field_validator("exact_version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        if _VERSION_PATTERN.fullmatch(value) is None:
            raise ValueError("exact_version must be a numeric version")
        return value

    @field_validator("environment_marker")
    @classmethod
    def _validate_environment_marker(cls, value: str | None) -> str | None:
        if value not in (None, _WINDOWS_MARKER):
            raise ValueError("environment_marker is outside the locked Windows allowlist")
        return value


class _ArtifactRecord(TypedDict):
    filename: str
    sha256: str


class _DependencyRecord(TypedDict):
    normalized_name: str
    exact_version: str
    environment_marker: str | None
    source_kind: Literal["wheel"]
    artifacts: tuple[_ArtifactRecord, ...]


class _LockRecord(TypedDict):
    schema_version: Literal[1]
    python_constraint: str
    dependencies: tuple[_DependencyRecord, ...]


def _dependency_record(dependency: RuntimeDependency) -> _DependencyRecord:
    return {
        "normalized_name": dependency.normalized_name,
        "exact_version": dependency.exact_version,
        "environment_marker": dependency.environment_marker,
        "source_kind": dependency.source_kind,
        "artifacts": tuple(
            {"filename": artifact.filename, "sha256": artifact.sha256}
            for artifact in dependency.artifacts
        ),
    }


def _lock_record(
    schema_version: Literal[1],
    python_constraint: str,
    dependencies: tuple[RuntimeDependency, ...],
) -> _LockRecord:
    return {
        "schema_version": schema_version,
        "python_constraint": python_constraint,
        "dependencies": tuple(_dependency_record(item) for item in dependencies),
    }


def _canonical_json(
    schema_version: Literal[1],
    python_constraint: str,
    dependencies: tuple[RuntimeDependency, ...],
) -> str:
    return json.dumps(
        _lock_record(schema_version, python_constraint, dependencies),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _canonical_digest(
    schema_version: Literal[1],
    python_constraint: str,
    dependencies: tuple[RuntimeDependency, ...],
) -> str:
    return sha256(
        _canonical_json(schema_version, python_constraint, dependencies).encode("utf-8")
    ).hexdigest()


APPROVED_RUNTIME_DEPENDENCIES: tuple[RuntimeDependency, ...] = (
    RuntimeDependency(
        normalized_name="pydantic",
        exact_version="2.13.4",
        environment_marker=None,
        artifacts=(
            LockedArtifact(
                filename="pydantic-2.13.4-py3-none-any.whl",
                sha256="45a282cde31d808236fd7ea9d919b128653c8b38b393d1c4ab335c62924d9aba",
            ),
        ),
    ),
    RuntimeDependency(
        normalized_name="pydantic_core",
        exact_version="2.46.4",
        environment_marker=_WINDOWS_MARKER,
        artifacts=(
            LockedArtifact(
                filename="pydantic_core-2.46.4-cp311-cp311-win_amd64.whl",
                sha256="6f2eeda33a839975441c86a4119e1383c50b47faf0cbb5176985565c6bb02c33",
            ),
        ),
    ),
    RuntimeDependency(
        normalized_name="pywin32",
        exact_version="311",
        environment_marker=_WINDOWS_MARKER,
        artifacts=(
            LockedArtifact(
                filename="pywin32-311-cp311-cp311-win_amd64.whl",
                sha256="3ce80b34b22b17ccbd937a6e78e7225d80c52f5ab9940fe0506a1a16f3dab503",
            ),
        ),
    ),
    RuntimeDependency(
        normalized_name="annotated_types",
        exact_version="0.8.0",
        environment_marker=None,
        artifacts=(
            LockedArtifact(
                filename="annotated_types-0.8.0-py3-none-any.whl",
                sha256="f072f4d804ea359e4eaf198b1af7a8b0943881a87f31bb764f8bf219bb9419e0",
            ),
        ),
    ),
    RuntimeDependency(
        normalized_name="typing_extensions",
        exact_version="4.15.0",
        environment_marker=None,
        artifacts=(
            LockedArtifact(
                filename="typing_extensions-4.15.0-py3-none-any.whl",
                sha256="f0fa19c6845758ab08074a0cfa8b7aecb71c999ca73d62883bc25cc018c4e548",
            ),
        ),
    ),
    RuntimeDependency(
        normalized_name="typing_inspection",
        exact_version="0.4.2",
        environment_marker=None,
        artifacts=(
            LockedArtifact(
                filename="typing_inspection-0.4.2-py3-none-any.whl",
                sha256="4ed1cacbdc298c220f1bd249ed5287caa16f34d44ef4e9c3d0cbad5b521545e7",
            ),
        ),
    ),
)


class RuntimeDependencyLock(_StrictModel):
    """The closed, digest-bound runtime dependency lock."""

    schema_version: Literal[1] = 1
    python_constraint: str
    dependencies: tuple[RuntimeDependency, ...] = Field(min_length=1)
    lock_digest: str

    @field_validator("python_constraint")
    @classmethod
    def _validate_python_constraint(cls, value: str) -> str:
        if value != _PYTHON_CONSTRAINT:
            raise ValueError("python_constraint is not the approved runtime boundary")
        return value

    @field_validator("lock_digest")
    @classmethod
    def _validate_lock_digest(cls, value: str) -> str:
        if _SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("lock_digest must be 64 lowercase hexadecimal characters")
        return value

    @model_validator(mode="after")
    def _validate_closed_lock(self) -> Self:
        if self.dependencies != APPROVED_RUNTIME_DEPENDENCIES:
            raise ValueError("dependencies must equal the exact approved six-wheel lock")
        expected_digest = _canonical_digest(
            self.schema_version,
            self.python_constraint,
            self.dependencies,
        )
        if self.lock_digest != expected_digest:
            raise ValueError("lock_digest does not match canonical lock records")
        return self

    @classmethod
    def create(
        cls,
        dependencies: tuple[RuntimeDependency, ...] = APPROVED_RUNTIME_DEPENDENCIES,
        python_constraint: str = _PYTHON_CONSTRAINT,
    ) -> Self:
        digest = _canonical_digest(1, python_constraint, dependencies)
        return cls(
            schema_version=1,
            python_constraint=python_constraint,
            dependencies=dependencies,
            lock_digest=digest,
        )

    def canonical_json(self) -> str:
        return _canonical_json(
            self.schema_version,
            self.python_constraint,
            self.dependencies,
        )

    def canonical_digest(self) -> str:
        return _canonical_digest(
            self.schema_version,
            self.python_constraint,
            self.dependencies,
        )


class RuntimeDependencyLockReadError(ValueError):
    """Raised when the committed lock cannot be read as a typed lock."""


def build_approved_runtime_lock() -> RuntimeDependencyLock:
    """Build the exact approved lock without reading or writing any dependency."""

    return RuntimeDependencyLock.create()


def load_runtime_dependency_lock(path: Path) -> RuntimeDependencyLock:
    """Read and strictly validate one committed lock file."""

    try:
        return RuntimeDependencyLock.model_validate_json(path.read_bytes(), strict=True)
    except (OSError, ValueError) as error:
        raise RuntimeDependencyLockReadError("runtime dependency lock is invalid") from error


__all__ = [
    "APPROVED_RUNTIME_DEPENDENCIES",
    "LockedArtifact",
    "RuntimeDependency",
    "RuntimeDependencyLock",
    "RuntimeDependencyLockReadError",
    "build_approved_runtime_lock",
    "load_runtime_dependency_lock",
]
