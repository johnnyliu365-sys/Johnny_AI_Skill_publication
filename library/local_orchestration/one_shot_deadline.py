"""One-shot monotonic supervision deadlines with exact replacement semantics."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock, Timer
from time import monotonic_ns
from typing import Callable, Protocol

from pydantic import ValidationError

from library.workflow_router.deadline_contracts import (
    DeadlineArmRequest,
    DeadlineArmResult,
    DeadlineArmStatus,
    DeadlineCancelRequest,
    DeadlineCancelResult,
    DeadlineCancelStatus,
    DeadlineFailureKind,
    DeadlineFailureSignal,
    DeadlineSignal,
)


class MonotonicClockPort(Protocol):
    def now_ms(self) -> int: ...


class OneShotTimerPort(Protocol):
    def start(self) -> None: ...

    def cancel(self) -> None: ...


class OneShotTimerFactory(Protocol):
    def create(self, delay_seconds: float, callback: Callable[[], None]) -> OneShotTimerPort: ...


class DeadlineSignalSink(Protocol):
    def on_deadline(self, signal: DeadlineSignal) -> None: ...

    def on_deadline_failure(self, signal: DeadlineFailureSignal) -> None: ...


class OneShotDeadlinePort(Protocol):
    def arm(self, request: DeadlineArmRequest) -> DeadlineArmResult: ...

    def cancel(self, request: DeadlineCancelRequest) -> DeadlineCancelResult: ...


class OneShotDeadlineFactory(Protocol):
    def create(self, sink: DeadlineSignalSink) -> OneShotDeadlinePort: ...


class SystemMonotonicClock:
    def now_ms(self) -> int:
        return monotonic_ns() // 1_000_000


class ThreadingOneShotTimerFactory:
    def create(self, delay_seconds: float, callback: Callable[[], None]) -> OneShotTimerPort:
        timer = Timer(delay_seconds, callback)
        timer.daemon = True
        return timer


@dataclass(frozen=True, slots=True)
class MonotonicOneShotDeadlineFactory:
    clock: MonotonicClockPort
    timer_factory: OneShotTimerFactory | None = None

    def create(self, sink: DeadlineSignalSink) -> MonotonicOneShotDeadlinePort:
        return MonotonicOneShotDeadlinePort(
            sink,
            clock=self.clock,
            timer_factory=self.timer_factory,
        )


_BindingKey = tuple[str, str, str, str]


@dataclass(slots=True)
class _ActiveDeadline:
    request: DeadlineArmRequest
    generation: int
    timer: OneShotTimerPort


def _binding_key(request: DeadlineArmRequest | DeadlineCancelRequest) -> _BindingKey:
    if isinstance(request, DeadlineArmRequest):
        lease = request.lease
        return (
            lease.project_id,
            lease.ticket_ref,
            lease.router_receipt_ref,
            lease.task_ref,
        )
    return (
        request.project_id,
        request.ticket_ref,
        request.router_receipt_ref,
        request.task_ref,
    )


class MonotonicOneShotDeadlinePort:
    """Own at most one non-recurring timer for each exact execution binding."""

    def __init__(
        self,
        sink: DeadlineSignalSink,
        *,
        clock: MonotonicClockPort | None = None,
        timer_factory: OneShotTimerFactory | None = None,
    ) -> None:
        self._sink = sink
        self._clock = clock if clock is not None else SystemMonotonicClock()
        self._timer_factory = (
            timer_factory if timer_factory is not None else ThreadingOneShotTimerFactory()
        )
        self._lock = Lock()
        self._active: dict[_BindingKey, _ActiveDeadline] = {}
        self._next_generation = 1

    def arm(self, request: DeadlineArmRequest) -> DeadlineArmResult:
        if type(request) is not DeadlineArmRequest:
            return DeadlineArmResult(status=DeadlineArmStatus.REJECTED)
        try:
            trusted = DeadlineArmRequest.model_validate(request, strict=True)
            now_ms = self._clock.now_ms()
        except (ValidationError, OSError, RuntimeError, ValueError):
            return DeadlineArmResult(status=DeadlineArmStatus.UNAVAILABLE)
        if now_ms < 0:
            return DeadlineArmResult(status=DeadlineArmStatus.UNAVAILABLE)
        key = _binding_key(trusted)
        with self._lock:
            current = self._active.get(key)
            if current is not None and current.request == trusted:
                return DeadlineArmResult(
                    status=DeadlineArmStatus.ARMED,
                    lease_id=trusted.lease.lease_id,
                )
            generation = self._next_generation
            self._next_generation += 1
            delay_seconds = max(0, trusted.lease.deadline_ms - now_ms) / 1_000
            try:
                timer = self._timer_factory.create(
                    delay_seconds,
                    lambda: self._fire(key, generation),
                )
                replacement = _ActiveDeadline(trusted, generation, timer)
                self._active[key] = replacement
                timer.start()
            except (OSError, RuntimeError, ValueError):
                if current is None:
                    self._active.pop(key, None)
                else:
                    self._active[key] = current
                return DeadlineArmResult(status=DeadlineArmStatus.UNAVAILABLE)
            if current is not None:
                current.timer.cancel()
            return DeadlineArmResult(
                status=(
                    DeadlineArmStatus.REPLACED
                    if current is not None
                    else DeadlineArmStatus.ARMED
                ),
                lease_id=trusted.lease.lease_id,
            )

    def cancel(self, request: DeadlineCancelRequest) -> DeadlineCancelResult:
        if type(request) is not DeadlineCancelRequest:
            return DeadlineCancelResult(status=DeadlineCancelStatus.REJECTED)
        try:
            trusted = DeadlineCancelRequest.model_validate(request, strict=True)
        except ValidationError:
            return DeadlineCancelResult(status=DeadlineCancelStatus.REJECTED)
        key = _binding_key(trusted)
        with self._lock:
            current = self._active.get(key)
            if current is None:
                return DeadlineCancelResult(status=DeadlineCancelStatus.ALREADY_CLOSED)
            if current.request.lease.lease_id != trusted.lease_id:
                return DeadlineCancelResult(status=DeadlineCancelStatus.REJECTED)
            self._active.pop(key)
            current.timer.cancel()
        return DeadlineCancelResult(status=DeadlineCancelStatus.CANCELLED)

    def _fire(self, key: _BindingKey, generation: int) -> None:
        with self._lock:
            current = self._active.get(key)
            if current is None or current.generation != generation:
                return
            self._active.pop(key)
        lease = current.request.lease
        try:
            fired_at_ms = self._clock.now_ms()
            if fired_at_ms < lease.deadline_ms:
                self._sink.on_deadline_failure(
                    DeadlineFailureSignal(
                        lease_id=lease.lease_id,
                        project_id=lease.project_id,
                        ticket_ref=lease.ticket_ref,
                        router_receipt_ref=lease.router_receipt_ref,
                        task_ref=lease.task_ref,
                        failure=DeadlineFailureKind.TIMER_UNAVAILABLE,
                    )
                )
                return
            signal = DeadlineSignal(
                lease_id=lease.lease_id,
                project_id=lease.project_id,
                ticket_ref=lease.ticket_ref,
                router_receipt_ref=lease.router_receipt_ref,
                task_ref=lease.task_ref,
                fired_at_ms=fired_at_ms,
            )
            self._sink.on_deadline(signal)
        except (OSError, RuntimeError, TypeError, ValueError, ValidationError):
            self._sink.on_deadline_failure(
                DeadlineFailureSignal(
                    lease_id=lease.lease_id,
                    project_id=lease.project_id,
                    ticket_ref=lease.ticket_ref,
                    router_receipt_ref=lease.router_receipt_ref,
                    task_ref=lease.task_ref,
                    failure=DeadlineFailureKind.CALLBACK_FAILED,
                )
            )


__all__ = [
    "DeadlineSignalSink",
    "MonotonicClockPort",
    "MonotonicOneShotDeadlinePort",
    "MonotonicOneShotDeadlineFactory",
    "OneShotDeadlineFactory",
    "OneShotDeadlinePort",
    "OneShotTimerFactory",
    "OneShotTimerPort",
    "SystemMonotonicClock",
    "ThreadingOneShotTimerFactory",
]
