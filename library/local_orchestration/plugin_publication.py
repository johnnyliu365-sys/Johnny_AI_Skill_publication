"""Turn the declared payload into the tree a pinned commit actually carries.

The plugin manifest declares what the plugin publishes.  Nothing in this module
knows what that declaration says: every path it handles is read out of the
manifest it is handed, so a change to the declaration is the only way to change
the tree that comes out.  A second enumeration living here would be a second
truth, and two truths drift.

Four failures are named separately, because "the answer could not be computed"
must never arrive looking like "the answer is: they match".

``PayloadDeclarationError``
    the declaration is absent, unreadable, or itself illegal.
``PublicationTreeError``
    the tree could not be enumerated, read, or written.
``PinnedCommitError``
    the pinned object id names no commit in this repository.
``PublicationMismatchError``
    the pinned commit's tree is not the declared payload.

One declared path cannot be bound by content, and the reason is structural
rather than an oversight: the file that records the pin is itself inside the
tree the pin names, so requiring it to be byte-identical would require a commit
whose content states its own object id.  Two things follow, and both are
enforced here.

The published copy records an id that names nothing.  Shipping the *previous*
release's id instead would be worse than a placeholder, because it is a live
pin: anyone feeding the shipped copy back in as a marketplace would install
whatever that older id points at -- which, for the release this mechanism
replaces, is the entire development repository.  An id that resolves to nothing
fails closed instead.

Because the published copy no longer depends on what the pin will become, the
commit is a function of the declared content again: publishing twice in a row
produces the same object id instead of chasing its own tail.

The exemption is then bound by a rule stricter than equality -- the published
copy must record the placeholder, and substituting the real pin for it must
reproduce the working copy byte for byte -- so nothing else can hide behind it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final, Mapping, NewType, Sequence

PushableRefName = NewType("PushableRefName", str)
RemoteTrackingRefName = NewType("RemoteTrackingRefName", str)

__all__ = [
    "PayloadDeclarationError",
    "PinnedCommitError",
    "LocalPublicationReachability",
    "PublicationDiff",
    "PublicationError",
    "PublicationMismatchError",
    "PublicationReachability",
    "PublicationReachabilityError",
    "PublicationRefError",
    "PublicationRefQueryError",
    "PinCarrierMode",
    "PinCarrierNormalization",
    "PublicationTreeError",
    "PushableRefName",
    "RemotePublicationReachability",
    "RemoteTrackingRefName",
    "assert_commit_matches_declaration",
    "commit_exists",
    "compare_commit_to_declaration",
    "declared_blob_ids",
    "declared_payload_files",
    "declared_payload_paths",
    "is_payload_path",
    "load_payload_declaration",
    "materialise_publication_tree",
    "pinned_plugin_source",
    "publication_refs_reaching_commit",
    "publication_commit_message",
    "read_plugin_manifest",
    "repin_marketplace",
    "normalize_pin_carrier",
    "heal_pin_carrier",
    "require_existing_commit",
    "require_fetchable_publication_ref",
    "require_reachable_publication_ref",
    "tree_blob_ids",
    "write_publication_commit",
]

_FULL_SHA: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{40}\Z")
_MOVING_REFS: Final[frozenset[str]] = frozenset(
    {"main", "master", "head", "trunk", "default", "latest", "tip"}
)
_PUSHABLE_REF_PREFIXES: Final[tuple[str, ...]] = ("refs/heads/", "refs/tags/")
_REMOTE_TRACKING_REF_PREFIX: Final[str] = "refs/remotes/"
_REF_ALLOWED: Final[re.Pattern[str]] = re.compile(
    r"refs/(?:heads|tags)/[A-Za-z0-9][A-Za-z0-9._/-]*\Z"
)
_REMOTE_REF_ALLOWED: Final[re.Pattern[str]] = re.compile(
    r"refs/remotes/[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._/-]*\Z"
)

# The three development trees a plugin user can never reach a use for.  Held as
# segment tuples so that the ticket register is expressible without also
# excluding its sibling directories, and so that a directory whose name merely
# begins with an excluded one cannot match.  This is an exclusion policy, not a
# payload enumeration: it says what may never ship, never what does.
_EXCLUDED_PREFIXES: Final[tuple[tuple[str, ...], ...]] = (
    ("tests",),
    ("doc",),
    ("modules", "tickets"),
)

# A synthetic, stable committer identity.  The publication commit must be a pure
# function of the declared content, so wall-clock time and the operator's own
# identity are both kept out of it: re-running the step on unchanged content has
# to reproduce the same object id, or "someone ran it once" becomes the proof.
_FIXED_DATE: Final[str] = "@0 +0000"

# The id recorded by the published copy of the file that records the pin.  It is
# well-formed and names nothing, so the shipped copy cannot be used to install
# anything at all -- least of all the release this mechanism exists to stop.
_UNPINNABLE: Final[str] = "0" * 40


class PublicationError(Exception):
    """Base class for every way publication can fail."""


class PayloadDeclarationError(PublicationError, ValueError):
    """Raised when the declaration or the pin it records is itself illegal."""


class PublicationTreeError(PublicationError, ValueError):
    """Raised when the tree cannot be enumerated, read, or written.

    Never degraded to an empty result: an unreadable tree is not an empty one,
    and a comparison against an empty set would report a match.
    """


class PinnedCommitError(PublicationError, ValueError):
    """Raised when the pinned object id names no commit in this repository."""


class PublicationMismatchError(PublicationError, ValueError):
    """Raised when the pinned commit's tree is not the declared payload."""


class LocalPublicationReachability(str, Enum):
    """Whether a local pushable ref currently reaches the publication commit."""

    LOCAL_REACHABLE = "LOCAL_REACHABLE"
    LOCAL_UNREACHABLE = "LOCAL_UNREACHABLE"


class RemotePublicationReachability(str, Enum):
    """What the local checkout last fetched from a remote about the commit."""

    REMOTE_REACHABLE_AT_LAST_FETCH = "REMOTE_REACHABLE_AT_LAST_FETCH"
    NOT_PUSHED = "NOT_PUSHED"


@dataclass(frozen=True)
class PublicationReachability:
    """Separate local-anchor reachability from stale remote-fetch evidence."""

    local_state: LocalPublicationReachability
    remote_state: RemotePublicationReachability
    local_refs: tuple[PushableRefName, ...]
    remote_tracking_refs: tuple[RemoteTrackingRefName, ...]


class PublicationRefError(PayloadDeclarationError):
    """Raised when an anchor is not a valid pushable Git ref."""


class PublicationReachabilityError(PinnedCommitError):
    """Raised when no pushable anchor reaches the pinned commit."""


class PublicationRefQueryError(PublicationTreeError):
    """Raised when pushable-ref reachability cannot be determined."""


class PinCarrierMode(str, Enum):
    """The one of two typed carrier documents accepted by the shared codec."""

    SOURCE = "SOURCE"
    GENERATED = "GENERATED"


@dataclass(frozen=True)
class PinCarrierNormalization:
    """A validated carrier document and its one reversible pin substitution."""

    normalized_text: str
    pin_carrier: str
    recorded_sha: str
    mode: PinCarrierMode

    def heal(self, live_sha: str) -> str:
        """Replace exactly the generated dead SHA with one validated live SHA."""

        if (
            not isinstance(self.normalized_text, str)
            or not isinstance(self.pin_carrier, str)
            or not isinstance(self.recorded_sha, str)
            or not isinstance(self.mode, PinCarrierMode)
        ):
            raise PublicationMismatchError("the pin carrier normalization is invalid")
        _validate_pin_carrier_name(self.pin_carrier)
        if self.mode is not PinCarrierMode.GENERATED:
            raise PublicationMismatchError(
                f"only a generated pin carrier can be healed: {self.pin_carrier}"
            )
        if not isinstance(live_sha, str) or _FULL_SHA.fullmatch(live_sha) is None:
            raise PayloadDeclarationError(
                f"the live pin is not a full id: {self.pin_carrier}"
            )
        if self.normalized_text.count(_UNPINNABLE) != 1:
            raise PublicationMismatchError(
                f"the generated pin carrier has an invalid placeholder: {self.pin_carrier}"
            )
        return self.normalized_text.replace(_UNPINNABLE, live_sha)


def _validate_pin_carrier_name(pin_carrier: str) -> None:
    if (
        not isinstance(pin_carrier, str)
        or not pin_carrier
        or pin_carrier.startswith("/")
        or "\\" in pin_carrier
        or "\x00" in pin_carrier
        or any(part in ("", ".", "..") for part in pin_carrier.split("/"))
    ):
        raise PayloadDeclarationError(
            f"the pin carrier must be a clean repository-relative path: {pin_carrier!r}"
        )


def _recorded_pin_carrier_sha(text: str, pin_carrier: str) -> str:
    try:
        parsed: object = json.loads(text)
    except (TypeError, ValueError) as error:
        raise PayloadDeclarationError(
            f"the pin carrier records no readable pin: {pin_carrier}"
        ) from error
    if not isinstance(parsed, Mapping):
        raise PayloadDeclarationError(
            f"the pin carrier records no readable pin: {pin_carrier}"
        )
    plugins: object = parsed.get("plugins")
    if not isinstance(plugins, list) or len(plugins) != 1:
        raise PayloadDeclarationError(
            f"the pin carrier records no readable pin: {pin_carrier}"
        )
    plugin: object = plugins[0]
    if not isinstance(plugin, Mapping):
        raise PayloadDeclarationError(
            f"the pin carrier records no readable pin: {pin_carrier}"
        )
    source: object = plugin.get("source")
    if not isinstance(source, Mapping):
        raise PayloadDeclarationError(
            f"the pin carrier records no readable pin: {pin_carrier}"
        )
    recorded: object = source.get("sha")
    if not isinstance(recorded, str):
        raise PayloadDeclarationError(
            f"the recorded pin is not a full id: {pin_carrier}"
        )
    return recorded


def normalize_pin_carrier(
    text: str,
    pin_carrier: str,
    *,
    mode: PinCarrierMode,
) -> PinCarrierNormalization:
    """Validate one carrier document and normalize its single pin slot.

    SOURCE mode replaces one live full SHA with the unpinnable placeholder;
    GENERATED mode accepts only that placeholder.  Both modes use the same
    typed JSON/cardinality checks so generation and closure cannot drift.
    """

    _validate_pin_carrier_name(pin_carrier)
    if not isinstance(text, str):
        raise PayloadDeclarationError(f"the pin carrier is not text: {pin_carrier}")
    if not isinstance(mode, PinCarrierMode):
        raise PayloadDeclarationError(f"the pin carrier mode is invalid: {pin_carrier}")
    recorded = _recorded_pin_carrier_sha(text, pin_carrier)
    if _FULL_SHA.fullmatch(recorded) is None:
        raise PayloadDeclarationError(f"the recorded pin is not a full id: {pin_carrier}")
    if text.count(recorded) != 1:
        raise PayloadDeclarationError(
            f"the recorded pin does not appear exactly once: {pin_carrier}"
        )
    if mode is PinCarrierMode.SOURCE:
        normalized = text.replace(recorded, _UNPINNABLE)
    elif recorded == _UNPINNABLE:
        normalized = text
    else:
        raise PublicationMismatchError(
            f"the published copy records a usable pin instead of a placeholder: {pin_carrier}"
        )
    return PinCarrierNormalization(
        normalized_text=normalized,
        pin_carrier=pin_carrier,
        recorded_sha=recorded,
        mode=mode,
    )


def heal_pin_carrier(normalized: PinCarrierNormalization, live_sha: str) -> str:
    """Apply the shared reversible generated-carrier healing operation."""

    if not isinstance(normalized, PinCarrierNormalization):
        raise PublicationMismatchError("the pin carrier normalization is invalid")
    return normalized.heal(live_sha)


# --------------------------------------------------------------------------- #
# reading the declaration
# --------------------------------------------------------------------------- #


def read_plugin_manifest(manifest_path: Path) -> dict[str, object]:
    """Read the whole plugin manifest document."""

    try:
        document = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except OSError as error:
        raise PayloadDeclarationError("plugin manifest cannot be read") from error
    except (ValueError, UnicodeDecodeError) as error:
        raise PayloadDeclarationError("plugin manifest is not valid JSON") from error
    if not isinstance(document, dict):
        raise PayloadDeclarationError("plugin manifest is not an object")
    return document


def load_payload_declaration(manifest_path: Path) -> dict[str, object]:
    """Read and validate the payload enumeration."""

    document = read_plugin_manifest(manifest_path)
    payload = document.get("payload")
    if not isinstance(payload, dict):
        raise PayloadDeclarationError("plugin manifest declares no payload")
    trees = payload.get("trees")
    files = payload.get("files")
    if not isinstance(trees, list) or not trees:
        raise PayloadDeclarationError("payload trees must be a non-empty list")
    if not isinstance(files, list) or not files:
        raise PayloadDeclarationError("payload files must be a non-empty list")
    for entry in (*trees, *files):
        if not isinstance(entry, str) or not entry or entry != entry.strip():
            raise PayloadDeclarationError("payload entry is not a clean path")
    for entry in trees:
        if "/" in entry or entry in (".", ".."):
            raise PayloadDeclarationError("payload tree must be a single segment")
    for entry in (*trees, *files):
        if _is_forbidden(tuple(entry.split("/"))):
            raise PayloadDeclarationError(f"payload enumerates an excluded tree: {entry}")
    return payload


def _is_forbidden(parts: tuple[str, ...]) -> bool:
    return any(parts[: len(prefix)] == prefix for prefix in _EXCLUDED_PREFIXES)


def _payload_string_entries(payload: Mapping[str, object], key: str) -> tuple[str, ...]:
    """Read one validated string-list field from a payload mapping."""

    entries = payload.get(key)
    if not isinstance(entries, list) or not all(isinstance(entry, str) for entry in entries):
        raise PayloadDeclarationError(f"payload {key} must be a list of strings")
    return tuple(entries)


def is_payload_path(relative_path: str, payload: Mapping[str, object]) -> bool:
    """Segment-exact membership test for one repository-relative path."""

    trees = frozenset(_payload_string_entries(payload, "trees"))
    files = frozenset(_payload_string_entries(payload, "files"))
    excluded_segment_entries = payload.get("excludedSegments", ())
    if not isinstance(excluded_segment_entries, (list, tuple)) or not all(
        isinstance(entry, str) for entry in excluded_segment_entries
    ):
        raise PayloadDeclarationError("payload excludedSegments must be a string list")
    excluded_segments = frozenset(
        excluded_segment_entries
    )
    excluded_suffix_entries = payload.get("excludedSuffixes", ())
    if not isinstance(excluded_suffix_entries, (list, tuple)) or not all(
        isinstance(entry, str) for entry in excluded_suffix_entries
    ):
        raise PayloadDeclarationError("payload excludedSuffixes must be a string list")
    excluded_suffixes = tuple(
        excluded_suffix_entries
    )

    cleaned = relative_path.strip("/")
    if not cleaned:
        return False
    parts = tuple(cleaned.split("/"))
    if any(part in ("", ".", "..") for part in parts):
        return False
    if any(part in excluded_segments for part in parts):
        return False
    if excluded_suffixes and cleaned.endswith(excluded_suffixes):
        return False
    if _is_forbidden(parts):
        return False
    return cleaned in files or parts[0] in trees


def declared_payload_files(root: Path, payload: Mapping[str, object]) -> tuple[Path, ...]:
    """Every real file the declaration admits, in sorted order."""

    root = Path(root)
    found: list[Path] = []
    for name in _payload_string_entries(payload, "files"):
        candidate = root / name
        if candidate.is_symlink() or not candidate.is_file():
            raise PayloadDeclarationError(f"declared payload file is absent: {name}")
        found.append(candidate)
    for name in _payload_string_entries(payload, "trees"):
        tree = root / name
        if tree.is_symlink() or not tree.is_dir():
            raise PayloadDeclarationError(f"declared payload tree is absent: {name}")
        for candidate in tree.rglob("*"):
            if not candidate.is_file() or candidate.is_symlink():
                continue
            if is_payload_path(candidate.relative_to(root).as_posix(), payload):
                found.append(candidate)
    return tuple(sorted(set(found), key=lambda path: path.as_posix()))


def declared_payload_paths(root: Path, payload: Mapping[str, object]) -> tuple[str, ...]:
    """The declared payload as repository-relative posix paths."""

    root = Path(root)
    return tuple(
        path.relative_to(root).as_posix() for path in declared_payload_files(root, payload)
    )


# --------------------------------------------------------------------------- #
# reading the pin
# --------------------------------------------------------------------------- #


def pinned_plugin_source(manifest_path: Path) -> dict[str, object]:
    """Read the marketplace entry's source and reject every floating form."""

    try:
        document = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except OSError as error:
        raise PayloadDeclarationError("marketplace manifest cannot be read") from error
    except (ValueError, UnicodeDecodeError) as error:
        raise PayloadDeclarationError("marketplace manifest is not valid JSON") from error

    plugins = document.get("plugins")
    if not isinstance(plugins, list) or len(plugins) != 1:
        raise PayloadDeclarationError("marketplace must declare exactly one plugin")
    source = plugins[0].get("source")
    if isinstance(source, str):
        raise PayloadDeclarationError(
            "a string source publishes the rest of the repository, not an enumeration"
        )
    if not isinstance(source, dict):
        raise PayloadDeclarationError("plugin source must be a pinned source object")
    sha = source.get("sha")
    if not isinstance(sha, str) or _FULL_SHA.fullmatch(sha) is None:
        raise PayloadDeclarationError("plugin source must pin a full 40-hex commit sha")
    ref = source.get("ref")
    if isinstance(ref, str) and ref.strip().casefold() in _MOVING_REFS:
        raise PayloadDeclarationError(f"plugin source pins a moving ref: {ref}")
    return source


def _run_git(
    root: Path,
    arguments: Sequence[str],
    *,
    input_text: str | None = None,
    environment: Mapping[str, str] | None = None,
) -> str:
    # Bytes, not text: this platform's text mode rewrites a newline written to a
    # child's stdin into a carriage-return pair, which git accepts as part of the
    # path.  It then reports "Ignoring path ..." on stderr and *exits zero*, so
    # the whole payload silently becomes nothing.  Reading the streams as text
    # would hide the same characters coming back.
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=str(root),
            input=None if input_text is None else input_text.encode("utf-8"),
            capture_output=True,
            env=None if environment is None else {**os.environ, **environment},
            check=False,
        )
    except OSError as error:  # git missing, cwd gone
        raise PublicationTreeError(f"git could not be run: {arguments[0]}") from error
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise PublicationTreeError(f"git {arguments[0]} failed: {stderr or completed.returncode}")
    return completed.stdout.decode("utf-8", errors="replace")


def commit_exists(root: Path, sha: str) -> bool:
    """Whether the pinned sha names a real commit in this repository."""

    completed = subprocess.run(
        ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
        cwd=str(root),
        capture_output=True,
        check=False,
    )
    return completed.returncode == 0


def require_existing_commit(root: Path, sha: str) -> str:
    """Return the pinned sha, or name the failure.

    Malformed input is a declaration failure; a well-formed id that names no
    commit is a repository fact, and gets its own name so the two cannot be
    confused at the call site.
    """

    if not isinstance(sha, str) or _FULL_SHA.fullmatch(sha) is None:
        raise PayloadDeclarationError("pinned sha must be a full 40-hex lowercase id")
    if not commit_exists(root, sha):
        raise PinnedCommitError(f"the pinned sha names no commit in this repository: {sha}")
    return sha


def _validate_pushable_publication_ref(ref: str) -> str:
    """Validate the complete ref name, including its pushable namespace."""

    if (
        not isinstance(ref, str)
        or not any(ref.startswith(prefix) for prefix in _PUSHABLE_REF_PREFIXES)
        or _REF_ALLOWED.fullmatch(ref) is None
    ):
        raise PublicationRefError(
            "publication anchor must be a complete refs/heads/* or refs/tags/* name"
        )
    if ".." in ref or "@{" in ref or ref.endswith("."):
        raise PublicationRefError(f"publication anchor is not a valid Git ref: {ref}")
    segments = ref.split("/")
    if any(segment in ("", ".", "..") or segment.endswith(".lock") for segment in segments):
        raise PublicationRefError(f"publication anchor is not a valid Git ref: {ref}")
    return ref


def _validate_remote_tracking_ref(ref: str) -> RemoteTrackingRefName:
    """Validate a complete ``refs/remotes/<remote>/<branch>`` ref name."""

    if (
        not isinstance(ref, str)
        or not ref.startswith(_REMOTE_TRACKING_REF_PREFIX)
        or _REMOTE_REF_ALLOWED.fullmatch(ref) is None
    ):
        raise PublicationRefError(
            "remote publication evidence must be a complete "
            "refs/remotes/<remote>/<branch> name"
        )
    if ".." in ref or "@{" in ref or ref.endswith("."):
        raise PublicationRefError(f"remote tracking ref is not a valid Git ref: {ref}")
    segments = ref.split("/")
    if any(segment in ("", ".", "..") or segment.endswith(".lock") for segment in segments):
        raise PublicationRefError(f"remote tracking ref is not a valid Git ref: {ref}")
    return RemoteTrackingRefName(ref)


def publication_refs_reaching_commit(root: Path, sha: str) -> PublicationReachability:
    """Return named local reachability and last-fetch remote evidence for ``sha``.

    ``refs/remotes`` is deliberately reported as last-fetch evidence.  It is a
    local tracking ref, not a live probe of the remote, so this function never
    calls that evidence current remote truth.  Failure to enumerate refs is a
    separate named error so a broken Git query cannot masquerade as no ref.
    """

    sha = require_existing_commit(root, sha)
    try:
        raw = _run_git(
            root,
            [
                "for-each-ref",
                "--contains",
                sha,
                "--format=%(refname)",
                "refs/heads",
                "refs/tags",
                "refs/remotes",
            ],
        )
    except PublicationTreeError as error:
        raise PublicationRefQueryError(
            "pushable publication refs could not be enumerated"
        ) from error
    local_refs: list[PushableRefName] = []
    remote_tracking_refs: list[RemoteTrackingRefName] = []
    for ref in (line for line in raw.splitlines() if line):
        if ref.startswith(_REMOTE_TRACKING_REF_PREFIX):
            try:
                remote_tracking_refs.append(_validate_remote_tracking_ref(ref))
            except PublicationRefError as error:
                raise PublicationRefQueryError(
                    "Git returned a malformed remote tracking publication ref"
                ) from error
            continue
        try:
            validated = _validate_pushable_publication_ref(ref)
        except PublicationRefError as error:
            raise PublicationRefQueryError(
                "Git returned a malformed pushable publication ref"
            ) from error
        local_refs.append(PushableRefName(validated))

    return PublicationReachability(
        local_state=(
            LocalPublicationReachability.LOCAL_REACHABLE
            if local_refs
            else LocalPublicationReachability.LOCAL_UNREACHABLE
        ),
        remote_state=(
            RemotePublicationReachability.REMOTE_REACHABLE_AT_LAST_FETCH
            if remote_tracking_refs
            else RemotePublicationReachability.NOT_PUSHED
        ),
        local_refs=tuple(local_refs),
        remote_tracking_refs=tuple(remote_tracking_refs),
    )


def require_reachable_publication_ref(root: Path, sha: str, ref: str) -> str:
    """Require ``sha`` to be reachable from the named pushable anchor ref."""

    ref = _validate_pushable_publication_ref(ref)
    sha = require_existing_commit(root, sha)
    reachability = publication_refs_reaching_commit(root, sha)
    if PushableRefName(ref) not in reachability.local_refs:
        raise PublicationReachabilityError(
            f"the pinned sha is not reachable from its pushable anchor: {ref}"
        )
    return sha


def require_fetchable_publication_ref(root: Path, sha: str, ref: str) -> str:
    """Require last-fetch evidence that a user can obtain ``sha``.

    The public ``ref`` may be the named local branch anchor, in which case any
    matching remote branch tracking ref is accepted, or the complete tracking
    ref itself.  A tag is a valid local anchor but has no corresponding branch
    tracking ref and therefore cannot satisfy this requirement.
    """

    if not isinstance(ref, str):
        raise PublicationRefError("publication ref must be a string")
    if ref.startswith(_REMOTE_TRACKING_REF_PREFIX):
        requested_remote = _validate_remote_tracking_ref(ref)
        requested_local: str | None = None
    else:
        requested_local = _validate_pushable_publication_ref(ref)
        requested_remote = None

    sha = require_existing_commit(root, sha)
    reachability = publication_refs_reaching_commit(root, sha)
    matches: tuple[RemoteTrackingRefName, ...]
    if requested_remote is not None:
        matches = (requested_remote,)
    elif requested_local is not None and requested_local.startswith("refs/heads/"):
        branch = requested_local.removeprefix("refs/heads/")
        matches = tuple(
            tracking
            for tracking in reachability.remote_tracking_refs
            if tracking.removeprefix(_REMOTE_TRACKING_REF_PREFIX).split("/", 1)[1]
            == branch
        )
    else:
        matches = ()

    if not any(match in reachability.remote_tracking_refs for match in matches):
        raise PublicationReachabilityError(
            "the pinned sha has no corresponding remote-tracking ref at last fetch: "
            f"{ref}"
        )
    return sha


# --------------------------------------------------------------------------- #
# what the pin actually carries
# --------------------------------------------------------------------------- #


def tree_blob_ids(root: Path, sha: str) -> dict[str, str]:
    """Every path a commit carries, mapped to the blob id recorded for it."""

    require_existing_commit(root, sha)
    raw = _run_git(root, ["ls-tree", "-r", "-z", f"{sha}^{{tree}}"])
    entries: dict[str, str] = {}
    for record in raw.split("\0"):
        if not record:
            continue
        try:
            meta, path = record.split("\t", 1)
            _mode, kind, blob = meta.split(" ", 2)
        except ValueError as error:
            raise PublicationTreeError(f"unreadable tree entry: {record!r}") from error
        if kind != "blob":
            raise PublicationTreeError(f"the pinned tree carries a non-blob entry: {path}")
        entries[path] = blob
    if not entries:
        raise PublicationTreeError(f"the pinned tree enumerated to nothing: {sha}")
    return entries


def declared_blob_ids(root: Path, payload: Mapping[str, object]) -> dict[str, str]:
    """Hash the declared payload as it stands on disk, using git's own filters.

    Hashing through git rather than over raw bytes is what makes the comparison
    valid on a working copy whose line endings differ from the stored form.
    """

    root = Path(root)
    relatives = list(declared_payload_paths(root, payload))
    if not relatives:
        raise PublicationTreeError("the declaration admitted no files at all")
    for relative in relatives:
        if "\n" in relative or "\r" in relative:
            raise PublicationTreeError(f"declared path cannot be hashed: {relative!r}")
    produced = _run_git(
        root, ["hash-object", "--stdin-paths"], input_text="\n".join(relatives) + "\n"
    ).split()
    if len(produced) != len(relatives):
        raise PublicationTreeError(
            f"hashed {len(produced)} of {len(relatives)} declared files"
        )
    return dict(zip(relatives, produced))


@dataclass(frozen=True)
class PublicationDiff:
    """The difference between what a commit carries and what was declared."""

    missing: tuple[str, ...]
    extra: tuple[str, ...]
    differing: tuple[str, ...]
    unbindable: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        return not (self.missing or self.extra or self.differing)


def compare_commit_to_declaration(
    root: Path,
    payload: Mapping[str, object],
    sha: str,
    *,
    pin_carrier: str | None = None,
) -> PublicationDiff:
    """Recompute both sides from repository facts and report every difference.

    ``pin_carrier`` names the one path that records ``sha`` itself.  It is not
    dropped from the comparison -- a content difference there is reported under
    its own heading, so the caller has to decide about it explicitly.
    """

    declared = declared_blob_ids(root, payload)
    carried = tree_blob_ids(root, sha)
    missing = tuple(sorted(set(declared) - set(carried)))
    extra = tuple(sorted(set(carried) - set(declared)))
    differing: list[str] = []
    unbindable: list[str] = []
    for path in sorted(set(declared) & set(carried)):
        if declared[path] == carried[path]:
            continue
        if pin_carrier is not None and path == pin_carrier:
            unbindable.append(path)
        else:
            differing.append(path)
    return PublicationDiff(missing, extra, tuple(differing), tuple(unbindable))


def _healed_pin_carrier_matches(
    root: Path, sha: str, pin_carrier: str, carried_blob: str
) -> bool:
    """Whether the carried copy differs from the working copy only in the pin.

    Exactly one recorded id is substituted, and only after it has been read out
    of the carried document and shown to occur once, so a second difference
    anywhere in the file still fails.
    """

    published = _run_git(root, ["cat-file", "blob", carried_blob])
    try:
        working = (Path(root) / pin_carrier).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise PublicationTreeError(f"the pin carrier cannot be read: {pin_carrier}") from error
    generated = normalize_pin_carrier(
        published, pin_carrier, mode=PinCarrierMode.GENERATED
    )
    source = normalize_pin_carrier(
        working, pin_carrier, mode=PinCarrierMode.SOURCE
    )
    if source.recorded_sha != sha:
        return False
    healed = heal_pin_carrier(generated, sha)
    return healed.replace("\r\n", "\n") == working.replace("\r\n", "\n")


def assert_commit_matches_declaration(
    root: Path,
    payload: Mapping[str, object],
    sha: str,
    *,
    pin_carrier: str | None = None,
) -> PublicationDiff:
    """Raise unless the pinned commit carries exactly the declared payload."""

    if pin_carrier is not None and pin_carrier not in declared_blob_ids(root, payload):
        raise PayloadDeclarationError(
            f"the pin carrier is not part of the declared payload: {pin_carrier}"
        )
    diff = compare_commit_to_declaration(root, payload, sha, pin_carrier=pin_carrier)
    if diff.missing:
        raise PublicationMismatchError(
            "the pinned commit is missing declared paths: " + ", ".join(diff.missing[:10])
        )
    if diff.extra:
        raise PublicationMismatchError(
            "the pinned commit carries undeclared paths: " + ", ".join(diff.extra[:10])
        )
    if diff.differing:
        raise PublicationMismatchError(
            "the pinned commit carries different content for: "
            + ", ".join(diff.differing[:10])
        )
    # Checked whether or not the blob differs.  A carrier that happens to match
    # byte for byte is not exempt -- it means the published copy kept a working
    # pin at some other tree, which is the failure this whole module is about.
    if pin_carrier is not None:
        carried = tree_blob_ids(root, sha)
        if pin_carrier in carried and not _healed_pin_carrier_matches(
            root, sha, pin_carrier, carried[pin_carrier]
        ):
            raise PublicationMismatchError(
                f"the pin carrier differs by more than the pin it records: {pin_carrier}"
            )
    return diff


# --------------------------------------------------------------------------- #
# producing the tree
# --------------------------------------------------------------------------- #


def materialise_publication_tree(
    root: Path,
    payload: Mapping[str, object],
    destination: Path,
    *,
    pin_carrier: str | None = None,
) -> tuple[str, ...]:
    """Copy exactly the declared payload into an empty destination.

    The pin carrier is neutralised here too.  A directory that differed from the
    commit would be a second artifact claiming to be the same release, and the
    difference would be precisely a live pin at some older tree.
    """

    root = Path(root)
    destination = Path(destination)
    sources = declared_payload_files(root, payload)
    if not sources:
        raise PublicationTreeError("the declaration admitted no files at all")
    if destination.exists() and any(destination.iterdir()):
        raise PublicationTreeError(f"publication destination is not empty: {destination}")
    relatives = {source.relative_to(root).as_posix() for source in sources}
    if pin_carrier is not None and pin_carrier not in relatives:
        raise PayloadDeclarationError(
            f"the pin carrier is not part of the declared payload: {pin_carrier}"
        )
    written: list[str] = []
    for source in sources:
        relative = source.relative_to(root)
        target = destination / relative
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if pin_carrier is not None and relative.as_posix() == pin_carrier:
                target.write_bytes(
                    _neutralised_pin_carrier_text(root, pin_carrier).encode("utf-8")
                )
            else:
                shutil.copyfile(source, target)
        except OSError as error:
            raise PublicationTreeError(
                f"declared payload file could not be published: {relative.as_posix()}"
            ) from error
        written.append(relative.as_posix())
    return tuple(written)


def publication_commit_message(document: Mapping[str, object]) -> str:
    """A message that is a function of the manifest, not of the moment."""

    name = str(document.get("name", "")).strip()
    version = str(document.get("version", "")).strip()
    if not name or not version:
        raise PayloadDeclarationError("plugin manifest declares no name and version")
    return f"{name} {version}\n\nEvery path below is enumerated by the manifest payload.\n"


def _commit_identity(document: Mapping[str, object]) -> tuple[str, str]:
    author = document.get("author")
    name = str(document.get("name", "")).strip()
    if isinstance(author, Mapping):
        author_name = str(author.get("name", "")).strip() or name
    else:
        author_name = str(author or "").strip() or name
    if not author_name or not name:
        raise PayloadDeclarationError("plugin manifest declares no author and name")
    return author_name, f"{name}@invalid"


def _neutralised_pin_carrier_text(root: Path, pin_carrier: str) -> str:
    """The pin carrier's content with the id it records replaced by a dead one."""

    try:
        text = (Path(root) / pin_carrier).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise PublicationTreeError(f"the pin carrier cannot be read: {pin_carrier}") from error
    return normalize_pin_carrier(
        text, pin_carrier, mode=PinCarrierMode.SOURCE
    ).normalized_text


def _neutralise_pin_carrier(
    root: Path, pin_carrier: str, environment: Mapping[str, str]
) -> str:
    """Stage the pin carrier with an id that names nothing, and return that blob."""

    text = _neutralised_pin_carrier_text(root, pin_carrier)
    blob = _run_git(
        root,
        ["hash-object", "-w", "--path", pin_carrier, "--stdin"],
        input_text=text,
    ).strip()
    if _FULL_SHA.fullmatch(blob) is None:
        raise PublicationTreeError(f"the neutralised pin carrier did not hash: {blob!r}")
    _run_git(
        root,
        ["update-index", "--add", "--cacheinfo", f"100644,{blob},{pin_carrier}"],
        environment=environment,
    )
    return blob


def write_publication_commit(
    root: Path,
    manifest_path: Path,
    *,
    pin_carrier: str | None = None,
    ref: str | None = None,
) -> str:
    """Write a parentless commit whose tree is exactly the declared payload.

    The object id is a pure function of the declared content, so re-running this
    on an unchanged working copy reproduces it.  Nothing about the development
    history is written into it and no branch is moved: the development tree
    stays whole, and the publication tree is a separate root.
    """

    root = Path(root)
    if ref is not None:
        ref = _validate_pushable_publication_ref(ref)
    document = read_plugin_manifest(manifest_path)
    payload = load_payload_declaration(manifest_path)
    relatives = list(declared_payload_paths(root, payload))
    if not relatives:
        raise PublicationTreeError("the declaration admitted no files at all")

    author_name, author_email = _commit_identity(document)
    message = publication_commit_message(document)

    handle, raw_index = tempfile.mkstemp(prefix="publication-index-")
    os.close(handle)
    os.unlink(raw_index)
    environment = {"GIT_INDEX_FILE": raw_index}
    try:
        _run_git(root, ["read-tree", "--empty"], environment=environment)
        _run_git(
            root,
            ["update-index", "--add", "--stdin"],
            input_text="\n".join(relatives) + "\n",
            environment=environment,
        )
        # git reports an ignored path on stderr and still exits zero, so the exit
        # code is not evidence that anything was staged.  Count what landed.
        staged = {
            record.split("\t", 1)[1]
            for record in _run_git(root, ["ls-files", "-s", "-z"], environment=environment).split("\0")
            if "\t" in record
        }
        if staged != set(relatives):
            raise PublicationTreeError(
                f"staged {len(staged)} of {len(relatives)} declared files; "
                f"missing {sorted(set(relatives) - staged)[:5]}"
            )
        if pin_carrier is not None:
            if pin_carrier not in staged:
                raise PayloadDeclarationError(
                    f"the pin carrier is not part of the declared payload: {pin_carrier}"
                )
            _neutralise_pin_carrier(root, pin_carrier, environment)
        tree = _run_git(root, ["write-tree"], environment=environment).strip()
    finally:
        if os.path.exists(raw_index):
            os.unlink(raw_index)
    if _FULL_SHA.fullmatch(tree) is None:
        raise PublicationTreeError(f"the publication tree did not hash: {tree!r}")

    commit = _run_git(
        root,
        ["commit-tree", tree, "-m", message],
        environment={
            "GIT_AUTHOR_NAME": author_name,
            "GIT_AUTHOR_EMAIL": author_email,
            "GIT_AUTHOR_DATE": _FIXED_DATE,
            "GIT_COMMITTER_NAME": author_name,
            "GIT_COMMITTER_EMAIL": author_email,
            "GIT_COMMITTER_DATE": _FIXED_DATE,
        },
    ).strip()
    if _FULL_SHA.fullmatch(commit) is None:
        raise PublicationTreeError(f"the publication commit did not hash: {commit!r}")
    if ref is not None:
        _run_git(root, ["update-ref", ref, commit])
        require_reachable_publication_ref(root, commit, ref)
    return commit


def repin_marketplace(marketplace_path: Path, sha: str) -> str:
    """Point the marketplace entry at ``sha``, changing nothing else.

    The replacement is textual and asserted to be unique, so the file's
    formatting survives and the only byte difference is the pin itself.
    """

    marketplace_path = Path(marketplace_path)
    if _FULL_SHA.fullmatch(sha) is None:
        raise PayloadDeclarationError("a pin must be a full 40-hex lowercase id")
    previous = str(pinned_plugin_source(marketplace_path)["sha"])
    try:
        raw = marketplace_path.read_bytes()
    except OSError as error:
        raise PayloadDeclarationError("marketplace manifest cannot be read") from error
    needle = previous.encode("ascii")
    if raw.count(needle) != 1:
        raise PayloadDeclarationError(
            f"the recorded pin does not appear exactly once: {raw.count(needle)}"
        )
    try:
        marketplace_path.write_bytes(raw.replace(needle, sha.encode("ascii")))
    except OSError as error:
        raise PayloadDeclarationError("marketplace manifest cannot be written") from error
    return previous


# --------------------------------------------------------------------------- #
# operator entry point
# --------------------------------------------------------------------------- #


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--marketplace", type=Path)
    parser.add_argument("--into", type=Path)
    parser.add_argument("--ref")
    parser.add_argument("--verify-only", action="store_true")
    parsed = parser.parse_args(argv)

    root = parsed.repo.resolve()
    payload = load_payload_declaration(parsed.manifest)
    carrier = None
    if parsed.marketplace is not None:
        try:
            carrier = parsed.marketplace.resolve().relative_to(root).as_posix()
        except ValueError as error:
            raise PayloadDeclarationError(
                "the manifest that records the pin is outside the repository"
            ) from error

    if parsed.verify_only:
        if parsed.marketplace is None:
            raise PayloadDeclarationError("verification needs the manifest that records the pin")
        if parsed.ref is None:
            raise PublicationRefError("verification needs the pushable publication anchor ref")
        sha = str(pinned_plugin_source(parsed.marketplace)["sha"])
        assert_commit_matches_declaration(root, payload, sha, pin_carrier=carrier)
        require_reachable_publication_ref(root, sha, parsed.ref)
        print(f"verified {sha}")
        return 0

    if parsed.ref is None:
        raise PublicationRefError("publication requires a pushable anchor ref")

    if parsed.into is not None:
        written = materialise_publication_tree(
            root, payload, parsed.into, pin_carrier=carrier
        )
        print(f"materialised {len(written)} files -> {parsed.into}")

    commit = write_publication_commit(
        root, parsed.manifest, pin_carrier=carrier, ref=parsed.ref
    )
    print(f"publication commit {commit}")
    if parsed.marketplace is not None:
        previous = repin_marketplace(parsed.marketplace, commit)
        print(f"repinned {previous} -> {commit}")
        assert_commit_matches_declaration(root, payload, commit, pin_carrier=carrier)
        print("pin verified against the declaration")
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main())
