"""Windows-native exact Git ref hints using overlapped directory notifications.

The native bindings this module needs (`pywin32`) exist only on Windows, and
`requirements-dev.txt` installs them only under `sys_platform == "win32"` --
so importing this module on any other platform, or on Windows without the
package present, must still succeed. Ticket 21 is what makes that true:
whether a native watch can actually be armed is reported by value through
`probe_ref_watch_capability`, in the same finite shape
`wake_capability.probe_wake_capability` already uses for the (unrelated) host
wake command -- a bounded status plus, on failure, exactly one named reason,
never a boolean and never inferred from something else being empty.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
import subprocess
import sys
from threading import current_thread, Lock, Thread
from typing import cast, Final, Self, TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from library.workflow_router.git_handoff_contracts import (
    GitNativeFailureKind,
    GitNativeFailureSignal,
    GitNativeRegistrationRequest,
    GitNativeRegistrationResult,
    GitNativeRegistrationStatus,
    GitRefSignal,
    SubscriptionId,
)
from .git_handoff_event_adapter import NativeGitRefSignalSink

# `_NATIVE_IMPORT_ERROR` is the one fact every other name in this module
# ultimately depends on: `None` only when the four modules below both exist
# and imported cleanly. It is computed once, here, rather than re-probed on
# every call -- an interpreter that has already imported (or already failed
# to import) a module gets the same answer for the rest of the process.
_NATIVE_IMPORT_ERROR: str | None

if TYPE_CHECKING:
    import _win32typing
    import pywintypes
    import win32con
    import win32event
    import win32file

    _NATIVE_IMPORT_ERROR = None
else:
    try:
        import pywintypes
        import win32con
        import win32event
        import win32file
    except ImportError as _import_error:
        pywintypes = None  # type: ignore[assignment]
        win32con = None  # type: ignore[assignment]
        win32event = None  # type: ignore[assignment]
        win32file = None  # type: ignore[assignment]
        _NATIVE_IMPORT_ERROR = str(_import_error)
    else:
        _NATIVE_IMPORT_ERROR = None


class RefWatchCapabilityStatus(str, Enum):
    """Finite outcomes of asking whether this process can arm a native watch."""

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class RefWatchCapabilityFailure(str, Enum):
    """Finite reasons a native exact-ref watch cannot be armed here.

    `PLATFORM_UNSUPPORTED` and `NATIVE_BINDING_UNAVAILABLE` are kept apart on
    purpose: the first is "this OS has no such API", the second is "this is
    Windows but the optional `pywin32` dependency did not import". Collapsing
    them would hide which of two very different remedies applies.
    """

    PLATFORM_UNSUPPORTED = "PLATFORM_UNSUPPORTED"
    NATIVE_BINDING_UNAVAILABLE = "NATIVE_BINDING_UNAVAILABLE"


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
    )


class RefWatchCapabilityResult(_StrictModel):
    """Exactly one available capability or exactly one named failure.

    Mirrors `WakeCapabilityProbeResult`'s shape so "no watcher" (this type,
    `UNAVAILABLE` with a name) and "a watcher with nothing to report" (an
    empty queue elsewhere) can never be read as the same fact -- one is a
    capability result, the other is a queue being quiet, and nothing here
    lets a caller confuse the two by construction.
    """

    status: RefWatchCapabilityStatus
    failure: RefWatchCapabilityFailure | None = None

    @model_validator(mode="after")
    def exact_capability_shape(self) -> Self:
        if self.status is RefWatchCapabilityStatus.AVAILABLE:
            if self.failure is not None:
                raise ValueError("an available capability carries no failure")
        elif self.failure is None:
            raise ValueError("an unavailable capability names exactly one failure")
        return self


def probe_ref_watch_capability() -> RefWatchCapabilityResult:
    """Whether this process can arm a native exact-ref watch, and why not.

    Takes no argument and trusts no caller-supplied claim: the answer comes
    only from facts this interpreter can observe about itself (the running
    platform, and whether the native bindings actually imported), the same
    "prove it, do not take it on faith" rule `probe_wake_capability` follows
    for the host wake command.
    """

    if sys.platform != "win32":
        return RefWatchCapabilityResult(
            status=RefWatchCapabilityStatus.UNAVAILABLE,
            failure=RefWatchCapabilityFailure.PLATFORM_UNSUPPORTED,
        )
    if _NATIVE_IMPORT_ERROR is not None:
        return RefWatchCapabilityResult(
            status=RefWatchCapabilityStatus.UNAVAILABLE,
            failure=RefWatchCapabilityFailure.NATIVE_BINDING_UNAVAILABLE,
        )
    return RefWatchCapabilityResult(status=RefWatchCapabilityStatus.AVAILABLE)


_NOTIFY_FILTER: int | None = (
    None
    if _NATIVE_IMPORT_ERROR is not None
    else win32con.FILE_NOTIFY_CHANGE_FILE_NAME | win32con.FILE_NOTIFY_CHANGE_LAST_WRITE
)
_FILE_LIST_DIRECTORY: Final[int] = 0x0001


@dataclass(frozen=True, slots=True)
class _WatchSpec:
    directory: Path
    subtree: bool
    exact_names: frozenset[str]
    name_prefixes: tuple[str, ...]

    def matches(self, raw_name: str) -> bool:
        normalized = raw_name.replace("\\", "/").casefold()
        return normalized in self.exact_names or any(
            normalized.startswith(prefix) for prefix in self.name_prefixes
        )


@dataclass(slots=True)
class _ArmedWatch:
    spec: _WatchSpec
    handle: _win32typing.PyHANDLE
    buffer: _win32typing.PyOVERLAPPEDReadBuffer
    overlapped: _win32typing.PyOVERLAPPED


class _Subscription:
    def __init__(
        self,
        request: GitNativeRegistrationRequest,
        stop_event: int,
        watches: tuple[_ArmedWatch, ...],
    ) -> None:
        self.request = request
        self.stop_event = stop_event
        self.watches = watches
        self.thread: Thread | None = None


def _git_common_directory(repository_root: Path) -> Path:
    completed = subprocess.run(
        ("git", "-C", str(repository_root), "rev-parse", "--git-common-dir"),
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if completed.returncode != 0:
        raise ValueError("repository has no readable Git common directory")
    raw = Path(completed.stdout.strip())
    candidate = raw if raw.is_absolute() else repository_root / raw
    common = candidate.resolve(strict=True)
    if not common.is_dir():
        raise ValueError("Git common directory must be an existing directory")
    return common


def _loose_ref_spec(common: Path, exact_git_ref: str) -> _WatchSpec:
    ref_parts = PurePosixPath(exact_git_ref).parts
    target = common.joinpath(*ref_parts)
    ancestor = target.parent
    while not ancestor.exists():
        if ancestor == common:
            raise ValueError("Git ref metadata parent is unavailable")
        ancestor = ancestor.parent
    resolved_ancestor = ancestor.resolve(strict=True)
    resolved_ancestor.relative_to(common)
    relative = target.relative_to(resolved_ancestor).as_posix().casefold()
    return _WatchSpec(
        directory=resolved_ancestor,
        subtree=len(PurePosixPath(relative).parts) > 1,
        exact_names=frozenset((relative,)),
        name_prefixes=(),
    )


def _packed_ref_spec(common: Path) -> _WatchSpec:
    return _WatchSpec(
        directory=common,
        subtree=False,
        exact_names=frozenset(("packed-refs",)),
        name_prefixes=("packed-refs.",),
    )


class WindowsNativeGitRefNotificationPort:
    """One native notification composition per exact subscription, with no polling."""

    def __init__(self, repository_root: Path, sink: NativeGitRefSignalSink) -> None:
        if not isinstance(repository_root, Path):
            raise TypeError("repository root must be a Path")
        if not repository_root.is_absolute():
            raise ValueError("repository root must be absolute")
        root = repository_root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("repository root must be an existing directory")
        self._common = _git_common_directory(root)
        self._sink = sink
        self._lock = Lock()
        self._subscriptions: dict[SubscriptionId, _Subscription] = {}

    def register(self, request: GitNativeRegistrationRequest) -> GitNativeRegistrationResult:
        if type(request) is not GitNativeRegistrationRequest:
            return GitNativeRegistrationResult(status=GitNativeRegistrationStatus.REJECTED)
        try:
            trusted = GitNativeRegistrationRequest.model_validate(request, strict=True)
        except ValidationError:
            return GitNativeRegistrationResult(status=GitNativeRegistrationStatus.REJECTED)
        if _NATIVE_IMPORT_ERROR is not None:
            # No native binding imported, so no `win32*` name below this line
            # is safe to touch. Reported by value, the same as any other
            # native-side failure this method already returns -- not raised,
            # and never a silent pretence that a watch was armed.
            return GitNativeRegistrationResult(status=GitNativeRegistrationStatus.UNAVAILABLE)
        with self._lock:
            existing = self._subscriptions.get(trusted.subscription_id)
            if existing is not None:
                if existing.request == trusted:
                    return GitNativeRegistrationResult(
                        status=GitNativeRegistrationStatus.REGISTERED,
                        event_source_ref=trusted.event_source_ref,
                        subscription_id=trusted.subscription_id,
                    )
                return GitNativeRegistrationResult(status=GitNativeRegistrationStatus.REJECTED)
            opened_watches: list[_ArmedWatch] = []
            try:
                specs = (
                    _loose_ref_spec(self._common, trusted.exact_git_ref),
                    _packed_ref_spec(self._common),
                )
                for spec in specs:
                    opened_watches.append(self._open_and_arm(spec))
                watches = tuple(opened_watches)
                stop_event = win32event.CreateEvent(None, True, False, None)
            except (OSError, ValueError, pywintypes.error):
                self._close_watches(tuple(opened_watches))
                return GitNativeRegistrationResult(
                    status=GitNativeRegistrationStatus.UNAVAILABLE
                )
            subscription = _Subscription(trusted, stop_event, watches)
            thread = Thread(
                target=self._run_subscription,
                args=(subscription,),
                name=f"git-ref-{trusted.subscription_id}",
                daemon=True,
            )
            subscription.thread = thread
            self._subscriptions[trusted.subscription_id] = subscription
            try:
                thread.start()
            except RuntimeError:
                self._subscriptions.pop(trusted.subscription_id, None)
                self._close_watches(watches)
                win32file.CloseHandle(stop_event)
                return GitNativeRegistrationResult(
                    status=GitNativeRegistrationStatus.UNAVAILABLE
                )
            return GitNativeRegistrationResult(
                status=GitNativeRegistrationStatus.REGISTERED,
                event_source_ref=trusted.event_source_ref,
                subscription_id=trusted.subscription_id,
            )

    @staticmethod
    def _open_and_arm(spec: _WatchSpec) -> _ArmedWatch:
        handle = win32file.CreateFile(
            str(spec.directory),
            _FILE_LIST_DIRECTORY,
            win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE,
            None,
            win32con.OPEN_EXISTING,
            win32con.FILE_FLAG_BACKUP_SEMANTICS | win32con.FILE_FLAG_OVERLAPPED,
            None,
        )
        buffer = win32file.AllocateReadBuffer(8192)
        overlapped = pywintypes.OVERLAPPED()
        overlapped.hEvent = win32event.CreateEvent(None, True, False, None)
        watch = _ArmedWatch(spec, handle, buffer, overlapped)
        try:
            WindowsNativeGitRefNotificationPort._arm(watch)
        except pywintypes.error:
            handle.Close()
            win32file.CloseHandle(overlapped.hEvent)
            raise
        return watch

    @staticmethod
    def _arm(watch: _ArmedWatch) -> None:
        win32event.ResetEvent(watch.overlapped.hEvent)
        win32file.ReadDirectoryChangesW(
            int(watch.handle),
            watch.buffer,
            watch.spec.subtree,
            _NOTIFY_FILTER,
            watch.overlapped,
        )

    @staticmethod
    def _changed_names(watch: _ArmedWatch) -> tuple[str, ...]:
        byte_count = win32file.GetOverlappedResult(
            int(watch.handle),
            watch.overlapped,
            True,
        )
        if byte_count == 0:
            return ()
        raw: object = win32file.FILE_NOTIFY_INFORMATION(
            cast(str, watch.buffer), byte_count
        )
        if not isinstance(raw, (list, tuple)):
            return ()
        names: list[str] = []
        for item in raw:
            if not isinstance(item, tuple) or len(item) != 2:
                continue
            name = item[1]
            if isinstance(name, str):
                names.append(name)
        return tuple(names)

    def _run_subscription(self, subscription: _Subscription) -> None:
        wait_handles = [
            subscription.stop_event,
            *(watch.overlapped.hEvent for watch in subscription.watches),
        ]
        try:
            while True:
                wait_result = win32event.WaitForMultipleObjects(
                    wait_handles,
                    False,
                    win32event.INFINITE,
                )
                index = wait_result - win32event.WAIT_OBJECT_0
                if index == 0:
                    return
                if index < 1 or index > len(subscription.watches):
                    raise OSError("native wait returned an invalid handle index")
                watch = subscription.watches[index - 1]
                names = self._changed_names(watch)
                self._arm(watch)
                if any(watch.spec.matches(name) for name in names):
                    self._sink.on_signal(
                        GitRefSignal(
                            event_source_ref=subscription.request.event_source_ref,
                            subscription_id=subscription.request.subscription_id,
                        )
                    )
        except (OSError, pywintypes.error):
            self._sink.on_failure(
                GitNativeFailureSignal(
                    event_source_ref=subscription.request.event_source_ref,
                    subscription_id=subscription.request.subscription_id,
                    failure=GitNativeFailureKind.NOTIFICATION_UNAVAILABLE,
                )
            )
        finally:
            with self._lock:
                current = self._subscriptions.get(subscription.request.subscription_id)
                if current is subscription:
                    self._subscriptions.pop(subscription.request.subscription_id, None)
            self._close_watches(subscription.watches)
            win32file.CloseHandle(subscription.stop_event)

    def cancel(self, subscription_id: SubscriptionId) -> bool:
        with self._lock:
            subscription = self._subscriptions.pop(subscription_id, None)
        if subscription is None:
            return True
        win32event.SetEvent(subscription.stop_event)
        thread = subscription.thread
        if thread is not None and thread is not current_thread():
            thread.join(timeout=5.0)
        return thread is None or thread is current_thread() or not thread.is_alive()

    @staticmethod
    def _close_watches(watches: tuple[_ArmedWatch, ...]) -> None:
        for watch in watches:
            try:
                watch.handle.Close()
            except pywintypes.error:
                pass
            try:
                win32file.CloseHandle(watch.overlapped.hEvent)
            except pywintypes.error:
                pass


@dataclass(frozen=True, slots=True)
class WindowsNativeGitRefNotificationFactory:
    repository_root: Path

    def create(
        self,
        sink: NativeGitRefSignalSink,
    ) -> WindowsNativeGitRefNotificationPort:
        return WindowsNativeGitRefNotificationPort(self.repository_root, sink)


__all__ = [
    "NativeGitRefSignalSink",
    "RefWatchCapabilityFailure",
    "RefWatchCapabilityResult",
    "RefWatchCapabilityStatus",
    "WindowsNativeGitRefNotificationFactory",
    "WindowsNativeGitRefNotificationPort",
    "probe_ref_watch_capability",
]
