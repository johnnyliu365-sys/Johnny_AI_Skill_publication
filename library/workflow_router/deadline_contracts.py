"""Strong contracts for one-shot monotonic supervision deadlines."""

from __future__ import annotations

from enum import Enum
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from .contracts import ProjectId
from .role_wake_contracts import (
    DeadlineCapabilityState,
    MonotonicDeadlineCapabilityProof,
)
from .supervision_policy import (
    LeaseId,
    LeaseLifecycle,
    MonotonicMilliseconds,
    ReceiptReference,
    SupervisionLease,
    TaskReference,
    TicketReference,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
        revalidate_instances="always",
    )


class DeadlineArmStatus(str, Enum):
    ARMED = "ARMED"
    REPLACED = "REPLACED"
    REJECTED = "REJECTED"
    UNAVAILABLE = "UNAVAILABLE"


class DeadlineCancelStatus(str, Enum):
    CANCELLED = "CANCELLED"
    ALREADY_CLOSED = "ALREADY_CLOSED"
    REJECTED = "REJECTED"


class DeadlineFailureKind(str, Enum):
    TIMER_UNAVAILABLE = "TIMER_UNAVAILABLE"
    CALLBACK_FAILED = "CALLBACK_FAILED"


class DeadlineArmRequest(_StrictModel):
    lease: SupervisionLease
    capability: MonotonicDeadlineCapabilityProof

    @model_validator(mode="after")
    def capability_binds_active_lease(self) -> Self:
        lease = self.lease
        capability = self.capability
        if lease.lifecycle is not LeaseLifecycle.ACTIVE:
            raise ValueError("only an active supervision lease may be armed")
        if capability.state is not DeadlineCapabilityState.PROVEN:
            raise ValueError("deadline capability must be proven")
        if not capability.one_shot_supported or capability.recurring_callback_required:
            raise ValueError("deadline capability must be one-shot without recurrence")
        if (
            capability.project_id != lease.project_id
            or capability.ticket_ref != lease.ticket_ref
            or capability.router_receipt_ref != lease.router_receipt_ref
            or capability.implementation_task_ref != lease.task_ref
        ):
            raise ValueError("deadline capability must bind the exact lease")
        return self


class DeadlineArmResult(_StrictModel):
    status: DeadlineArmStatus
    lease_id: LeaseId | None = None

    @model_validator(mode="after")
    def identity_exists_only_when_armed(self) -> Self:
        accepted = self.status in (DeadlineArmStatus.ARMED, DeadlineArmStatus.REPLACED)
        if accepted != (self.lease_id is not None):
            raise ValueError("only an armed deadline carries its lease identity")
        return self


class DeadlineCancelRequest(_StrictModel):
    lease_id: LeaseId
    project_id: ProjectId
    ticket_ref: TicketReference
    router_receipt_ref: ReceiptReference
    task_ref: TaskReference


class DeadlineCancelResult(_StrictModel):
    status: DeadlineCancelStatus


class DeadlineSignal(_StrictModel):
    lease_id: LeaseId
    project_id: ProjectId
    ticket_ref: TicketReference
    router_receipt_ref: ReceiptReference
    task_ref: TaskReference
    fired_at_ms: MonotonicMilliseconds


class DeadlineFailureSignal(_StrictModel):
    lease_id: LeaseId
    project_id: ProjectId
    ticket_ref: TicketReference
    router_receipt_ref: ReceiptReference
    task_ref: TaskReference
    failure: DeadlineFailureKind


def cancel_request_for(lease: SupervisionLease) -> DeadlineCancelRequest:
    """Project the exact identity needed to close one armed deadline."""

    return DeadlineCancelRequest(
        lease_id=lease.lease_id,
        project_id=lease.project_id,
        ticket_ref=lease.ticket_ref,
        router_receipt_ref=lease.router_receipt_ref,
        task_ref=lease.task_ref,
    )


__all__ = [
    "DeadlineArmRequest",
    "DeadlineArmResult",
    "DeadlineArmStatus",
    "DeadlineCancelRequest",
    "DeadlineCancelResult",
    "DeadlineCancelStatus",
    "DeadlineFailureKind",
    "DeadlineFailureSignal",
    "DeadlineSignal",
    "cancel_request_for",
]
