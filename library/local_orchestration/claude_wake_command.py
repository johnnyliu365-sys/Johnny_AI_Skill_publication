"""Wake one Claude Code conversation branch for the reviewer a payload names.

Claude Code exposes no interface for injecting a turn into a conversation
somebody is already sitting in: the CLI's whole command surface was read and
none of it delivers input to a running session, and the in-app session
message tool is callable only by an agent already inside a session. So this
channel never wakes the owner's open window. What it does instead is drive a
branch the Router owns -- `claude -p --resume <session>` runs exactly one
turn against a stored conversation and exits -- which is why different
reviewers reach different branches: the target is resolved per attempt from
the payload's `reviewer_ref` through an owner-declared routing table.

The capability probe renders this exact command against a disposable payload
that names no reviewer. Exiting zero on a payload this command cannot deliver
would make `PROVEN` mean "the dispatcher can read a file", so the probe path
instead performs a real end-to-end drive of a throwaway branch and requires a
completed model turn to come back before it reports success. Two honest
limits follow, and neither is papered over: the probe proves the host can
drive *a* Claude branch, not that the reviewer's own branch is reachable
(the probe payload names no reviewer, and a missing route surfaces at wake
time as `REVIEWER_NOT_MAPPED`); and the probe drives a throwaway session id
where a real wake resumes a stored one, which is the single deliberate
difference between the probed invocation and the delivered one.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

_EXECUTABLE_ENVIRONMENT_KEY = "JOHNNY_CLAUDE_EXECUTABLE"
_ROUTES_FILE_NAME = "claude-branch-routes.json"
_INSTALL_RELATIVE = Path("Claude") / "claude-code"
_APP_ROOT_RELATIVE = Path("Claude")
_APP_SESSIONS_RELATIVE = Path("Claude") / "claude-code-sessions"
_EXECUTABLE_NAME = "claude.exe"

_PROBE_MODEL = "haiku"
_PROBE_MARKER = "JOHNNY_PROBE_OK"
_PROBE_PROMPT = (
    "Reply with exactly " + _PROBE_MARKER + " and nothing else. "
    "This is an automated capability probe; take no other action."
)
_AUTH_TIMEOUT_SECONDS = 10
_AGENTS_TIMEOUT_SECONDS = 15
_PROBE_DRIVE_TIMEOUT_SECONDS = 18
_DRIVE_TIMEOUT_SECONDS = 120

# `probe_wake_capability` kills the whole rendered command at
# `min(30, config.timeout_seconds)`, so the probe path's own worst case -- the
# auth read plus the throwaway drive -- has to finish inside that, or a working
# host would be reported as PROBE_TIMEOUT. The budget is spent against a
# monotonic deadline rather than assumed, and a cell binds it to the runtime's
# cap so raising either timeout turns red instead of silently overrunning.
_PROBE_BUDGET_SECONDS = 28

_VERSION_PATTERN = re.compile(r"^\d+(?:\.\d+)*$")
_SESSION_ID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_REQUIRED_PROTOCOL = "ROLE_WAKE_V1"


class ClaudeWakeStatus(str, Enum):
    """What this invocation actually achieved."""

    DELIVERED = "DELIVERED"
    CAPABILITY_PROVEN = "CAPABILITY_PROVEN"
    REFUSED = "REFUSED"


class ClaudeWakeFailure(str, Enum):
    """Finite reasons one wake could not be delivered."""

    ARGUMENTS_INVALID = "ARGUMENTS_INVALID"
    EXECUTABLE_UNAVAILABLE = "EXECUTABLE_UNAVAILABLE"
    NOT_AUTHENTICATED = "NOT_AUTHENTICATED"
    PAYLOAD_UNREADABLE = "PAYLOAD_UNREADABLE"
    PAYLOAD_MALFORMED = "PAYLOAD_MALFORMED"
    ROUTES_UNREADABLE = "ROUTES_UNREADABLE"
    ROUTES_INVALID = "ROUTES_INVALID"
    REVIEWER_NOT_MAPPED = "REVIEWER_NOT_MAPPED"
    BRANCH_HELD_BY_APP_TAB = "BRANCH_HELD_BY_APP_TAB"
    APP_CLAIM_CHECK_FAILED = "APP_CLAIM_CHECK_FAILED"
    BRANCH_HELD_BY_LIVE_SESSION = "BRANCH_HELD_BY_LIVE_SESSION"
    LIVE_SESSION_CHECK_FAILED = "LIVE_SESSION_CHECK_FAILED"
    DRIVE_FAILED = "DRIVE_FAILED"
    DRIVE_TIMEOUT = "DRIVE_TIMEOUT"
    PROBE_NOT_COMPLETED = "PROBE_NOT_COMPLETED"


@dataclass(frozen=True, slots=True)
class ClaudeBranch:
    """One Claude conversation branch this host can drive."""

    reviewer_ref: str
    session_id: str
    project_id: str | None


def _version_key(name: str) -> tuple[int, ...]:
    if not _VERSION_PATTERN.match(name):
        return ()
    return tuple(int(part) for part in name.split("."))


def default_claude_executable(
    environ: dict[str, str] | None = None,
) -> Path | None:
    """Locate the CLI, which installs off PATH under a versioned directory."""

    source = os.environ if environ is None else environ
    override = source.get(_EXECUTABLE_ENVIRONMENT_KEY)
    if override:
        candidate = Path(override)
        return candidate if candidate.is_file() else None
    roaming = source.get("APPDATA")
    if not roaming:
        return None
    install_root = Path(roaming) / _INSTALL_RELATIVE
    if not install_root.is_dir():
        return None
    best: tuple[tuple[int, ...], Path] | None = None
    try:
        entries = list(install_root.iterdir())
    except OSError:
        return None
    for entry in entries:
        executable = entry / _EXECUTABLE_NAME
        if not executable.is_file():
            continue
        key = _version_key(entry.name)
        if not key:
            continue
        if best is None or key > best[0]:
            best = (key, executable)
    return None if best is None else best[1]


def _run(
    argv: tuple[str, ...], timeout_seconds: int, cwd: Path | None = None
) -> subprocess.CompletedProcess[bytes] | None:
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            shell=False,
            timeout=timeout_seconds,
            cwd=None if cwd is None else str(cwd),
        )
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None


def is_authenticated(executable: Path) -> bool:
    """Read the CLI's own authentication verdict; never infer it from a guess."""

    completed = _run((str(executable), "auth", "status"), _AUTH_TIMEOUT_SECONDS)
    if completed is None or completed.returncode != 0:
        return False
    try:
        payload = json.loads(completed.stdout.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("loggedIn") is True


def app_claimed_session_ids(
    environ: dict[str, str] | None = None,
) -> frozenset[str] | None:
    """Read which CLI conversations the desktop app holds a tab for.

    A tab open on screen and a live process are not the same thing. Measured
    on the owner's host: the process behind an open tab left the live
    inventory while the owner had not touched the tab at all. A guard that
    only asks which processes are running would therefore hand the Router a
    conversation the owner still has in front of them and call it free.

    The app writes one record per session carrying its own id *and* the
    `cliSessionId` it wraps, so the claim survives the process and is readable
    from disk. `None` means the claim could not be established, and the caller
    must refuse rather than proceed: a record that cannot be read may be the
    one that mattered.
    """

    source = os.environ if environ is None else environ
    roaming = source.get("APPDATA")
    if not roaming:
        return None
    root = Path(roaming) / _APP_SESSIONS_RELATIVE
    if not root.is_dir():
        if (Path(roaming) / _APP_ROOT_RELATIVE).is_dir():
            return None
        return frozenset()
    try:
        records = list(root.rglob("local_*.json"))
    except OSError:
        return None
    claimed: set[str] = set()
    for record in records:
        try:
            parsed = json.loads(record.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            return None
        if not isinstance(parsed, dict):
            return None
        value = parsed.get("cliSessionId")
        if isinstance(value, str) and value:
            claimed.add(value)
    return frozenset(claimed)


def live_session_ids(executable: Path) -> frozenset[str] | None:
    """Read which conversations a live process currently holds.

    Driving a conversation the owner has open in the app was measured on the
    owner's host: the turn is appended to the transcript, the app neither
    renders nor registers it, and the app goes on holding an in-memory history
    that no longer matches the file. That produces work the owner cannot see
    and two writers over one transcript, so it is refused rather than offered.

    Needs no authentication. `None` means the inventory could not be read,
    which is not the same as "nothing is live" and must not be treated as it.
    """

    completed = _run((str(executable), "agents", "--json"), _AGENTS_TIMEOUT_SECONDS)
    if completed is None or completed.returncode != 0:
        return None
    try:
        parsed = json.loads(completed.stdout.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(parsed, list):
        return None
    held: set[str] = set()
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        value = entry.get("sessionId")
        if isinstance(value, str) and value:
            held.add(value)
    return frozenset(held)


def is_capability_probe(body: str) -> bool:
    """The probe payload is the runtime's own JSON marker, not a wake payload."""

    try:
        parsed = json.loads(body)
    except ValueError:
        return False
    return isinstance(parsed, dict) and parsed.get("probe") is True


def parse_identifiers(body: str) -> dict[str, str]:
    """Read the identifiers-only `key=value` payload the Router renders."""

    identifiers: dict[str, str] = {}
    for line in body.splitlines():
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        identifiers[key] = value
    return identifiers


def load_routes(path: Path) -> tuple[ClaudeBranch, ...] | None:
    """Read the owner-declared reviewer-to-branch table; None means unreadable."""

    try:
        body = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        parsed = json.loads(body)
    except ValueError:
        raise ValueError("routes file is not JSON")
    if not isinstance(parsed, dict):
        raise ValueError("routes file must be a JSON object")
    entries = parsed.get("routes")
    if not isinstance(entries, list) or not entries:
        raise ValueError("routes file must carry a non-empty routes list")
    branches: list[ClaudeBranch] = []
    seen: set[tuple[str, str | None]] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("every route must be an object")
        reviewer_ref = entry.get("reviewer_ref")
        session_id = entry.get("session_id")
        project_id = entry.get("project_id")
        if not isinstance(reviewer_ref, str) or not reviewer_ref:
            raise ValueError("every route needs a reviewer_ref")
        if not isinstance(session_id, str) or not _SESSION_ID_PATTERN.match(
            session_id
        ):
            raise ValueError("every route needs a UUID session_id")
        if project_id is not None and not isinstance(project_id, str):
            raise ValueError("project_id must be a string when present")
        key = (reviewer_ref, project_id)
        if key in seen:
            raise ValueError("one reviewer may not hold two branches per project")
        seen.add(key)
        branches.append(
            ClaudeBranch(
                reviewer_ref=reviewer_ref,
                session_id=session_id,
                project_id=project_id,
            )
        )
    return tuple(branches)


def resolve_branch(
    branches: tuple[ClaudeBranch, ...], reviewer_ref: str, project_id: str | None
) -> ClaudeBranch | None:
    """Prefer a project-scoped route, then a project-agnostic one; never guess."""

    for branch in branches:
        if branch.reviewer_ref == reviewer_ref and branch.project_id == project_id:
            return branch
    for branch in branches:
        if branch.reviewer_ref == reviewer_ref and branch.project_id is None:
            return branch
    return None


def default_routes_path() -> Path | None:
    """Derive the routes file from the same root every owned path derives from."""

    try:
        from .johnny_root_layout import JohnnyRootLayout

        return JohnnyRootLayout.resolve().base / _ROUTES_FILE_NAME
    except Exception:
        return None


def _wake_message(payload_file: Path) -> str:
    return (
        "[Johnny wake] A receipt-bound reviewer wake was delivered for you. "
        f"Read the wake payload at {payload_file} and act on it as the named "
        "reviewer. The payload carries identifiers only; follow the review "
        "instructions it names."
    )


def drive_branch(
    executable: Path,
    session_id: str,
    payload_file: Path,
    timeout_seconds: int = _DRIVE_TIMEOUT_SECONDS,
) -> tuple[ClaudeWakeStatus, ClaudeWakeFailure | None]:
    """Run exactly one turn against the reviewer's own stored branch."""

    completed = _run(
        (
            str(executable),
            "-p",
            "--resume",
            session_id,
            _wake_message(payload_file),
        ),
        timeout_seconds,
    )
    if completed is None:
        return ClaudeWakeStatus.REFUSED, ClaudeWakeFailure.DRIVE_TIMEOUT
    if completed.returncode != 0:
        return ClaudeWakeStatus.REFUSED, ClaudeWakeFailure.DRIVE_FAILED
    return ClaudeWakeStatus.DELIVERED, None


def probe_drive(
    executable: Path,
    timeout_seconds: int = _PROBE_DRIVE_TIMEOUT_SECONDS,
    cwd: Path | None = None,
) -> tuple[ClaudeWakeStatus, ClaudeWakeFailure | None]:
    """Drive a throwaway branch end to end; a bare exit code proves nothing."""

    completed = _run(
        (
            str(executable),
            "-p",
            "--session-id",
            str(uuid.uuid4()),
            "--model",
            _PROBE_MODEL,
            _PROBE_PROMPT,
        ),
        timeout_seconds,
        cwd=cwd,
    )
    if completed is None:
        return ClaudeWakeStatus.REFUSED, ClaudeWakeFailure.DRIVE_TIMEOUT
    if completed.returncode != 0:
        return ClaudeWakeStatus.REFUSED, ClaudeWakeFailure.DRIVE_FAILED
    body = completed.stdout.decode("utf-8", errors="replace")
    if _PROBE_MARKER not in body:
        return ClaudeWakeStatus.REFUSED, ClaudeWakeFailure.PROBE_NOT_COMPLETED
    return ClaudeWakeStatus.CAPABILITY_PROVEN, None


def wake(
    payload_file: Path,
    executable: Path | None = None,
    routes_file: Path | None = None,
) -> tuple[ClaudeWakeStatus, ClaudeWakeFailure | None]:
    """Deliver one wake, or prove the capability when handed a probe payload."""

    started = time.monotonic()
    resolved = default_claude_executable() if executable is None else executable
    if resolved is None or not resolved.is_file():
        return ClaudeWakeStatus.REFUSED, ClaudeWakeFailure.EXECUTABLE_UNAVAILABLE
    try:
        body = payload_file.read_text(encoding="utf-8")
    except OSError:
        return ClaudeWakeStatus.REFUSED, ClaudeWakeFailure.PAYLOAD_UNREADABLE

    if not is_authenticated(resolved):
        return ClaudeWakeStatus.REFUSED, ClaudeWakeFailure.NOT_AUTHENTICATED

    if is_capability_probe(body):
        remaining = _PROBE_BUDGET_SECONDS - (time.monotonic() - started)
        if remaining < 1:
            return ClaudeWakeStatus.REFUSED, ClaudeWakeFailure.DRIVE_TIMEOUT
        return probe_drive(
            resolved, min(_PROBE_DRIVE_TIMEOUT_SECONDS, int(remaining))
        )

    identifiers = parse_identifiers(body)
    if identifiers.get("protocol") != _REQUIRED_PROTOCOL:
        return ClaudeWakeStatus.REFUSED, ClaudeWakeFailure.PAYLOAD_MALFORMED
    reviewer_ref = identifiers.get("reviewer_ref")
    if not reviewer_ref or reviewer_ref == "-":
        return ClaudeWakeStatus.REFUSED, ClaudeWakeFailure.PAYLOAD_MALFORMED
    project_id = identifiers.get("project_id")

    path = default_routes_path() if routes_file is None else routes_file
    if path is None:
        return ClaudeWakeStatus.REFUSED, ClaudeWakeFailure.ROUTES_UNREADABLE
    try:
        branches = load_routes(path)
    except ValueError:
        return ClaudeWakeStatus.REFUSED, ClaudeWakeFailure.ROUTES_INVALID
    if branches is None:
        return ClaudeWakeStatus.REFUSED, ClaudeWakeFailure.ROUTES_UNREADABLE

    branch = resolve_branch(branches, reviewer_ref, project_id)
    if branch is None:
        return ClaudeWakeStatus.REFUSED, ClaudeWakeFailure.REVIEWER_NOT_MAPPED

    claimed = app_claimed_session_ids()
    if claimed is None:
        return ClaudeWakeStatus.REFUSED, ClaudeWakeFailure.APP_CLAIM_CHECK_FAILED
    if branch.session_id in claimed:
        return ClaudeWakeStatus.REFUSED, ClaudeWakeFailure.BRANCH_HELD_BY_APP_TAB

    held = live_session_ids(resolved)
    if held is None:
        return ClaudeWakeStatus.REFUSED, ClaudeWakeFailure.LIVE_SESSION_CHECK_FAILED
    if branch.session_id in held:
        return (
            ClaudeWakeStatus.REFUSED,
            ClaudeWakeFailure.BRANCH_HELD_BY_LIVE_SESSION,
        )
    return drive_branch(resolved, branch.session_id, payload_file)


def main(argv: tuple[str, ...]) -> int:
    """Emit exactly one typed JSON line; exit 0 only when one wake landed."""

    payload: str | None = None
    executable: str | None = None
    routes: str | None = None
    remaining = list(argv)
    while remaining:
        item = remaining.pop(0)
        if item == "--executable":
            executable = remaining.pop(0) if remaining else None
        elif item.startswith("--executable="):
            executable = item.split("=", 1)[1]
        elif item == "--routes":
            routes = remaining.pop(0) if remaining else None
        elif item.startswith("--routes="):
            routes = item.split("=", 1)[1]
        elif payload is None:
            payload = item

    if not payload:
        print(
            json.dumps(
                {
                    "status": ClaudeWakeStatus.REFUSED.value,
                    "code": ClaudeWakeFailure.ARGUMENTS_INVALID.value,
                },
                sort_keys=True,
            )
        )
        return 2

    status, failure = wake(
        Path(payload),
        executable=Path(executable) if executable else None,
        routes_file=Path(routes) if routes else None,
    )
    line: dict[str, object] = {"status": status.value}
    if failure is not None:
        line["code"] = failure.value
    print(json.dumps(line, sort_keys=True))
    succeeded = status in (
        ClaudeWakeStatus.DELIVERED,
        ClaudeWakeStatus.CAPABILITY_PROVEN,
    )
    return 0 if succeeded else 2


if __name__ == "__main__":
    raise SystemExit(main(tuple(sys.argv[1:])))


__all__ = [
    "ClaudeBranch",
    "ClaudeWakeFailure",
    "ClaudeWakeStatus",
    "app_claimed_session_ids",
    "default_claude_executable",
    "default_routes_path",
    "drive_branch",
    "is_authenticated",
    "is_capability_probe",
    "live_session_ids",
    "load_routes",
    "main",
    "parse_identifiers",
    "probe_drive",
    "resolve_branch",
    "wake",
]
