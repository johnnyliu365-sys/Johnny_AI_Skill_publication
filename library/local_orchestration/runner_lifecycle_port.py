"""Real `RunnerLifecyclePort`: one detached event runner per project.

Start spawns a detached child that outlives this process; stop writes the
owner's stop sentinel and waits a bounded time for the runner to record its
own `STOPPED` state. Nothing here polls Git — the sentinel is the only thing
the lifecycle observes, and the runner itself sleeps on native ref signals.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from library.workflow_router.contracts import OpaqueMetadataId, ProjectId

from .event_runner import runner_state_path, stop_sentinel_path
from .johnny_root_layout import JohnnyRootLayout
from .project_runner_registry import (
    RunnerStartCapabilityUnavailable,
    RunnerStartResult,
    RunnerStarted,
    RunnerStopCapabilityUnavailable,
    RunnerStopped,
    RunnerStopResult,
)

_PID_FILE_NAME = "runner.pid"
_RUNNER_MODULE = "library.local_orchestration.event_runner_main"
_START_TIMEOUT_SECONDS = 30.0
_STOP_TIMEOUT_SECONDS = 30.0
_OBSERVE_INTERVAL_SECONDS = 0.25
_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200


def runner_pid_path(layout: JohnnyRootLayout) -> Path:
    return layout.queue_root / _PID_FILE_NAME


def read_runner_state(layout: JohnnyRootLayout) -> dict[str, object] | None:
    path = runner_state_path(layout)
    if not path.is_file():
        return None
    try:
        recorded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return recorded if type(recorded) is dict else None


class RealRunnerLifecyclePort:
    """Spawn and stop the Johnny-owned event runner for one project."""

    def __init__(
        self,
        layout: JohnnyRootLayout,
        python_executable: Path | None = None,
        plugin_root: Path | None = None,
    ) -> None:
        self._layout = layout
        self._python = (
            python_executable
            if python_executable is not None
            else layout.venv_python
        )
        self._plugin_root = (
            plugin_root if plugin_root is not None else layout.plugin_root
        )

    def _await_state(self, expected: str, timeout_seconds: float) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            state = read_runner_state(self._layout)
            if state is not None and state.get("status") == expected:
                return True
            if state is not None and state.get("status") == "BLOCKED":
                return False
            time.sleep(_OBSERVE_INTERVAL_SECONDS)
        return False

    def start(self, project_ref: ProjectId) -> RunnerStartResult:
        if not self._python.is_file() or not self._plugin_root.is_dir():
            return RunnerStartCapabilityUnavailable()
        pid_path = runner_pid_path(self._layout)
        if pid_path.exists():
            # One project has at most one runner; an existing pid is not ours
            # to replace from here.
            return RunnerStartCapabilityUnavailable()
        environment = dict(os.environ)
        environment["JOHNNY_ROOT"] = str(self._layout.base)
        environment["PYTHONPATH"] = str(self._plugin_root)
        try:
            child = subprocess.Popen(
                (str(self._python), "-X", "utf8", "-m", _RUNNER_MODULE),
                cwd=str(self._plugin_root),
                env=environment,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP,
            )
        except (OSError, ValueError):
            return RunnerStartCapabilityUnavailable()
        try:
            pid_path.parent.mkdir(parents=True, exist_ok=True)
            pid_path.write_text(str(child.pid), encoding="utf-8")
        except OSError:
            return RunnerStartCapabilityUnavailable()
        if not self._await_state("RUNNING", _START_TIMEOUT_SECONDS):
            self.stop(project_ref, "runner")
            return RunnerStartCapabilityUnavailable()
        return RunnerStarted(runner_ref="runner")

    def stop(
        self, project_ref: ProjectId, runner_ref: OpaqueMetadataId
    ) -> RunnerStopResult:
        pid_path = runner_pid_path(self._layout)
        stop_path = stop_sentinel_path(self._layout)
        try:
            stop_path.parent.mkdir(parents=True, exist_ok=True)
            stop_path.write_text("stop", encoding="utf-8")
        except OSError:
            return RunnerStopCapabilityUnavailable()
        stopped = self._await_state("STOPPED", _STOP_TIMEOUT_SECONDS)
        try:
            if pid_path.exists():
                pid_path.unlink()
        except OSError:
            return RunnerStopCapabilityUnavailable()
        if not stopped:
            # The sentinel is in place but the runner never acknowledged it;
            # its state is unknown rather than proven stopped.
            return RunnerStopCapabilityUnavailable()
        return RunnerStopped()


__all__ = ["RealRunnerLifecyclePort", "read_runner_state", "runner_pid_path"]
