"""An owner-declarable wake command for an Antigravity reviewer conversation.

E11 proved the channel: `agentapi send-message` into an existing conversation
really wakes an agent that reads the delivered payload and acts. It also found
why that cannot be declared directly as a `WakeCommandConfig.command`: the
`agentapi` client needs `ANTIGRAVITY_LS_ADDRESS` and `ANTIGRAVITY_CSRF_TOKEN`,
and both change on every IDE launch. A command frozen into owner
configuration would be stale by the next restart.

This module is the command the owner declares instead. It rediscovers the
running language server at invocation time, then sends exactly one message.

    py -3.11 -m library.local_orchestration.antigravity_wake_command \\
        --conversation <uuid> {payload_file}

Discovery is read-only: it enumerates processes and their listening sockets
and asks the candidate a question with no side effect. Nothing is killed,
restarted or reconfigured, and nothing is cached between runs.

The message names the payload file; it never pastes the payload body. The
identifiers-only discipline lives in the payload file the wake port wrote,
and duplicating it into conversation text would be a second, unreviewed copy.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

# Injected endpoint, for the two cases where discovery cannot run: a
# qualification driving this command deterministically, and a runner started
# as a service with the values supplied by whatever launched the IDE. Both
# are anticipated modes, not bypasses — an injected endpoint is still proved
# by the same probe before anything is sent.
_ENDPOINT_ENVIRONMENT_KEY = "JOHNNY_ANTIGRAVITY_ENDPOINT"
_TOKEN_ENVIRONMENT_KEY = "JOHNNY_ANTIGRAVITY_TOKEN"

_AGENTAPI_RELATIVE = Path(".gemini") / "antigravity-ide" / "bin" / "agentapi.bat"
_PROBE_CONVERSATION_ID = "johnny-discovery-probe"
_AUTHENTICATED_MARKER = "trajectory not found"
_CSRF_PATTERN = re.compile(r"--csrf_token\s+([0-9a-fA-F-]{8,64})")
_PROBE_TIMEOUT_SECONDS = 20
_SEND_TIMEOUT_SECONDS = 90
_ENUMERATE_TIMEOUT_SECONDS = 45

_ENUMERATE_SCRIPT = (
    "$ErrorActionPreference='SilentlyContinue';"
    " $procs = Get-CimInstance Win32_Process"
    " -Filter \"Name='language_server_windows_x64.exe'\";"
    " $out = @();"
    " foreach ($p in $procs) {"
    "   $ports = @(Get-NetTCPConnection -State Listen |"
    "     Where-Object { $_.OwningProcess -eq $p.ProcessId } |"
    "     Select-Object -ExpandProperty LocalPort);"
    "   $out += [pscustomobject]@{"
    "     command_line = [string]$p.CommandLine; ports = $ports } };"
    " ConvertTo-Json -InputObject @($out) -Compress -Depth 4"
)


class WakeSendStatus(str, Enum):
    """Finite outcomes of one wake-command invocation."""

    SENT = "SENT"
    REFUSED = "REFUSED"


class WakeSendFailure(str, Enum):
    """Finite reasons the wake could not be delivered."""

    ARGUMENTS_INVALID = "ARGUMENTS_INVALID"
    PAYLOAD_UNREADABLE = "PAYLOAD_UNREADABLE"
    AGENTAPI_UNAVAILABLE = "AGENTAPI_UNAVAILABLE"
    NO_LANGUAGE_SERVER = "NO_LANGUAGE_SERVER"
    SEND_FAILED = "SEND_FAILED"


@dataclass(frozen=True, slots=True)
class LanguageServerCandidate:
    """One reachable address and the token its process was started with."""

    address: str
    token: str


def default_agentapi_path() -> Path:
    """The real client shipped with the IDE, for this user."""

    return Path.home() / _AGENTAPI_RELATIVE


def enumerate_candidates() -> tuple[LanguageServerCandidate, ...]:
    """Read every running language server's token and listening ports.

    A process may listen on several ports and only one speaks the agent API,
    so every pairing is returned and the probe decides which one is real.
    """

    try:
        completed = subprocess.run(
            ("powershell", "-NoProfile", "-Command", _ENUMERATE_SCRIPT),
            capture_output=True,
            shell=False,
            timeout=_ENUMERATE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return ()
    if completed.returncode != 0:
        return ()
    try:
        parsed = json.loads(completed.stdout.decode("utf-8", errors="replace") or "[]")
    except ValueError:
        return ()
    if not isinstance(parsed, list):
        return ()

    candidates: list[LanguageServerCandidate] = []
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        command_line = entry.get("command_line")
        if not isinstance(command_line, str):
            continue
        match = _CSRF_PATTERN.search(command_line)
        if match is None:
            continue
        raw_ports = entry.get("ports")
        ports = raw_ports if isinstance(raw_ports, list) else [raw_ports]
        for port in ports:
            if isinstance(port, int):
                candidates.append(
                    LanguageServerCandidate(f"127.0.0.1:{port}", match.group(1))
                )
    return tuple(candidates)


def _invoke(
    agentapi_path: Path,
    candidate: LanguageServerCandidate,
    arguments: tuple[str, ...],
    timeout_seconds: int,
) -> subprocess.CompletedProcess[bytes] | None:
    environment = {
        **_inherited_environment(),
        "ANTIGRAVITY_LS_ADDRESS": candidate.address,
        "ANTIGRAVITY_CSRF_TOKEN": candidate.token,
    }
    try:
        return subprocess.run(
            ("cmd.exe", "/d", "/c", str(agentapi_path), *arguments),
            capture_output=True,
            shell=False,
            timeout=timeout_seconds,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _inherited_environment() -> dict[str, str]:
    return dict(os.environ)


def injected_candidate() -> LanguageServerCandidate | None:
    """The endpoint an operator supplied, when one was supplied."""

    address = os.environ.get(_ENDPOINT_ENVIRONMENT_KEY)
    token = os.environ.get(_TOKEN_ENVIRONMENT_KEY)
    if not address or not token:
        return None
    return LanguageServerCandidate(address, token)


def probe_candidate(agentapi_path: Path, candidate: LanguageServerCandidate) -> bool:
    """Ask one candidate a question with no side effect.

    An authenticated agent API answers `trajectory not found` for an unknown
    conversation. A wrong port resets the connection and a missing token is
    refused, so this single read separates the real endpoint from the rest
    without creating or touching any conversation.
    """

    completed = _invoke(
        agentapi_path,
        candidate,
        ("get-conversation-metadata", _PROBE_CONVERSATION_ID),
        _PROBE_TIMEOUT_SECONDS,
    )
    if completed is None:
        return False
    output = completed.stdout.decode("utf-8", errors="replace")
    return _AUTHENTICATED_MARKER in output


def discover_language_server(
    agentapi_path: Path,
    candidates: tuple[LanguageServerCandidate, ...] | None = None,
) -> LanguageServerCandidate | None:
    """The first candidate that proves it speaks the authenticated API.

    An injected endpoint is preferred when present, but it is probed exactly
    like a discovered one: supplying an address never substitutes for proving
    the server answers.
    """

    if candidates is None:
        injected = injected_candidate()
        pool = (injected,) if injected is not None else enumerate_candidates()
    else:
        pool = candidates
    for candidate in pool:
        if probe_candidate(agentapi_path, candidate):
            return candidate
    return None


def _wake_message(payload_file: Path) -> str:
    return (
        "[Johnny wake] A receipt-bound reviewer wake was delivered for you. "
        f"Read the wake payload at {payload_file} and act on it as the named "
        "reviewer. The payload carries identifiers only; follow the review "
        "instructions it names."
    )


def send_wake(
    conversation_id: str,
    payload_file: Path,
    agentapi_path: Path | None = None,
    candidates: tuple[LanguageServerCandidate, ...] | None = None,
) -> tuple[WakeSendStatus, WakeSendFailure | None]:
    """Discover the live server and deliver exactly one wake message."""

    client = default_agentapi_path() if agentapi_path is None else agentapi_path
    if not client.is_file():
        return WakeSendStatus.REFUSED, WakeSendFailure.AGENTAPI_UNAVAILABLE
    if not payload_file.is_file():
        return WakeSendStatus.REFUSED, WakeSendFailure.PAYLOAD_UNREADABLE

    candidate = discover_language_server(client, candidates)
    if candidate is None:
        return WakeSendStatus.REFUSED, WakeSendFailure.NO_LANGUAGE_SERVER

    completed = _invoke(
        client,
        candidate,
        (
            "send-message",
            "--title=johnny-reviewer-wake",
            conversation_id,
            _wake_message(payload_file),
        ),
        _SEND_TIMEOUT_SECONDS,
    )
    if completed is None or completed.returncode != 0:
        return WakeSendStatus.REFUSED, WakeSendFailure.SEND_FAILED
    return WakeSendStatus.SENT, None


def main(argv: tuple[str, ...]) -> int:
    """Emit exactly one typed JSON line; exit 0 only when one wake was sent."""

    conversation_id: str | None = None
    payload: str | None = None
    client: str | None = None
    remaining = list(argv)
    while remaining:
        item = remaining.pop(0)
        if item == "--conversation":
            conversation_id = remaining.pop(0) if remaining else None
        elif item.startswith("--conversation="):
            conversation_id = item.split("=", 1)[1]
        elif item == "--agentapi":
            client = remaining.pop(0) if remaining else None
        elif item.startswith("--agentapi="):
            client = item.split("=", 1)[1]
        elif payload is None:
            payload = item

    if not conversation_id or not payload:
        print(
            json.dumps(
                {
                    "status": WakeSendStatus.REFUSED.value,
                    "code": WakeSendFailure.ARGUMENTS_INVALID.value,
                },
                sort_keys=True,
            )
        )
        return 2

    status, failure = send_wake(
        conversation_id,
        Path(payload),
        agentapi_path=Path(client) if client else None,
    )
    payload_line: dict[str, object] = {"status": status.value}
    if failure is not None:
        payload_line["code"] = failure.value
    print(json.dumps(payload_line, sort_keys=True))
    return 0 if status is WakeSendStatus.SENT else 2


if __name__ == "__main__":
    raise SystemExit(main(tuple(sys.argv[1:])))


__all__ = [
    "LanguageServerCandidate",
    "WakeSendFailure",
    "WakeSendStatus",
    "default_agentapi_path",
    "discover_language_server",
    "enumerate_candidates",
    "injected_candidate",
    "main",
    "probe_candidate",
    "send_wake",
]
