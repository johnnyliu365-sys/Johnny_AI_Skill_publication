"""Answer, from the repository itself, where every tracked ticket stands.

The owner's question is small and precise: which ticket is at which stage,
which commit does it stand at, and what do I hand a conversation if I take it
over. Everything here exists to answer that from facts rather than from
recollection.

Two rules decide the whole design.

**A ticket's state is declared, never inferred.** Each tracked ticket carries a
```johnny-status``` block; this module reads that block and nothing else. It
does not parse the English in a State row, because a sentence like "R2/R3
landed; R4 open" is a summary written for a human and reading it as data is how
a page ends up confidently wrong about work the owner is depending on.

**Absent and broken are different answers.** A ticket file with no block has
not opted in to this surface and is simply not listed. A file whose block is
present but will not parse is reported in `unreadable`, with its path and the
reason — because that one *was* meant to be on the page, and a list that is
short because a file broke is the failure this surface exists to prevent.

The document this produces is plain stdlib types. The template that renders it
is a separate module owned by someone else; neither imports the other.
"""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

_BLOCK = re.compile(r"```johnny-status\r?\n(.*?)```", re.DOTALL)
_NULL = "-"
_TICKETS_RELATIVE = Path("modules") / "tickets"
_SKIPPED_STEMS = frozenset({"README", "TEMPLATE", "README.TEMPLATE", "PITFALL-REGISTER"})

# The lifecycle the owner actually runs: work finishes, then it is reviewed,
# and "finished" is not "accepted". DONE means the work is done and waiting for
# a verdict; APPROVED and REJECTED are the two verdicts. Collapsing DONE into
# APPROVED would hide the queue of things waiting on a review nobody has done.
_TICKET_STATES = (
    "NEEDS_OWNER",
    "REJECTED",
    "DONE",
    "IN_PROGRESS",
    "APPROVED",
)
_STAGE_STATES = ("DONE", "OPEN")
_SCALAR_KEYS = frozenset(
    {"id", "title", "state", "reason", "released_in", "commit"}
)
_REQUIRED_KEYS = ("id", "title", "state")
_REASON_REQUIRED = frozenset({"NEEDS_OWNER", "REJECTED"})
_STATE_ORDER = {name: index for index, name in enumerate(_TICKET_STATES)}


def _git(repository_root: Path, *arguments: str) -> str | None:
    """Run git for one fact. Bytes in, UTF-8 out: paths here carry CJK."""

    try:
        completed = subprocess.run(
            ("git", *arguments),
            cwd=str(repository_root),
            capture_output=True,
            shell=False,
            timeout=30,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.decode("utf-8", errors="replace").strip()


def find_status_block(text: str) -> str | None:
    """Return the declared block, or None when the file never opted in."""

    match = _BLOCK.search(text)
    return None if match is None else match.group(1)


def parse_status_block(body: str) -> dict[str, object]:
    """Read one declared block. Anything unexpected raises rather than guesses."""

    scalars: dict[str, str] = {}
    stages: list[dict[str, str]] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"每一行都要是 key = value：{line!r}")
        key, value = (part.strip() for part in line.split("=", 1))
        if key == "stage":
            fields = [field.strip() for field in value.split("|")]
            if len(fields) != 3:
                raise ValueError(f"stage 要寫成 ref | label | state：{value!r}")
            ref, label, state = fields
            if not ref:
                raise ValueError("stage 的 ref 不能是空的")
            if state not in _STAGE_STATES:
                raise ValueError(f"stage 狀態只能是 {_STAGE_STATES}：{state!r}")
            stages.append({"ref": ref, "label": label, "state": state})
            continue
        if key not in _SCALAR_KEYS:
            # A typo here would silently drop a field, so it is an error and
            # not something to skip past.
            raise ValueError(f"不認得的欄位 {key!r}")
        if key in scalars:
            raise ValueError(f"欄位 {key!r} 出現兩次")
        scalars[key] = value

    for key in _REQUIRED_KEYS:
        if not scalars.get(key):
            raise ValueError(f"缺少必要欄位 {key!r}")
    state = scalars["state"]
    if state not in _TICKET_STATES:
        raise ValueError(f"state 只能是 {_TICKET_STATES}：{state!r}")

    why = scalars.get("reason", _NULL)
    reason = None if why in ("", _NULL) else why
    # A row that says someone is blocked without saying on what is a row the
    # owner cannot act on, so both states that block demand their reason.
    if state in _REASON_REQUIRED and reason is None:
        raise ValueError(f"state 是 {state} 就必須寫 reason")
    if state not in _REASON_REQUIRED and reason is not None:
        raise ValueError(f"state 是 {state} 不該寫 reason")

    released = scalars.get("released_in", _NULL)
    named = scalars.get("commit", _NULL)
    return {
        "declared_commit": None if named in ("", _NULL) else named,
        "id": scalars["id"],
        "title": scalars["title"],
        "state": state,
        "reason": reason,
        "stages": stages,
        "released_in": None if released in ("", _NULL) else released,
    }


def discover_ticket_files(repository_root: Path) -> tuple[Path, ...]:
    """Every ticket markdown file, registries and templates excluded."""

    root = repository_root / _TICKETS_RELATIVE
    if not root.is_dir():
        return ()
    found = [
        path
        for path in sorted(root.rglob("*.md"))
        if path.stem not in _SKIPPED_STEMS
    ]
    return tuple(found)


def _named_commit(repository_root: Path, sha: str) -> dict[str, str] | None:
    """Resolve a declared commit. A sha that does not resolve is not a commit.

    Falling back silently here would hand the owner a handoff command built
    from a typo, which fails only once they are already depending on it.
    """

    line = _git(repository_root, "log", "-1", "--format=%h%x1f%s", sha)
    if not line or "\x1f" not in line:
        return None
    resolved, subject = line.split("\x1f", 1)
    return {"sha": resolved, "subject": subject}


def _last_commit(repository_root: Path, path: Path) -> dict[str, str] | None:
    """Where the file was last touched; used only when none is declared."""

    relative = path.relative_to(repository_root).as_posix()
    line = _git(
        repository_root, "log", "-1", "--format=%h%x1f%s", "--", relative
    )
    if not line or "\x1f" not in line:
        return None
    sha, subject = line.split("\x1f", 1)
    return {"sha": sha, "subject": subject}


def _head(repository_root: Path) -> dict[str, str]:
    return {
        "branch": _git(repository_root, "rev-parse", "--abbrev-ref", "HEAD") or "-",
        "commit": _git(repository_root, "rev-parse", "--short", "HEAD") or "-",
    }


def _newest_tag(repository_root: Path, pattern: str, sort: str) -> str | None:
    listing = _git(repository_root, "tag", "--list", pattern, "--sort", sort)
    if not listing:
        return None
    return listing.splitlines()[0].strip() or None


def _tag_commit(repository_root: Path, tag: str) -> str | None:
    return _git(repository_root, "rev-parse", "--short", f"{tag}^{{commit}}")


def build_document(repository_root: Path) -> dict[str, object]:
    """Produce the whole document the template renders. Facts only."""

    tickets: list[dict[str, object]] = []
    unreadable: list[dict[str, str]] = []
    head = _head(repository_root)

    for path in discover_ticket_files(repository_root):
        relative = path.relative_to(repository_root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as error:
            unreadable.append(
                {
                    "label": relative,
                    "path": relative,
                    "reason": f"讀不到檔案：{type(error).__name__}",
                }
            )
            continue
        block = find_status_block(text)
        if block is None:
            # Never opted in. Not an error, and not something to report as one.
            continue
        try:
            declared = parse_status_block(block)
        except ValueError as error:
            unreadable.append(
                {"label": relative, "path": relative, "reason": str(error)}
            )
            continue

        named = declared.pop("declared_commit")
        if named is None:
            commit = _last_commit(repository_root, path)
        else:
            commit = _named_commit(repository_root, named)
            if commit is None:
                unreadable.append(
                    {
                        "label": relative,
                        "path": relative,
                        "reason": f"宣告的 commit {named!r} 在這個 repo 找不到",
                    }
                )
                continue
        anchor = commit["sha"] if commit is not None else head["commit"]
        declared.update(
            {
                "module": path.parent.name,
                "commit": commit,
                "ticket_path": relative,
                "handoff_command": f"git show {anchor} -- {relative}",
            }
        )
        tickets.append(declared)

    tickets.sort(key=lambda item: (_STATE_ORDER[str(item["state"])], str(item["id"])))

    release_tag = _newest_tag(repository_root, "v*", "-v:refname")
    rollback_tag = _newest_tag(repository_root, "rollback-pre-*", "-refname")
    release = None
    if release_tag is not None:
        release_commit = _tag_commit(repository_root, release_tag)
        if release_commit is not None:
            release = {"version": release_tag, "commit": release_commit}
    rollback = None
    if rollback_tag is not None:
        rollback_commit = _tag_commit(repository_root, rollback_tag)
        if rollback_commit is not None:
            rollback = {"commit": rollback_commit}

    return {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(
            timespec="seconds"
        ),
        "head": head,
        "release": release,
        "rollback": rollback,
        "tickets": tickets,
        "unreadable": unreadable,
    }


__all__ = [
    "build_document",
    "discover_ticket_files",
    "find_status_block",
    "parse_status_block",
]
