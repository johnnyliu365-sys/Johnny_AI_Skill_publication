"""Refuse a change that touches what its ticket never declared, before main.

This is `dispatch_authority` wearing a second face. That gate decides which
requests may become receipts; this one decides which changes may become shared
truth. Both run fail-closed in a fixed order, both refuse with a finite named
reason, and both journal every outcome with the host principal.

**Where the gate sits, and why not earlier.** The Router is a Python library,
not a filesystem hook. It cannot stop an agent that holds a write tool from
pressing the key, and a module that claimed to "block before the edit" while
checking afterwards would be family C of the pitfall register — a mechanism
described in the present tense that is not the mechanism running. So the gate
sits where a library genuinely can stand: between a branch and `main`. A
worktree is a draft and a wrong draft is not a governance failure; the failure
is a wrong draft becoming the version everybody else reads. Host-specific
keystroke interception is a host adapter's job and deliberately not this
module's, because taking it would bind the Router to one host.

**What this is, honestly.** On the sanctioned path the guarantee is exact:
when `admit_document_mutation` refuses, it has executed no Git mutation, and
`main` is at the same commit it was before the call. It is not a cryptographic
boundary — anything in the same process could run `git merge` itself, exactly
as anything could forge a dispatch grant. What it buys is that the one route
that is supposed to move work into `main` cannot move undeclared work into
`main`, and that every refusal is named, attributed and durable.

Two properties do the real work, and both are about *who supplies the facts*.

**The boundary is read from the integration branch, never from the candidate.**
A boundary read out of the branch under judgement is a boundary the branch can
edit; an agent would widen its own declaration in the same commit that needs
widening, and the gate would agree with itself. So the declaration comes from
`git show <integration_branch>:<ticket>` — the copy already accepted as shared
truth. This is also why tickets belong to the control plane: a ticket is the
thing a change is measured against, so it cannot be a thing the change moves.

**The change set is read from Git, never from the requester.** A gate over a
self-reported list of touched files is self-discipline with extra steps, and
self-discipline is the thing that already failed. `git diff --raw` between the
merge base and the candidate is the same list a reviewer would see.

**Case comparison is deliberately asymmetric.** On Windows `DOC/a.md` and
`doc/a.md` are one file. Matching the allow lists case-insensitively would
admit paths the ticket did not write; matching the forbid list
case-sensitively would let `Dispatch_Authority.py` walk past a rule naming
`dispatch_authority.py`. Both directions therefore fail closed: allow lists
compare exactly, the forbid list compares case-folded.

**Nothing is decoded and nothing is guessed.** `%2F` is a character in a file
name, not a separator, and a path is normalised lexically *before* it is
matched — otherwise `doc/../library/x.py` matches a boundary of `doc/`, which
is the whole prefix-confusion family in one line. A ticket with no readable
declaration is refused rather than interpreted: not knowing where the boundary
is does not mean there is not one.
"""

from __future__ import annotations

import fnmatch
import getpass
import json
import re
import subprocess
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field

from .johnny_root_layout import JohnnyRootLayout

_JOURNAL_FILE_NAME = "document-mutation-journal.jsonl"
_BLOCK = re.compile(r"```johnny-boundary\r?\n(.*?)```", re.DOTALL)
_LIST_KEYS: tuple[str, ...] = ("modify", "create", "delete", "forbid")
_WILDCARD_CHARACTERS = ("*", "?", "[")
_GIT_TIMEOUT_SECONDS = 30
_RECURSIVE = "**"


class ChangeKind(str, Enum):
    """The three things a change can do to a path."""

    CREATE = "CREATE"
    MODIFY = "MODIFY"
    DELETE = "DELETE"


class DocumentMutationStatus(str, Enum):
    """Finite outcomes of one integration attempt."""

    INTEGRATED = "INTEGRATED"
    REFUSED = "REFUSED"


class DocumentMutationFailure(str, Enum):
    """Finite reasons an integration is refused.

    The three thresholds carry three different codes on purpose. "Touched a
    file it should not have", "created a file nobody authorised" and "deleted
    something irreversibly" are different failures with different corrections,
    and a single `BOUNDARY_VIOLATION` would erase that distinction at exactly
    the moment somebody needs it.
    """

    REQUEST_INVALID = "REQUEST_INVALID"
    REPOSITORY_UNREADABLE = "REPOSITORY_UNREADABLE"
    TICKET_UNREADABLE = "TICKET_UNREADABLE"
    BOUNDARY_UNDECLARED = "BOUNDARY_UNDECLARED"
    BOUNDARY_UNPARSABLE = "BOUNDARY_UNPARSABLE"
    PATH_NOT_REPOSITORY_RELATIVE = "PATH_NOT_REPOSITORY_RELATIVE"
    REDIRECTION_ENTRY_NOT_ADMISSIBLE = "REDIRECTION_ENTRY_NOT_ADMISSIBLE"
    PATH_FORBIDDEN = "PATH_FORBIDDEN"
    MODIFICATION_OUTSIDE_BOUNDARY = "MODIFICATION_OUTSIDE_BOUNDARY"
    CREATION_NOT_AUTHORIZED = "CREATION_NOT_AUTHORIZED"
    DELETION_NOT_AUTHORIZED = "DELETION_NOT_AUTHORIZED"
    INTEGRATION_FAILED = "INTEGRATION_FAILED"


class BoundaryReadStatus(str, Enum):
    """Absent, broken and readable are three different answers, never two."""

    DECLARED = "DECLARED"
    TICKET_UNREADABLE = "TICKET_UNREADABLE"
    UNDECLARED = "UNDECLARED"
    UNPARSABLE = "UNPARSABLE"


class DocumentBoundary(BaseModel):
    """One ticket's declared authority over paths, as the ticket wrote it.

    `modify` must be non-empty: a ticket that may change nothing has nothing
    to integrate, and an empty envelope is far more likely to be a declaration
    that failed to say anything than a deliberate one. `create`, `delete` and
    `forbid` default to empty, which is the safe default in each case — no
    creation authorised, no deletion authorised, and the allow lists still
    bounding everything.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    modify: tuple[str, ...] = Field(min_length=1)
    create: tuple[str, ...] = ()
    delete: tuple[str, ...] = ()
    forbid: tuple[str, ...] = ()


class DocumentChange(BaseModel):
    """One path, what happened to it, and the Git mode of the written entry."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    path: str
    kind: ChangeKind
    entry_mode: str = "100644"


class DocumentMutationRequest(BaseModel):
    """One proposed integration, named entirely by references Git can resolve.

    `ticket_path` is repository-relative because the ticket is read out of the
    integration branch rather than off disk; an absolute path would invite a
    caller to hand the gate a ticket the repository never accepted.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: int = Field(default=1, ge=1, le=1)
    repository_root: str = Field(min_length=1, max_length=512)
    ticket_path: str = Field(min_length=1, max_length=512)
    integration_branch: str = Field(min_length=1, max_length=256)
    candidate_ref: str = Field(min_length=1, max_length=256)


class DocumentMutationResult(BaseModel):
    """Exactly one integration or one finite, named refusal.

    A refusal names the path as well as the reason. "Something was outside the
    boundary" is not actionable; "`AGENTS.md` was outside the boundary" is.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    status: DocumentMutationStatus
    failure: DocumentMutationFailure | None = None
    offending_path: str | None = None
    detail: str | None = None
    integrated_commit: str | None = None

    @classmethod
    def refused(
        cls,
        failure: DocumentMutationFailure,
        offending_path: str | None = None,
        detail: str | None = None,
    ) -> Self:
        return cls(
            status=DocumentMutationStatus.REFUSED,
            failure=failure,
            offending_path=offending_path,
            detail=detail,
        )


def journal_path(layout: JohnnyRootLayout) -> Path:
    return layout.queue_root / _JOURNAL_FILE_NAME


# --------------------------------------------------------------------------
# Paths: normalisation and matching
# --------------------------------------------------------------------------


def normalize_change_path(raw: str) -> str | None:
    """A repository-relative POSIX path, or None when the input is not one.

    Every rejection here is a case that would otherwise become a match against
    something it is not. `..` is resolved lexically so a traversal cannot ride
    inside an allowed prefix, and a traversal that leaves the repository has
    no repository-relative form at all. A backslash is refused rather than
    treated as text: on Windows it is a separator, and reading it as a literal
    would let `doc\\..\\library` past a component-wise comparison.
    """

    if not raw:
        return None
    if "\\" in raw or "\x00" in raw:
        return None
    if raw.startswith("/") or (len(raw) > 1 and raw[1] == ":"):
        return None
    parts: list[str] = []
    for part in raw.split("/"):
        if part in ("", "."):
            # An empty or bare-dot component means `a//b` or `./a`. Git emits
            # neither, so this is malformed input and smoothing it over would
            # be the guess this module refuses to make.
            return None
        if part == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(part)
    if not parts:
        return None
    return "/".join(parts)


def pattern_components(entry: str) -> tuple[str, ...] | None:
    """Split one declared entry into components, or None when it is malformed.

    A trailing slash is the declaration's way of saying "this directory and
    everything under it" and expands to a recursive component. Without one an
    entry is a path, not a prefix — `doc` does not cover `doc/a.md`, because a
    rule that silently covered a whole tree when the author wrote one file is
    how a boundary grows without anybody widening it.
    """

    if not entry or "\\" in entry or entry.startswith("/"):
        return None
    if entry.endswith("/"):
        entry = entry + _RECURSIVE
    parts = entry.split("/")
    for index, part in enumerate(parts):
        if part in ("", ".", ".."):
            return None
        if part == _RECURSIVE and index != len(parts) - 1:
            # A mid-pattern `**` has a defensible meaning, but no declaration
            # in this repository needs one, and an unused branch of a matcher
            # is an untested branch of a matcher.
            return None
    return tuple(parts)


def _component_matches(component: str, pattern: str, fold: bool) -> bool:
    if fold:
        component = component.casefold()
        pattern = pattern.casefold()
    if any(character in pattern for character in _WILDCARD_CHARACTERS):
        # `fnmatchcase`, never `fnmatch`: the latter normalises case through
        # `os.path.normcase`, which on Windows would quietly turn every allow
        # list into a case-insensitive one.
        return fnmatch.fnmatchcase(component, pattern)
    return component == pattern


def _matches(parts: tuple[str, ...], pattern: tuple[str, ...], fold: bool) -> bool:
    if not pattern:
        return not parts
    head = pattern[0]
    if head == _RECURSIVE:
        return True
    if not parts:
        return False
    if not _component_matches(parts[0], head, fold):
        return False
    return _matches(parts[1:], pattern[1:], fold)


def path_matches_entry(path: str, entry: str, fold: bool) -> bool:
    """Whether one normalised path falls under one declared entry."""

    pattern = pattern_components(entry)
    if pattern is None:
        return False
    return _matches(tuple(path.split("/")), pattern, fold)


def _matches_any(path: str, entries: tuple[str, ...], fold: bool) -> bool:
    return any(path_matches_entry(path, entry, fold) for entry in entries)


# --------------------------------------------------------------------------
# The declaration block
# --------------------------------------------------------------------------


def find_boundary_block(text: str) -> str | None:
    """Return the declared block, or None when the ticket never opted in."""

    match = _BLOCK.search(text)
    return None if match is None else match.group(1)


def parse_boundary_block(body: str) -> DocumentBoundary:
    """Read one declared block. Anything unexpected raises rather than guesses."""

    collected: dict[str, list[str]] = {key: [] for key in _LIST_KEYS}
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"每一行都要是 key = value：{line!r}")
        key, value = (part.strip() for part in line.split("=", 1))
        if key not in collected:
            # A typo would silently drop an entry. Dropping a `forbid` entry
            # turns a prohibition into permission, so this is an error.
            raise ValueError(f"不認得的欄位 {key!r}")
        if not value:
            raise ValueError(f"欄位 {key!r} 的值不能是空的")
        if pattern_components(value) is None:
            raise ValueError(f"欄位 {key!r} 的路徑寫法不合法：{value!r}")
        if value in collected[key]:
            raise ValueError(f"欄位 {key!r} 重複宣告 {value!r}")
        collected[key].append(value)

    for entry in collected["delete"]:
        # Deletion is irreversible, so it does not get to be approximate. An
        # exact path per deleted file means removing a module and its
        # seventeen tests takes eighteen declared lines, which is precisely
        # the friction that failure mode was missing.
        if any(character in entry for character in _WILDCARD_CHARACTERS):
            raise ValueError(f"delete 只接受精確路徑，不得使用萬用字元：{entry!r}")
        if entry.endswith("/") or normalize_change_path(entry) != entry:
            raise ValueError(f"delete 只接受單一檔案的精確路徑：{entry!r}")

    if not collected["modify"]:
        raise ValueError("缺少必要欄位 'modify'：沒有宣告可讀邊界的票不得整合")

    return DocumentBoundary(
        modify=tuple(collected["modify"]),
        create=tuple(collected["create"]),
        delete=tuple(collected["delete"]),
        forbid=tuple(collected["forbid"]),
    )


def read_boundary(text: str) -> tuple[BoundaryReadStatus, DocumentBoundary | None, str | None]:
    """Absent, broken, or declared — the three answers kept apart."""

    body = find_boundary_block(text)
    if body is None:
        return BoundaryReadStatus.UNDECLARED, None, None
    try:
        return BoundaryReadStatus.DECLARED, parse_boundary_block(body), None
    except ValueError as error:
        return BoundaryReadStatus.UNPARSABLE, None, str(error)


# --------------------------------------------------------------------------
# The three thresholds
# --------------------------------------------------------------------------

_KIND_FAILURE = {
    ChangeKind.MODIFY: DocumentMutationFailure.MODIFICATION_OUTSIDE_BOUNDARY,
    ChangeKind.CREATE: DocumentMutationFailure.CREATION_NOT_AUTHORIZED,
    ChangeKind.DELETE: DocumentMutationFailure.DELETION_NOT_AUTHORIZED,
}

# A blob or an executable blob is content. Mode 120000 is a symlink and 160000
# is a gitlink: both are redirections, and admitting one by its own path
# admits whatever it points at, which the gate cannot see or bound.
_CONTENT_MODES = frozenset({"100644", "100755"})


def evaluate_change(
    boundary: DocumentBoundary, change: DocumentChange
) -> DocumentMutationFailure | None:
    """The whole rule for one change, in the order the rule is written."""

    path = normalize_change_path(change.path)
    if path is None:
        return DocumentMutationFailure.PATH_NOT_REPOSITORY_RELATIVE
    if change.kind is not ChangeKind.DELETE and change.entry_mode not in _CONTENT_MODES:
        return DocumentMutationFailure.REDIRECTION_ENTRY_NOT_ADMISSIBLE
    if _matches_any(path, boundary.forbid, fold=True):
        return DocumentMutationFailure.PATH_FORBIDDEN
    allowed = {
        ChangeKind.MODIFY: boundary.modify,
        ChangeKind.CREATE: boundary.create,
        ChangeKind.DELETE: boundary.delete,
    }[change.kind]
    if not _matches_any(path, allowed, fold=False):
        return _KIND_FAILURE[change.kind]
    return None


def evaluate_changes(
    boundary: DocumentBoundary, changes: tuple[DocumentChange, ...]
) -> tuple[DocumentMutationFailure | None, str | None]:
    """The first refusal in a deterministic order, or nothing to refuse.

    An empty change set is admitted: no path left the boundary, because no
    path moved. Whether that is worth integrating is not this gate's question.
    """

    for change in sorted(changes, key=lambda item: (item.path, item.kind.value)):
        failure = evaluate_change(boundary, change)
        if failure is not None:
            return failure, change.path
    return None, None


# --------------------------------------------------------------------------
# Git: the facts nobody in the request gets to supply
# --------------------------------------------------------------------------


def _git(repository_root: Path, *arguments: str) -> bytes | None:
    """Run one Git command for one fact. Bytes out: these paths carry CJK."""

    try:
        completed = subprocess.run(
            ("git", "-C", str(repository_root), *arguments),
            check=False,
            capture_output=True,
            shell=False,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def _decode(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace")


def parse_raw_diff(payload: bytes) -> tuple[DocumentChange, ...] | None:
    """Turn `git diff --raw -z` output into changes, or None when it is not that.

    A rename is deliberately decomposed into a deletion and a creation. It is
    both, it needs both authorisations, and a ticket that may rename a file it
    was never allowed to delete is the deletion threshold with a new name.
    """

    tokens = payload.split(b"\x00")
    changes: list[DocumentChange] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if not token:
            continue
        if not token.startswith(b":"):
            return None
        fields = _decode(token[1:]).split(" ")
        if len(fields) != 5:
            return None
        source_mode, target_mode, _, _, status = fields
        if not status:
            return None
        letter = status[0]
        if index >= len(tokens):
            return None
        first = _decode(tokens[index])
        index += 1
        # An entry with no path is not an entry. Letting it through would
        # produce a change whose path is the empty string, and the empty
        # string is refused downstream for a completely different reason —
        # a fail-closed answer that names the wrong cause.
        if not first:
            return None
        if letter in ("R", "C"):
            if index >= len(tokens):
                return None
            second = _decode(tokens[index])
            index += 1
            if not second:
                return None
            if letter == "R":
                changes.append(
                    DocumentChange(
                        path=first, kind=ChangeKind.DELETE, entry_mode=source_mode
                    )
                )
            changes.append(
                DocumentChange(
                    path=second, kind=ChangeKind.CREATE, entry_mode=target_mode
                )
            )
            continue
        if letter == "A":
            kind, mode = ChangeKind.CREATE, target_mode
        elif letter == "D":
            kind, mode = ChangeKind.DELETE, source_mode
        elif letter in ("M", "T"):
            kind, mode = ChangeKind.MODIFY, target_mode
        else:
            # `U` (unmerged) and `X` (unknown) mean the diff is not a
            # statement about a finished change. Refusing to read it is the
            # fail-closed answer; inventing a kind for it is not.
            return None
        changes.append(DocumentChange(path=first, kind=kind, entry_mode=mode))
    return tuple(changes)


def _journal(
    layout: JohnnyRootLayout,
    request: DocumentMutationRequest | None,
    outcome: str,
    offending_path: str | None,
    detail: str | None,
) -> None:
    """Append one audit line; journaling failure never blocks the outcome."""

    entry = {
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "principal": getpass.getuser(),
        "ticket_path": request.ticket_path if request is not None else None,
        "integration_branch": (
            request.integration_branch if request is not None else None
        ),
        "candidate_ref": request.candidate_ref if request is not None else None,
        "outcome": outcome,
        "offending_path": offending_path,
        "detail": detail,
    }
    try:
        path = journal_path(layout)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
    except OSError:
        pass


def _refuse(
    layout: JohnnyRootLayout,
    request: DocumentMutationRequest | None,
    failure: DocumentMutationFailure,
    offending_path: str | None = None,
    detail: str | None = None,
) -> DocumentMutationResult:
    _journal(layout, request, failure.value, offending_path, detail)
    return DocumentMutationResult.refused(failure, offending_path, detail)


def admit_document_mutation(
    layout: JohnnyRootLayout, request: DocumentMutationRequest
) -> DocumentMutationResult:
    """Integrate one candidate branch into `main`, or refuse without touching it.

    Every return above the final merge has executed no Git mutation. That is
    the property the whole module exists for, and it is why the merge is the
    last statement rather than something a caller is trusted to skip.
    """

    if type(request) is not DocumentMutationRequest:
        return _refuse(layout, None, DocumentMutationFailure.REQUEST_INVALID)

    root = Path(request.repository_root)
    if not root.is_absolute() or not root.is_dir():
        return _refuse(
            layout,
            request,
            DocumentMutationFailure.REPOSITORY_UNREADABLE,
            detail="repository root is not an absolute directory",
        )

    head = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if head is None or _decode(head).strip() != request.integration_branch:
        return _refuse(
            layout,
            request,
            DocumentMutationFailure.REPOSITORY_UNREADABLE,
            detail="the integration branch is not the checked-out branch",
        )

    status = _git(root, "status", "--porcelain")
    if status is None:
        return _refuse(
            layout,
            request,
            DocumentMutationFailure.REPOSITORY_UNREADABLE,
            detail="the working tree state is unreadable",
        )
    if _decode(status).strip():
        # Uncommitted content in the integration worktree is content nobody
        # judged, sitting where the merge lands.
        return _refuse(
            layout,
            request,
            DocumentMutationFailure.REPOSITORY_UNREADABLE,
            detail="the integration worktree is not clean",
        )

    # The declaration comes from the branch being integrated *into*. Reading it
    # from the candidate would let the change under judgement rewrite the rule
    # it is judged by.
    ticket = _git(
        root, "show", f"{request.integration_branch}:{request.ticket_path}"
    )
    if ticket is None:
        return _refuse(
            layout, request, DocumentMutationFailure.TICKET_UNREADABLE,
            offending_path=request.ticket_path,
        )

    read_status, boundary, reason = read_boundary(_decode(ticket))
    if read_status is BoundaryReadStatus.UNDECLARED:
        return _refuse(
            layout, request, DocumentMutationFailure.BOUNDARY_UNDECLARED,
            offending_path=request.ticket_path,
        )
    if read_status is not BoundaryReadStatus.DECLARED or boundary is None:
        return _refuse(
            layout,
            request,
            DocumentMutationFailure.BOUNDARY_UNPARSABLE,
            offending_path=request.ticket_path,
            detail=reason,
        )

    base = _git(root, "merge-base", request.integration_branch, request.candidate_ref)
    if base is None:
        return _refuse(
            layout,
            request,
            DocumentMutationFailure.REPOSITORY_UNREADABLE,
            detail="the candidate shares no history with the integration branch",
        )

    payload = _git(
        root,
        "diff",
        "--raw",
        "--no-renames",
        "-z",
        _decode(base).strip(),
        request.candidate_ref,
    )
    if payload is None:
        return _refuse(
            layout,
            request,
            DocumentMutationFailure.REPOSITORY_UNREADABLE,
            detail="the candidate's changes are unreadable",
        )
    changes = parse_raw_diff(payload)
    if changes is None:
        return _refuse(
            layout,
            request,
            DocumentMutationFailure.REPOSITORY_UNREADABLE,
            detail="the candidate's changes did not parse",
        )

    failure, offending_path = evaluate_changes(boundary, changes)
    if failure is not None:
        return _refuse(layout, request, failure, offending_path)

    merged = _git(root, "merge", "--ff-only", request.candidate_ref)
    if merged is None:
        return _refuse(
            layout,
            request,
            DocumentMutationFailure.INTEGRATION_FAILED,
            detail="the candidate does not fast-forward the integration branch",
        )
    landed = _git(root, "rev-parse", "HEAD")
    if landed is None:
        return _refuse(
            layout,
            request,
            DocumentMutationFailure.REPOSITORY_UNREADABLE,
            detail="the integrated commit is unreadable",
        )
    commit = _decode(landed).strip()
    _journal(layout, request, DocumentMutationStatus.INTEGRATED.value, None, commit)
    return DocumentMutationResult(
        status=DocumentMutationStatus.INTEGRATED, integrated_commit=commit
    )


__all__ = [
    "BoundaryReadStatus",
    "ChangeKind",
    "DocumentBoundary",
    "DocumentChange",
    "DocumentMutationFailure",
    "DocumentMutationRequest",
    "DocumentMutationResult",
    "DocumentMutationStatus",
    "admit_document_mutation",
    "evaluate_change",
    "evaluate_changes",
    "find_boundary_block",
    "journal_path",
    "normalize_change_path",
    "parse_boundary_block",
    "parse_raw_diff",
    "path_matches_entry",
    "pattern_components",
    "read_boundary",
]
