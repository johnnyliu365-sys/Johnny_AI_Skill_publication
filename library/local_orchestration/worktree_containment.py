"""Prove an agent's worktree lives under the repository root, or refuse.

The dispatch contracts are metadata-only: `WorktreeFingerprint` is an opaque
identifier and `OpaqueMetadataId` explicitly forbids path delimiters, so a
filesystem containment rule cannot live in a receipt. It belongs here, on the
host side, where the real paths are visible.

`sanctioned_worktree_path` is the correct-by-construction route: an agent that
derives its path from this function cannot land outside the repository. The
verification is the fail-closed complement for a path that arrived some other
way.
"""

from __future__ import annotations

import subprocess
from enum import Enum
from pathlib import Path

from .path_containment import resolves_within_root

WORKTREE_DIRECTORY_NAME = ".worktrees"
# Every root an agent worktree may occupy. The first is canonical and the
# one a new worktree must use; the second is owned by the Claude Code
# harness, which chooses that path itself. Both are repository-contained
# and both are ignored, which is the property this rule actually defends.
SANCTIONED_WORKTREE_ROOTS: tuple[str, ...] = (".worktrees", ".claude/worktrees")


class WorktreeContainmentStatus(str, Enum):
    """Finite outcomes of one containment verification."""

    CONTAINED = "CONTAINED"
    REFUSED = "REFUSED"


class WorktreeContainmentFailure(str, Enum):
    """Finite reasons a worktree path is refused."""

    OUTSIDE_REPOSITORY_ROOT = "OUTSIDE_REPOSITORY_ROOT"
    REPOSITORY_ROOT_INVALID = "REPOSITORY_ROOT_INVALID"
    NOT_THE_SANCTIONED_DIRECTORY = "NOT_THE_SANCTIONED_DIRECTORY"


def sanctioned_worktree_root(repository_root: Path) -> Path:
    """The single directory every agent worktree lives under."""

    return repository_root / WORKTREE_DIRECTORY_NAME


def sanctioned_worktree_path(repository_root: Path, ticket_id: str) -> Path:
    """Derive the exact path an agent must use for one ticket's worktree."""

    if not ticket_id or "/" in ticket_id or "\\" in ticket_id or ticket_id in {".", ".."}:
        raise ValueError("ticket_id must be one path segment")
    return sanctioned_worktree_root(repository_root) / ticket_id


def verify_worktree_contained(
    repository_root: Path, worktree_path: Path
) -> tuple[WorktreeContainmentStatus, WorktreeContainmentFailure | None]:
    """Prove the worktree resolves under the repository's sanctioned root.

    Containment is proven from resolved real paths, so a junctioned repository
    root or a redirected ancestor refuses rather than passing.
    """

    try:
        if not repository_root.is_absolute() or not repository_root.is_dir():
            return (
                WorktreeContainmentStatus.REFUSED,
                WorktreeContainmentFailure.REPOSITORY_ROOT_INVALID,
            )
    except OSError:
        return (
            WorktreeContainmentStatus.REFUSED,
            WorktreeContainmentFailure.REPOSITORY_ROOT_INVALID,
        )

    if not resolves_within_root(worktree_path, repository_root):
        return (
            WorktreeContainmentStatus.REFUSED,
            WorktreeContainmentFailure.OUTSIDE_REPOSITORY_ROOT,
        )

    for relative_root in SANCTIONED_WORKTREE_ROOTS:
        candidate_root = repository_root.joinpath(*relative_root.split("/"))
        if resolves_within_root(worktree_path, candidate_root):
            return WorktreeContainmentStatus.CONTAINED, None
    return (
        WorktreeContainmentStatus.REFUSED,
        WorktreeContainmentFailure.NOT_THE_SANCTIONED_DIRECTORY,
    )


def registered_worktree_paths(repository_root: Path) -> tuple[Path, ...]:
    """Read back the worktrees Git currently has registered, or nothing."""

    try:
        completed = subprocess.run(
            ("git", "-C", str(repository_root), "worktree", "list", "--porcelain"),
            check=False,
            capture_output=True,
            shell=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return ()
    if completed.returncode != 0:
        return ()
    decoded = completed.stdout.decode("utf-8", errors="replace")
    return tuple(
        Path(line[len("worktree ") :].strip())
        for line in decoded.splitlines()
        if line.startswith("worktree ")
    )


__all__ = [
    "SANCTIONED_WORKTREE_ROOTS",
    "WORKTREE_DIRECTORY_NAME",
    "WorktreeContainmentFailure",
    "WorktreeContainmentStatus",
    "registered_worktree_paths",
    "sanctioned_worktree_path",
    "sanctioned_worktree_root",
    "verify_worktree_contained",
]
