"""Pure model-role specification readiness admission."""

from __future__ import annotations

from .contracts import (
    ModelRole,
    RoleActivityState,
    SpecificationClosureKind,
    SpecificationReadinessAssessment,
    SpecificationReadinessBlocker,
    SpecificationReadinessDecision,
    SpecificationReadinessRequest,
    SpecificationWakeReason,
)
from .profile import ProjectWorkflowProfile


_WAKE_REASON_ORDER: dict[SpecificationWakeReason, int] = {
    reason: index for index, reason in enumerate(SpecificationWakeReason)
}


def _assessment(
    profile: ProjectWorkflowProfile,
    request: SpecificationReadinessRequest,
    decision: SpecificationReadinessDecision,
    wake_reason: SpecificationWakeReason | None,
) -> SpecificationReadinessAssessment:
    return SpecificationReadinessAssessment(
        project_profile_ref=profile.profile_id,
        project_profile_version=profile.profile_version,
        specification_ref=request.specification_ref,
        specification_revision=request.specification_revision,
        decision=decision,
        wake_reason=wake_reason,
    )


def _lowest_blocker_reason(
    blockers: tuple[SpecificationReadinessBlocker, ...],
) -> SpecificationWakeReason:
    return min(
        (blocker.reason for blocker in blockers),
        key=lambda reason: _WAKE_REASON_ORDER[reason],
    )


class ModelRoleReadinessGate:
    """Assess whether the exact specification may enter supervisor control."""

    @staticmethod
    def assess(
        profile: ProjectWorkflowProfile,
        request: SpecificationReadinessRequest,
    ) -> SpecificationReadinessAssessment:
        """Apply the frozen owner, blocker, closure and supervisor precedence."""

        if (
            request.project_profile_ref != profile.profile_id
            or request.project_profile_version != profile.profile_version
        ):
            raise ValueError("readiness request must bind the exact profile")
        if request.owner_approval_ref is None:
            return _assessment(
                profile,
                request,
                SpecificationReadinessDecision.OWNER_APPROVAL_REQUIRED,
                None,
            )
        if request.blockers:
            return _assessment(
                profile,
                request,
                SpecificationReadinessDecision.ARCHITECTURE_OWNER_REQUIRED,
                _lowest_blocker_reason(request.blockers),
            )
        closure_kinds = frozenset(evidence.kind for evidence in request.closure_evidence)
        expected_closure_kinds = frozenset(SpecificationClosureKind)
        if closure_kinds != expected_closure_kinds:
            return _assessment(
                profile,
                request,
                SpecificationReadinessDecision.ARCHITECTURE_OWNER_REQUIRED,
                SpecificationWakeReason.CLOSURE_INCOMPLETE,
            )
        if request.open_design_decision_refs:
            return _assessment(
                profile,
                request,
                SpecificationReadinessDecision.ARCHITECTURE_OWNER_REQUIRED,
                SpecificationWakeReason.OPEN_DESIGN_DECISION,
            )
        supervisor = next(
            assignment
            for assignment in profile.model_role_assignments
            if assignment.role is ModelRole.SUPERVISOR_REVIEWER
        )
        if not (supervisor.activity_state is RoleActivityState.ACTIVE) or not supervisor.capability_refs:
            return _assessment(
                profile,
                request,
                SpecificationReadinessDecision.ARCHITECTURE_OWNER_REQUIRED,
                SpecificationWakeReason.SUPERVISOR_CAPABILITY_UNAVAILABLE,
            )
        return _assessment(
            profile,
            request,
            SpecificationReadinessDecision.READY_FOR_SUPERVISION,
            None,
        )
