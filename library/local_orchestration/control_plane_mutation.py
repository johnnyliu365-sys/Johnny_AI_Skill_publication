"""Judge the control plane's own integrations, on a door only it may use.

`document_mutation_gate` governs implementers: a candidate may touch only what
its ticket declared. It has never seen a control-plane commit, because the
control plane does not go through it — it fast-forwards `main` from its own
worktree. Sixty-two of the seventy-six commits on `main` since that gate was
written arrived that way: tickets, dispatch bindings, releases, docs. The gate
that exists to stop undeclared writes was, from its first day, blind to the
role that has caused the most incidents in this repository.

This module is that gate's sister, not its clone. **The rules are different on
purpose.** An implementer may not write `modules/tickets/`; the control plane
must be able to, because opening tickets is its job. A door that made opening
a ticket impossible would not be a stricter gate, it would be a broken one. So
this entry asks for no ticket and no declared boundary. What it takes instead
is attribution, a durable record, and a small set of rules the control plane
does not get to break either.

**The standard of proof is the same as the sister gate's.** Every return above
the merge has executed no Git mutation, so a refusal leaves `main` at the
commit it was already at. Every path comparison is the sister module's,
imported rather than re-implemented, so `modules/tickets-archive/` cannot be
mistaken for `modules/tickets/` at one door and not the other.

**The two doors are not interchangeable, and that is asserted twice.** By
identity: both entries test `type(request) is` their own request class, so
neither will read the other's request even though the two are structurally
close. By namespace: this entry admits only candidates under `control/`, and
separately refuses any ref carrying an implementer namespace as a component,
so `control/implement/gov-19` is not a way back in. Both run before the
repository is touched at all — a candidate at the wrong door should not cause
this gate to go looking at anything.

**The control plane's own two rules.**

*One commit must not change both the rule and what the rule governs.* A commit
touching `library/` and `modules/tickets/` together is the exact shape of
editing the rulebook and the thing it judges in a single indivisible unit —
nobody can review one half without accepting the other. The rule is per commit,
not per candidate, because the commit is the unit a reviewer reads; two commits
doing the two things are separately reviewable and stay admissible.

*A pinned policy document must arrive with its pins.* Seven references are
frozen by digest in `profile.py` and in the router regression test. Editing one
without repinning both sites ships a policy the router believes is a different
policy. The control plane has missed that step twice, both times by committing
without running the suite, so this door recomputes the digest from the content
at the candidate rather than checking that the pinning file was merely touched.

**Journaling comes before the merge, not after.** The sister gate's journal is
best effort: it records what happened, and a failed write loses the record but
not the outcome. Here a lost record *is* the outcome being wrong — the point of
this door is that no commit reaches `main` unjudged and unrecorded — so the
admission line, naming the exact commit `main` is about to become, is written
first and a failure to write it refuses the integration. Nothing is integrated
before it is written down.

**What this is, honestly.** It is not a cryptographic boundary. Anything in the
same process could run `git merge` itself, and a control-plane operator who
points a `control/` ref at an implementer branch has deliberately walked
through the wrong door carrying the wrong thing. What it buys is that the
sanctioned route cannot move an unrecorded, unattributed or self-contradictory
change into `main`, and that every refusal is named, attributed and durable.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field

from .document_mutation_gate import (
    ChangeKind,
    DocumentChange,
    journal_path,
    normalize_change_path,
    parse_raw_diff,
)
from .johnny_root_layout import JohnnyRootLayout

_GIT_TIMEOUT_SECONDS = 30

#: The one namespace this door admits. Compared exactly: a ref is a name the
#: control plane chose, and choosing `Control/x` is choosing a different name.
_CONTROL_PLANE_NAMESPACE = "control/"

#: Namespace roots that belong to the other door. Checked as whole components
#: anywhere in the ref, not as a leading prefix, because the leading position
#: is already decided by the allow list — a prohibition that could only ever
#: agree with the allow list would be a branch nothing reaches. What this
#: catches is the legible form of the bypass: re-parenting an implementer
#: branch under this door as `control/implement/…`. Compared case-folded, for
#: the reason the sister gate folds its forbid list; compared component-wise,
#: so `control/codex-notes` is a note and not a namespace.
_IMPLEMENTER_ROOTS: frozenset[str] = frozenset({"implement", "codex"})

#: The rule, and the thing the rule governs.
_RULE_TREE = "library"
_SUBJECT_TREE = "modules/tickets"

#: Where the digest-pinned policy documents live, and the two files that must
#: agree with them. Both sites are named in governance ticket 17; a repin that
#: lands in only one of them is the failure this rule exists for.
_POLICY_DIRECTORY = "skills/johnny-project-takeover/references"
_PROFILE_PATH = "library/workflow_router/profile.py"
_PROFILE_TEST_PATH = "tests/test_workflow_router.py"

_PIN = re.compile(
    r'reference_id="(?P<identifier>[A-Za-z0-9_-]+)",\s*'
    r'source_revision="(?P<revision>rev-[0-9a-f]{16})",\s*'
    r'content_digest="(?P<digest>sha256_[0-9a-f]{64})"'
)

#: A blob or an executable blob is content. 120000 is a symlink and 160000 a
#: gitlink: both redirect to something this door cannot see or bound.
_CONTENT_MODES = frozenset({"100644", "100755"})


class ControlPlaneMutationStatus(str, Enum):
    """Finite outcomes of one control-plane integration attempt."""

    INTEGRATED = "INTEGRATED"
    REFUSED = "REFUSED"


class ControlPlaneMutationFailure(str, Enum):
    """Finite reasons a control-plane integration is refused.

    Every reason is separate because every reason has a different correction.
    "Nothing to integrate", "you are at the wrong door" and "you forgot to
    repin" are not one failure, and collapsing them would erase the answer at
    the moment somebody needs it.
    """

    REQUEST_INVALID = "REQUEST_INVALID"
    PRINCIPAL_UNDECLARED = "PRINCIPAL_UNDECLARED"
    PRINCIPAL_NOT_HOST = "PRINCIPAL_NOT_HOST"
    CANDIDATE_NOT_CONTROL_PLANE = "CANDIDATE_NOT_CONTROL_PLANE"
    REPOSITORY_UNREADABLE = "REPOSITORY_UNREADABLE"
    NOTHING_TO_INTEGRATE = "NOTHING_TO_INTEGRATE"
    PATH_NOT_REPOSITORY_RELATIVE = "PATH_NOT_REPOSITORY_RELATIVE"
    REDIRECTION_ENTRY_NOT_ADMISSIBLE = "REDIRECTION_ENTRY_NOT_ADMISSIBLE"
    RULE_AND_SUBJECT_IN_ONE_CHANGE = "RULE_AND_SUBJECT_IN_ONE_CHANGE"
    POLICY_REPIN_STALE = "POLICY_REPIN_STALE"
    JOURNAL_UNWRITABLE = "JOURNAL_UNWRITABLE"
    INTEGRATION_FAILED = "INTEGRATION_FAILED"


class ControlPlaneMutationRequest(BaseModel):
    """One proposed control-plane integration.

    There is deliberately no ticket field. The control plane's changes are not
    all ticketed — the first ticket of a series cannot cite a ticket that does
    not exist yet — and requiring one here would turn a gate into a deadlock.
    Attribution and a record are what this door asks for instead.

    This class is not interchangeable with `DocumentMutationRequest` even
    though the two carry overlapping fields. That is the point: each gate
    tests for its own type by identity, so neither can be driven by the
    other's request.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: int = Field(default=1, ge=1, le=1)
    repository_root: str = Field(min_length=1, max_length=512)
    integration_branch: str = Field(min_length=1, max_length=256)
    candidate_ref: str = Field(min_length=1, max_length=256)
    principal: str = Field(min_length=1, max_length=128)


class ControlPlaneMutationResult(BaseModel):
    """Exactly one integration, or one finite, named refusal."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    status: ControlPlaneMutationStatus
    failure: ControlPlaneMutationFailure | None = None
    offending_path: str | None = None
    detail: str | None = None
    integrated_commit: str | None = None

    @classmethod
    def refused(
        cls,
        failure: ControlPlaneMutationFailure,
        offending_path: str | None = None,
        detail: str | None = None,
    ) -> Self:
        return cls(
            status=ControlPlaneMutationStatus.REFUSED,
            failure=failure,
            offending_path=offending_path,
            detail=detail,
        )


# --------------------------------------------------------------------------
# Namespace: which door a candidate belongs at
# --------------------------------------------------------------------------


def candidate_is_control_plane(candidate_ref: str) -> bool:
    """Whether one ref name belongs at this door rather than the other one.

    Two rules, and they refuse different things. The prohibition runs first
    and case-folded: no component of the ref may be an implementer namespace,
    which refuses both `implement/x` and the re-parented `control/implement/x`.
    The permission runs second and exact: the ref must sit under `control/`,
    and `CONTROL/x` is a name nobody declared.
    """

    components = candidate_ref.split("/")
    if any(component.casefold() in _IMPLEMENTER_ROOTS for component in components):
        return False
    return candidate_ref.startswith(_CONTROL_PLANE_NAMESPACE) and len(
        candidate_ref
    ) > len(_CONTROL_PLANE_NAMESPACE)


# --------------------------------------------------------------------------
# Rule one: the rule and its subject may not move together
# --------------------------------------------------------------------------


def _under(path: str, tree: str) -> bool:
    """Whether a normalised path lies inside one tree.

    The separator is part of the comparison, which is the whole of defect
    class 1: `modules/tickets-archive/x.md` is not under `modules/tickets`,
    and `libraryx/y.py` is not under `library`. A bare `library` file at the
    root is not the tree either, so equality does not count.
    """

    return path.startswith(tree + "/")


def mixed_change_failure(paths: tuple[str, ...]) -> tuple[str, str] | None:
    """The offending pair when one commit moves both trees, else None.

    Returns the `library/` path that offends and, as detail, the ticket path
    it moved with. Both are the sorted-first of their side so the answer is
    the same on every run.
    """

    rule = sorted(path for path in paths if _under(path, _RULE_TREE))
    subject = sorted(path for path in paths if _under(path, _SUBJECT_TREE))
    if not rule or not subject:
        return None
    return rule[0], subject[0]


# --------------------------------------------------------------------------
# Rule two: a pinned policy document arrives with its pins
# --------------------------------------------------------------------------


def policy_document_id(path: str) -> str | None:
    """The pinned reference id one path could carry, or None.

    A document is a candidate for pinning when it is a Markdown file directly
    inside the references directory. Whether it is actually pinned is decided
    by the pins themselves, because only seven of the eighteen documents there
    are pinned and a hard-coded list of seven would drift the first time an
    eighth was added.
    """

    prefix = _POLICY_DIRECTORY + "/"
    if not path.startswith(prefix) or not path.endswith(".md"):
        return None
    stem = path[len(prefix) : -len(".md")]
    if not stem or "/" in stem:
        return None
    return stem


def policy_pins(profile_text: str) -> dict[str, tuple[str, str]]:
    """Every `(revision, digest)` the pinning module declares, by reference id."""

    return {
        match.group("identifier"): (match.group("revision"), match.group("digest"))
        for match in _PIN.finditer(profile_text)
    }


def policy_digest(raw: bytes) -> tuple[str, str]:
    """The revision and digest one document's bytes must be pinned as.

    Line endings are normalised to LF first. The working copy is CRLF and the
    repository is not, so a digest taken over the raw bytes would depend on
    which machine ran it — a check that answers differently per host is not a
    check.
    """

    hexdigest = hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()
    return "rev-" + hexdigest[:16], "sha256_" + hexdigest


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


def _changes_between(root: Path, first: str, second: str) -> tuple[DocumentChange, ...] | None:
    payload = _git(root, "diff", "--raw", "--no-renames", "-z", first, second)
    if payload is None:
        return None
    return parse_raw_diff(payload)


# --------------------------------------------------------------------------
# The journal: written before the merge, never after it
# --------------------------------------------------------------------------


def _append_journal(
    layout: JohnnyRootLayout,
    request: ControlPlaneMutationRequest | None,
    outcome: str,
    *,
    candidate_commit: str | None = None,
    changed_paths: tuple[str, ...] = (),
    offending_path: str | None = None,
    detail: str | None = None,
) -> bool:
    """Append one audit line. False means the record did not reach the disk."""

    entry = {
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "door": "CONTROL_PLANE",
        "principal": request.principal if request is not None else None,
        "host_principal": getpass.getuser(),
        "integration_branch": (
            request.integration_branch if request is not None else None
        ),
        "candidate_ref": request.candidate_ref if request is not None else None,
        "candidate_commit": candidate_commit,
        "changed_paths": list(changed_paths),
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
        return False
    return True


def _refuse(
    layout: JohnnyRootLayout,
    request: ControlPlaneMutationRequest | None,
    failure: ControlPlaneMutationFailure,
    offending_path: str | None = None,
    detail: str | None = None,
    changed_paths: tuple[str, ...] = (),
) -> ControlPlaneMutationResult:
    """Record and return a refusal.

    A refusal that cannot be journalled stays a refusal: the safe outcome has
    already happened and `main` has not moved. Only the admission line's write
    can change an outcome, and it changes it towards refusing.
    """

    _append_journal(
        layout,
        request,
        failure.value,
        changed_paths=changed_paths,
        offending_path=offending_path,
        detail=detail,
    )
    return ControlPlaneMutationResult.refused(failure, offending_path, detail)


def admit_control_plane_mutation(
    layout: JohnnyRootLayout, request: ControlPlaneMutationRequest
) -> ControlPlaneMutationResult:
    """Integrate one control-plane candidate into `main`, or refuse untouched.

    The order is fixed and each step only becomes answerable once the one
    before it holds: an object that is not a request has no fields to read; a
    principal nobody claimed cannot be attributed; a candidate at the wrong
    door should never cause this repository to be inspected at all; a change
    set cannot be judged before it can be read; and nothing may be integrated
    before the decision is on disk. Every return above the merge has executed
    no Git mutation.
    """

    if type(request) is not ControlPlaneMutationRequest:
        return _refuse(layout, None, ControlPlaneMutationFailure.REQUEST_INVALID)

    if not request.principal.strip():
        return _refuse(
            layout, request, ControlPlaneMutationFailure.PRINCIPAL_UNDECLARED
        )
    host = getpass.getuser()
    if request.principal != host:
        # A journal line attributed to somebody who was not at this machine is
        # worse than no line: it is a record that reads as evidence.
        return _refuse(
            layout,
            request,
            ControlPlaneMutationFailure.PRINCIPAL_NOT_HOST,
            detail="the declared principal is not the host principal",
        )

    if not candidate_is_control_plane(request.candidate_ref):
        return _refuse(
            layout,
            request,
            ControlPlaneMutationFailure.CANDIDATE_NOT_CONTROL_PLANE,
            detail=(
                "this door integrates only the "
                f"{_CONTROL_PLANE_NAMESPACE!r} namespace"
            ),
        )

    root = Path(request.repository_root)
    if not root.is_absolute() or not root.is_dir():
        return _refuse(
            layout,
            request,
            ControlPlaneMutationFailure.REPOSITORY_UNREADABLE,
            detail="repository root is not an absolute directory",
        )

    head = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if head is None or _decode(head).strip() != request.integration_branch:
        return _refuse(
            layout,
            request,
            ControlPlaneMutationFailure.REPOSITORY_UNREADABLE,
            detail="the integration branch is not the checked-out branch",
        )

    status = _git(root, "status", "--porcelain")
    if status is None:
        return _refuse(
            layout,
            request,
            ControlPlaneMutationFailure.REPOSITORY_UNREADABLE,
            detail="the working tree state is unreadable",
        )
    if _decode(status).strip():
        return _refuse(
            layout,
            request,
            ControlPlaneMutationFailure.REPOSITORY_UNREADABLE,
            detail="the integration worktree is not clean",
        )

    resolved = _git(root, "rev-parse", "--verify", f"{request.candidate_ref}^{{commit}}")
    if resolved is None:
        return _refuse(
            layout,
            request,
            ControlPlaneMutationFailure.REPOSITORY_UNREADABLE,
            detail="the candidate ref does not name a commit",
        )
    candidate_commit = _decode(resolved).strip()

    base = _git(root, "merge-base", request.integration_branch, request.candidate_ref)
    if base is None:
        return _refuse(
            layout,
            request,
            ControlPlaneMutationFailure.REPOSITORY_UNREADABLE,
            detail="the candidate shares no history with the integration branch",
        )
    merge_base = _decode(base).strip()

    changes = _changes_between(root, merge_base, request.candidate_ref)
    if changes is None:
        return _refuse(
            layout,
            request,
            ControlPlaneMutationFailure.REPOSITORY_UNREADABLE,
            detail="the candidate's changes are unreadable",
        )
    if not changes:
        return _refuse(
            layout,
            request,
            ControlPlaneMutationFailure.NOTHING_TO_INTEGRATE,
            detail="the candidate changes nothing the integration branch does not have",
        )

    normalised: list[str] = []
    for change in sorted(changes, key=lambda item: (item.path, item.kind.value)):
        path = normalize_change_path(change.path)
        if path is None:
            return _refuse(
                layout,
                request,
                ControlPlaneMutationFailure.PATH_NOT_REPOSITORY_RELATIVE,
                offending_path=change.path,
            )
        if change.kind is not ChangeKind.DELETE and change.entry_mode not in _CONTENT_MODES:
            return _refuse(
                layout,
                request,
                ControlPlaneMutationFailure.REDIRECTION_ENTRY_NOT_ADMISSIBLE,
                offending_path=path,
            )
        normalised.append(path)
    changed_paths = tuple(sorted(set(normalised)))

    commits = _git(root, "rev-list", "--reverse", f"{merge_base}..{request.candidate_ref}")
    if commits is None:
        return _refuse(
            layout,
            request,
            ControlPlaneMutationFailure.REPOSITORY_UNREADABLE,
            detail="the candidate's commits are unreadable",
            changed_paths=changed_paths,
        )
    for commit in _decode(commits).split():
        per_commit = _changes_between(root, f"{commit}^", commit)
        if per_commit is None:
            return _refuse(
                layout,
                request,
                ControlPlaneMutationFailure.REPOSITORY_UNREADABLE,
                detail=f"the changes of {commit} are unreadable",
                changed_paths=changed_paths,
            )
        paths = tuple(
            normalized
            for normalized in (
                normalize_change_path(change.path) for change in per_commit
            )
            if normalized is not None
        )
        offending = mixed_change_failure(paths)
        if offending is not None:
            rule_path, subject_path = offending
            return _refuse(
                layout,
                request,
                ControlPlaneMutationFailure.RULE_AND_SUBJECT_IN_ONE_CHANGE,
                offending_path=rule_path,
                detail=f"{commit} also changed {subject_path}",
                changed_paths=changed_paths,
            )

    repin = _repin_failure(root, request.candidate_ref, changed_paths)
    if repin is not None:
        offending_path, detail = repin
        return _refuse(
            layout,
            request,
            ControlPlaneMutationFailure.POLICY_REPIN_STALE,
            offending_path=offending_path,
            detail=detail,
            changed_paths=changed_paths,
        )

    # The decision goes to disk before `main` moves, naming the exact commit
    # `main` is about to become. If this line cannot be written, the
    # integration does not happen: an unrecorded commit on `main` is the one
    # thing this door exists to prevent.
    if not _append_journal(
        layout,
        request,
        "ADMITTED",
        candidate_commit=candidate_commit,
        changed_paths=changed_paths,
    ):
        return ControlPlaneMutationResult.refused(
            ControlPlaneMutationFailure.JOURNAL_UNWRITABLE,
            detail="the decision could not be recorded, so it was not acted on",
        )

    merged = _git(root, "merge", "--ff-only", request.candidate_ref)
    if merged is None:
        return _refuse(
            layout,
            request,
            ControlPlaneMutationFailure.INTEGRATION_FAILED,
            detail="the candidate does not fast-forward the integration branch",
            changed_paths=changed_paths,
        )
    landed = _git(root, "rev-parse", "HEAD")
    if landed is None or _decode(landed).strip() != candidate_commit:
        return _refuse(
            layout,
            request,
            ControlPlaneMutationFailure.INTEGRATION_FAILED,
            detail="the integration branch did not land on the admitted commit",
            changed_paths=changed_paths,
        )
    _append_journal(
        layout,
        request,
        ControlPlaneMutationStatus.INTEGRATED.value,
        candidate_commit=candidate_commit,
        changed_paths=changed_paths,
    )
    return ControlPlaneMutationResult(
        status=ControlPlaneMutationStatus.INTEGRATED,
        integrated_commit=candidate_commit,
    )


def _repin_failure(
    root: Path, candidate_ref: str, changed_paths: tuple[str, ...]
) -> tuple[str, str] | None:
    """`(path, detail)` when a pinned document arrived without its pins.

    The digest is recomputed from the content at the candidate rather than
    inferred from the pinning file having been touched. Touching `profile.py`
    for an unrelated reason is not a repin, and the two misses this rule was
    written for were both wrong values rather than absent edits.
    """

    candidates = tuple(
        path for path in changed_paths if policy_document_id(path) is not None
    )
    if not candidates:
        return None

    profile = _git(root, "show", f"{candidate_ref}:{_PROFILE_PATH}")
    if profile is None:
        return candidates[0], f"{_PROFILE_PATH} is unreadable at the candidate"
    pins = policy_pins(_decode(profile))
    regression = _git(root, "show", f"{candidate_ref}:{_PROFILE_TEST_PATH}")
    if regression is None:
        return candidates[0], f"{_PROFILE_TEST_PATH} is unreadable at the candidate"
    regression_text = _decode(regression)

    for path in candidates:
        identifier = policy_document_id(path)
        assert identifier is not None
        pinned = pins.get(identifier)
        if pinned is None:
            # A document in that directory that nobody pinned. Eleven of the
            # eighteen are exactly that, and inventing a pin for them would
            # refuse edits no rule ever restricted.
            continue
        body = _git(root, "show", f"{candidate_ref}:{path}")
        if body is None:
            return path, "a pinned policy document is unreadable at the candidate"
        revision, digest = policy_digest(body)
        if pinned != (revision, digest):
            return path, f"{_PROFILE_PATH} pins {pinned[0]}, the content is {revision}"
        if revision not in regression_text or digest not in regression_text:
            return path, f"{_PROFILE_TEST_PATH} was not repinned to {revision}"
    return None


__all__ = [
    "ControlPlaneMutationFailure",
    "ControlPlaneMutationRequest",
    "ControlPlaneMutationResult",
    "ControlPlaneMutationStatus",
    "admit_control_plane_mutation",
    "candidate_is_control_plane",
    "mixed_change_failure",
    "policy_digest",
    "policy_document_id",
    "policy_pins",
]
