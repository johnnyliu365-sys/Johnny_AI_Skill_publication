"""Validated project profiles and the default router-framework POC profile."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import model_validator

from .contracts import (
    ArtifactKind,
    AuthorityState,
    CapabilityRef,
    CompletionActionKind,
    DeliveryStage,
    ExpectedReturnContract,
    HumanWaitReason,
    ImplementationReturnStatus,
    ModelRole,
    ModelRoleAssignment,
    NonBlankText,
    OpaqueMetadataId,
    ProcessStage,
    ReturnContractKind,
    RoleActivityState,
    RouterEventKind,
    RouterModel,
    RouterOutcome,
    SkillReference,
)


class TransitionRule(RouterModel):
    """One closed, profile-owned transition rule."""

    skill_reference: SkillReference
    expected_return: ExpectedReturnContract
    current_stage: ProcessStage
    event_kind: RouterEventKind
    outcome: RouterOutcome
    next_stage: ProcessStage | None
    required_authority: AuthorityState | None = None
    required_source_kinds: tuple[ArtifactKind, ...] = ()
    eligible_capabilities: tuple[CapabilityRef, ...] = ()
    requires_human_approval: bool = False
    wait_reason: HumanWaitReason | None = None
    accepted_completion_actions: tuple[CompletionActionKind, ...] = ()
    requires_implementation_handoff: bool = False
    requires_dispatch_receipt: bool = False

    @model_validator(mode="after")
    def human_gate_is_a_declared_wait(self) -> TransitionRule:
        """Keep human waits explicit rather than treating every suspend as an approval wait."""

        if self.requires_human_approval and self.outcome is not RouterOutcome.SUSPEND:
            raise ValueError("human approval gates must suspend")
        if self.requires_human_approval and self.wait_reason is None:
            raise ValueError("human approval gates require a precise wait reason")
        if not self.requires_human_approval and self.wait_reason is not None:
            raise ValueError("only human approval gates may declare a wait reason")
        if self.outcome in (RouterOutcome.ADVANCE, RouterOutcome.RETRY) and self.next_stage is None:
            raise ValueError("advancing and retry rules require next_stage")
        if self.outcome is RouterOutcome.SUSPEND and self.next_stage is not None:
            raise ValueError("suspending rules must not declare a next stage")
        if self.outcome is RouterOutcome.STOP and self.next_stage is not ProcessStage.STOPPED:
            raise ValueError("stop rules must target stopped")
        if self.event_kind not in (
            RouterEventKind.ACTION_COMPLETED,
            RouterEventKind.IMPLEMENTATION_RETURNED,
        ) and self.accepted_completion_actions:
            raise ValueError("only action_completed rules may accept completion actions")
        if self.requires_implementation_handoff and (
            self.current_stage is not ProcessStage.TICKETS
            or self.event_kind is not RouterEventKind.TICKET_DISPATCH_REQUIRED
            or self.outcome is not RouterOutcome.SUSPEND
            or self.next_stage is not None
        ):
            raise ValueError(
                "implementation handoff is valid only for the ticket dispatch question"
            )
        if self.requires_dispatch_receipt and (
            self.current_stage is not ProcessStage.TICKETS
            or self.event_kind is not RouterEventKind.IMPLEMENTATION_DISPATCH_CONFIRMED
            or self.outcome is not RouterOutcome.ADVANCE
            or self.next_stage is not ProcessStage.GRILL
        ):
            raise ValueError(
                "dispatch receipts are valid only for confirmed ticket dispatch advancing to grill"
            )
        return self


class ProjectWorkflowProfile(RouterModel):
    """Project-specific policy injected into the reusable routing engine."""

    profile_id: NonBlankText
    profile_version: NonBlankText
    delivery_stage: DeliveryStage
    router_control_reference: SkillReference
    halt_return_contract: ExpectedReturnContract
    transition_rules: tuple[TransitionRule, ...]
    shared_context_ref: OpaqueMetadataId
    architecture_owner_capability_ref: OpaqueMetadataId
    model_role_assignments: tuple[ModelRoleAssignment, ...]

    @model_validator(mode="after")
    def has_unique_transition_keys(self) -> ProjectWorkflowProfile:
        """Reject ambiguous state/event rules before a graph is compiled."""

        keys = tuple((rule.current_stage, rule.event_kind) for rule in self.transition_rules)
        if len(keys) != len(set(keys)):
            raise ValueError("each current_stage and event_kind pair must have one rule")
        if self.router_control_reference.reference_id != "router-control":
            raise ValueError("profile fallback must use the router-control reference")
        if self.halt_return_contract.return_kind is not ReturnContractKind.NO_RETURN:
            raise ValueError("profile halt return contract must be no-return")
        if (
            self.halt_return_contract.contract_revision
            != self.router_control_reference.source_revision
        ):
            raise ValueError("profile fallback contract revision must match its reference")
        if self.shared_context_ref == self.architecture_owner_capability_ref:
            raise ValueError("shared Context and architecture capability IDs must be distinct")
        roles = tuple(assignment.role for assignment in self.model_role_assignments)
        if len(roles) != len(ModelRole) or set(roles) != set(ModelRole):
            raise ValueError("profiles require exactly one assignment for every model role")
        if any(
            assignment.project_profile_ref != self.profile_id
            for assignment in self.model_role_assignments
        ):
            raise ValueError("model role assignments must bind the exact profile")
        role_references = tuple(
            reference
            for assignment in self.model_role_assignments
            for reference in (
                assignment.model_ref,
                *assignment.capability_refs,
                *assignment.evidence_refs,
            )
        )
        if len(role_references) != len(set(role_references)):
            raise ValueError("model role references must be distinct within a profile")
        metadata_references = (
            self.shared_context_ref,
            self.architecture_owner_capability_ref,
        )
        forbidden_tokens = ("file", "prompt", "secret")
        if any(
            marker in tuple(reference.casefold().split("-"))
            for reference in metadata_references
            for marker in forbidden_tokens
        ) or any(
            marker in reference.casefold()
            for reference in metadata_references
            for marker in ("://", "\\", "/")
        ):
            raise ValueError("profile references must remain metadata-only")
        references: dict[OpaqueMetadataId, SkillReference] = {
            self.router_control_reference.reference_id: self.router_control_reference
        }
        for rule in self.transition_rules:
            if rule.expected_return.contract_revision != rule.skill_reference.source_revision:
                raise ValueError("transition contract revision must match its skill reference")
            prior_reference = references.get(rule.skill_reference.reference_id)
            if prior_reference is not None and prior_reference != rule.skill_reference:
                raise ValueError("one policy reference ID cannot have conflicting metadata")
            references[rule.skill_reference.reference_id] = rule.skill_reference
        return self

    def rule_for(
        self,
        *,
        current_stage: ProcessStage,
        event_kind: RouterEventKind,
    ) -> TransitionRule | None:
        """Find the one declared rule for this state/event pair."""

        for rule in self.transition_rules:
            if rule.current_stage is current_stage and rule.event_kind is event_kind:
                return rule
        return None


@dataclass(frozen=True)
class _PolicyRoute:
    """One frozen input-to-primary-action contract in the POC profile."""

    current_stage: ProcessStage
    event_kind: RouterEventKind
    reference_id: OpaqueMetadataId
    return_kind: ReturnContractKind
    router_events: tuple[RouterEventKind, ...]
    implementation_statuses: tuple[ImplementationReturnStatus, ...]


_POLICY_REFERENCES: tuple[SkillReference, ...] = (
    SkillReference(
        reference_id="router-control",
        source_revision="rev-9b005bbc31dca89d",
        content_digest="sha256_9b005bbc31dca89d7e2e9394f095543c03c0ae5dd7eeaca70197d2a887466c0c",
    ),
    SkillReference(
        reference_id="discovery-change",
        source_revision="rev-a1687d4fa9960e43",
        content_digest="sha256_a1687d4fa9960e439e7e390c4d9cdc4d62db6d93d69e4123dce0cc970b72216a",
    ),
    SkillReference(
        reference_id="context-routing",
        source_revision="rev-e1ce913609aa6971",
        content_digest="sha256_e1ce913609aa6971c75155eace49562dace117c270f82d358c57ba7be238d867",
    ),
    SkillReference(
        reference_id="specification-ticketing",
        source_revision="rev-26e443dfca8e8434",
        content_digest="sha256_26e443dfca8e84342bb2ca40d748ac155a2b34010fcd6dc7fd5b59c6de5936b3",
    ),
    SkillReference(
        reference_id="implementation-authority",
        source_revision="rev-855117ed19c9c952",
        content_digest="sha256_855117ed19c9c952f8903bc56ce070d2cf3805fb51d7a450c46bbf8a00480f50",
    ),
    SkillReference(
        reference_id="implementation-tdd",
        source_revision="rev-d17c86ca12905a7b",
        content_digest="sha256_d17c86ca12905a7b4a34977b9926243f7e1d02f03c541f98bc85cf4c7083d0b3",
    ),
    SkillReference(
        reference_id="review-checks",
        source_revision="rev-0589a1d06beafc2b",
        content_digest="sha256_0589a1d06beafc2ba42b8c24b448497f7973e7f6f88d18e349891e5769b9cf4d",
    ),
)


_POLICY_ROUTES: tuple[_PolicyRoute, ...] = (
    _PolicyRoute(
        ProcessStage.INTAKE,
        RouterEventKind.INTAKE,
        "discovery-change",
        ReturnContractKind.ROUTER_EVENT,
        (
            RouterEventKind.WAYFINDER_GO,
            RouterEventKind.WAYFINDER_NO_GO,
            RouterEventKind.WAYFINDER_INFO_REQUIRED,
        ),
        (),
    ),
    _PolicyRoute(
        ProcessStage.WAYFINDER,
        RouterEventKind.WAYFINDER_GO,
        "discovery-change",
        ReturnContractKind.ROUTER_EVENT,
        (RouterEventKind.ACTION_COMPLETED,),
        (),
    ),
    _PolicyRoute(
        ProcessStage.WAYFINDER,
        RouterEventKind.WAYFINDER_INFO_REQUIRED,
        "discovery-change",
        ReturnContractKind.ROUTER_EVENT,
        (RouterEventKind.OWNER_INPUT_PROVIDED,),
        (),
    ),
    _PolicyRoute(
        ProcessStage.WAYFINDER,
        RouterEventKind.OWNER_INPUT_PROVIDED,
        "discovery-change",
        ReturnContractKind.ROUTER_EVENT,
        (
            RouterEventKind.WAYFINDER_GO,
            RouterEventKind.WAYFINDER_NO_GO,
            RouterEventKind.WAYFINDER_INFO_REQUIRED,
        ),
        (),
    ),
    _PolicyRoute(
        ProcessStage.WAYFINDER,
        RouterEventKind.WAYFINDER_NO_GO,
        "router-control",
        ReturnContractKind.NO_RETURN,
        (),
        (),
    ),
    _PolicyRoute(
        ProcessStage.ARCHITECTURE,
        RouterEventKind.ACTION_COMPLETED,
        "discovery-change",
        ReturnContractKind.ROUTER_EVENT,
        (RouterEventKind.ACTION_COMPLETED,),
        (),
    ),
    _PolicyRoute(
        ProcessStage.GRILL,
        RouterEventKind.ACTION_COMPLETED,
        "context-routing",
        ReturnContractKind.ROUTER_EVENT,
        (RouterEventKind.ACTION_COMPLETED,),
        (),
    ),
    _PolicyRoute(
        ProcessStage.CONTEXT,
        RouterEventKind.ACTION_COMPLETED,
        "specification-ticketing",
        ReturnContractKind.ROUTER_EVENT,
        (RouterEventKind.ACTION_COMPLETED,),
        (),
    ),
    _PolicyRoute(
        ProcessStage.SPEC,
        RouterEventKind.ACTION_COMPLETED,
        "specification-ticketing",
        ReturnContractKind.ROUTER_EVENT,
        (RouterEventKind.APPROVAL_GRANTED, RouterEventKind.APPROVAL_DENIED),
        (),
    ),
    _PolicyRoute(
        ProcessStage.SPEC,
        RouterEventKind.APPROVAL_GRANTED,
        "specification-ticketing",
        ReturnContractKind.ROUTER_EVENT,
        (RouterEventKind.TICKET_DISPATCH_REQUIRED,),
        (),
    ),
    _PolicyRoute(
        ProcessStage.TICKETS,
        RouterEventKind.TICKET_DISPATCH_REQUIRED,
        "implementation-authority",
        ReturnContractKind.ROUTER_EVENT,
        (RouterEventKind.IMPLEMENTATION_DISPATCH_CONFIRMED,),
        (),
    ),
    _PolicyRoute(
        ProcessStage.TICKETS,
        RouterEventKind.IMPLEMENTATION_DISPATCH_CONFIRMED,
        "discovery-change",
        ReturnContractKind.ROUTER_EVENT,
        (RouterEventKind.ACTION_COMPLETED,),
        (),
    ),
    _PolicyRoute(
        ProcessStage.IMPLEMENT,
        RouterEventKind.IMPLEMENTATION_RETURNED,
        "implementation-tdd",
        ReturnContractKind.ROUTER_EVENT,
        (RouterEventKind.VALIDATION_PASSED, RouterEventKind.VALIDATION_FAILED),
        (),
    ),
    _PolicyRoute(
        ProcessStage.GRILL,
        RouterEventKind.INTEGRATION_COMPLETED,
        "discovery-change",
        ReturnContractKind.ROUTER_EVENT,
        (RouterEventKind.ACTION_COMPLETED,),
        (),
    ),
    _PolicyRoute(
        ProcessStage.GRILL,
        RouterEventKind.AUDIT_COMPLETED,
        "review-checks",
        ReturnContractKind.ROUTER_EVENT,
        (RouterEventKind.ACTION_COMPLETED,),
        (),
    ),
    _PolicyRoute(
        ProcessStage.IMPLEMENT,
        RouterEventKind.ACTION_COMPLETED,
        "implementation-tdd",
        ReturnContractKind.ROUTER_EVENT,
        (RouterEventKind.VALIDATION_PASSED, RouterEventKind.VALIDATION_FAILED),
        (),
    ),
    _PolicyRoute(
        ProcessStage.SMOKE_TEST,
        RouterEventKind.VALIDATION_PASSED,
        "review-checks",
        ReturnContractKind.ROUTER_EVENT,
        (RouterEventKind.ACTION_COMPLETED,),
        (),
    ),
    _PolicyRoute(
        ProcessStage.SMOKE_TEST,
        RouterEventKind.VALIDATION_FAILED,
        "implementation-tdd",
        ReturnContractKind.IMPLEMENTATION_RETURN,
        (),
        (
            ImplementationReturnStatus.COMPLETED,
            ImplementationReturnStatus.BLOCKED,
            ImplementationReturnStatus.CHANGE_DETECTED,
        ),
    ),
    _PolicyRoute(
        ProcessStage.REVIEW,
        RouterEventKind.ACTION_COMPLETED,
        "review-checks",
        ReturnContractKind.ROUTER_EVENT,
        (RouterEventKind.ACTION_COMPLETED,),
        (),
    ),
    _PolicyRoute(
        ProcessStage.HANDOFF,
        RouterEventKind.ACTION_COMPLETED,
        "router-control",
        ReturnContractKind.NO_RETURN,
        (),
        (),
    ),
    _PolicyRoute(
        ProcessStage.IMPLEMENT,
        RouterEventKind.REQUIREMENT_CHANGED,
        "discovery-change",
        ReturnContractKind.ROUTER_EVENT,
        (RouterEventKind.ACTION_COMPLETED,),
        (),
    ),
)


def _route_policy_for(
    *,
    current_stage: ProcessStage,
    event_kind: RouterEventKind,
) -> _PolicyRoute:
    """Return the one frozen primary-action contract for a state/event pair."""

    for policy in _POLICY_ROUTES:
        if policy.current_stage is current_stage and policy.event_kind is event_kind:
            return policy
    raise ValueError("the POC profile has no frozen policy route for this state/event")


def _policy_reference_for(reference_id: OpaqueMetadataId) -> SkillReference:
    """Resolve one frozen metadata-only policy reference without reading its file."""

    for reference in _POLICY_REFERENCES:
        if reference.reference_id == reference_id:
            return reference
    raise ValueError("the POC profile has no frozen policy reference with this ID")


def _skill_reference_for(
    *,
    current_stage: ProcessStage,
    event_kind: RouterEventKind,
) -> SkillReference:
    """Select the exact versioned policy reference for one declared transition."""

    policy = _route_policy_for(current_stage=current_stage, event_kind=event_kind)
    return _policy_reference_for(policy.reference_id)


def _expected_return_for(
    *,
    current_stage: ProcessStage,
    event_kind: RouterEventKind,
) -> ExpectedReturnContract:
    """Select the exact typed return produced by the primary next action."""

    policy = _route_policy_for(current_stage=current_stage, event_kind=event_kind)
    reference = _policy_reference_for(policy.reference_id)
    contract_id: OpaqueMetadataId = (
        f"return-{current_stage.value.replace('_', '-')}-"
        f"{event_kind.value.replace('_', '-')}"
    )
    return ExpectedReturnContract(
        contract_id=contract_id,
        contract_revision=reference.source_revision,
        return_kind=policy.return_kind,
        router_events=policy.router_events,
        implementation_statuses=policy.implementation_statuses,
    )


def build_router_poc_profile() -> ProjectWorkflowProfile:
    """Build the closed profile used by the framework's own POC."""

    wayfinder = CapabilityRef(
        capability_id="cap-wayfinder",
        version="1",
        agent_profile="wayfinder",
    )
    architecture = CapabilityRef(
        capability_id="cap-architecture",
        version="1",
        agent_profile="architecture",
    )
    grill = CapabilityRef(
        capability_id="cap-grill",
        version="1",
        agent_profile="grill",
    )
    context = CapabilityRef(
        capability_id="cap-context",
        version="1",
        agent_profile="context",
    )
    specification = CapabilityRef(
        capability_id="cap-specification",
        version="1",
        agent_profile="specification",
    )
    tickets = CapabilityRef(
        capability_id="cap-tickets",
        version="1",
        agent_profile="tickets",
    )
    implementation = CapabilityRef(
        capability_id="cap-implementation",
        version="1",
        agent_profile="implementation",
    )
    smoke_test = CapabilityRef(
        capability_id="cap-smoke-test",
        version="1",
        agent_profile="smoke-test",
    )
    review = CapabilityRef(
        capability_id="cap-review",
        version="1",
        agent_profile="review",
    )
    handoff = CapabilityRef(
        capability_id="cap-handoff",
        version="1",
        agent_profile="handoff",
    )
    model_role_assignments = (
        ModelRoleAssignment(
            project_profile_ref="router-framework-poc",
            role=ModelRole.ARCHITECTURE_OWNER,
            model_ref="model-architecture-owner",
            capability_refs=("cap-architecture-owner",),
            activity_state=RoleActivityState.ACTIVE,
            evidence_refs=("evidence-architecture-owner",),
        ),
        ModelRoleAssignment(
            project_profile_ref="router-framework-poc",
            role=ModelRole.SUPERVISOR_REVIEWER,
            model_ref="model-supervisor-reviewer",
            capability_refs=("cap-supervisor-reviewer",),
            activity_state=RoleActivityState.ACTIVE,
            evidence_refs=("evidence-supervisor-reviewer",),
        ),
        ModelRoleAssignment(
            project_profile_ref="router-framework-poc",
            role=ModelRole.IMPLEMENTATION_OWNER,
            model_ref="model-implementation-owner",
            capability_refs=("cap-implementation-owner",),
            activity_state=RoleActivityState.ACTIVE,
            evidence_refs=("evidence-implementation-owner",),
        ),
        ModelRoleAssignment(
            project_profile_ref="router-framework-poc",
            role=ModelRole.RESEARCH_HELPER,
            model_ref="model-research-helper",
            capability_refs=("cap-research-helper",),
            activity_state=RoleActivityState.SLEEPING,
            evidence_refs=("evidence-research-helper",),
        ),
    )
    return ProjectWorkflowProfile(
        profile_id="router-framework-poc",
        profile_version="2",
        delivery_stage=DeliveryStage.POC,
        router_control_reference=_policy_reference_for("router-control"),
        halt_return_contract=ExpectedReturnContract(
            contract_id="router-control-no-return",
            contract_revision=_policy_reference_for("router-control").source_revision,
            return_kind=ReturnContractKind.NO_RETURN,
            router_events=(),
            implementation_statuses=(),
        ),
        transition_rules=(
            TransitionRule(
                skill_reference=_skill_reference_for(
                    current_stage=ProcessStage.INTAKE,
                    event_kind=RouterEventKind.INTAKE,
                ),
                expected_return=_expected_return_for(
                    current_stage=ProcessStage.INTAKE,
                    event_kind=RouterEventKind.INTAKE,
                ),
                current_stage=ProcessStage.INTAKE,
                event_kind=RouterEventKind.INTAKE,
                outcome=RouterOutcome.ADVANCE,
                next_stage=ProcessStage.WAYFINDER,
                required_source_kinds=(ArtifactKind.PROJECT_GOAL,),
                eligible_capabilities=(wayfinder,),
            ),
            TransitionRule(
                skill_reference=_skill_reference_for(
                    current_stage=ProcessStage.WAYFINDER,
                    event_kind=RouterEventKind.WAYFINDER_GO,
                ),
                expected_return=_expected_return_for(
                    current_stage=ProcessStage.WAYFINDER,
                    event_kind=RouterEventKind.WAYFINDER_GO,
                ),
                current_stage=ProcessStage.WAYFINDER,
                event_kind=RouterEventKind.WAYFINDER_GO,
                outcome=RouterOutcome.ADVANCE,
                next_stage=ProcessStage.ARCHITECTURE,
                required_source_kinds=(ArtifactKind.WAYFINDER_OUTPUT,),
                eligible_capabilities=(architecture,),
            ),
            TransitionRule(
                skill_reference=_skill_reference_for(
                    current_stage=ProcessStage.WAYFINDER,
                    event_kind=RouterEventKind.WAYFINDER_NO_GO,
                ),
                expected_return=_expected_return_for(
                    current_stage=ProcessStage.WAYFINDER,
                    event_kind=RouterEventKind.WAYFINDER_NO_GO,
                ),
                current_stage=ProcessStage.WAYFINDER,
                event_kind=RouterEventKind.WAYFINDER_NO_GO,
                outcome=RouterOutcome.STOP,
                next_stage=ProcessStage.STOPPED,
                required_source_kinds=(ArtifactKind.WAYFINDER_OUTPUT,),
            ),
            TransitionRule(
                skill_reference=_skill_reference_for(
                    current_stage=ProcessStage.WAYFINDER,
                    event_kind=RouterEventKind.WAYFINDER_INFO_REQUIRED,
                ),
                expected_return=_expected_return_for(
                    current_stage=ProcessStage.WAYFINDER,
                    event_kind=RouterEventKind.WAYFINDER_INFO_REQUIRED,
                ),
                current_stage=ProcessStage.WAYFINDER,
                event_kind=RouterEventKind.WAYFINDER_INFO_REQUIRED,
                outcome=RouterOutcome.SUSPEND,
                next_stage=None,
                required_source_kinds=(ArtifactKind.WAYFINDER_INFO_REQUEST,),
                requires_human_approval=True,
                wait_reason=HumanWaitReason.WAYFINDER_INPUT_GAP,
            ),
            TransitionRule(
                skill_reference=_skill_reference_for(
                    current_stage=ProcessStage.WAYFINDER,
                    event_kind=RouterEventKind.OWNER_INPUT_PROVIDED,
                ),
                expected_return=_expected_return_for(
                    current_stage=ProcessStage.WAYFINDER,
                    event_kind=RouterEventKind.OWNER_INPUT_PROVIDED,
                ),
                current_stage=ProcessStage.WAYFINDER,
                event_kind=RouterEventKind.OWNER_INPUT_PROVIDED,
                outcome=RouterOutcome.RETRY,
                next_stage=ProcessStage.WAYFINDER,
                required_source_kinds=(ArtifactKind.PROJECT_GOAL,),
                eligible_capabilities=(wayfinder,),
            ),
            TransitionRule(
                skill_reference=_skill_reference_for(
                    current_stage=ProcessStage.ARCHITECTURE,
                    event_kind=RouterEventKind.ACTION_COMPLETED,
                ),
                expected_return=_expected_return_for(
                    current_stage=ProcessStage.ARCHITECTURE,
                    event_kind=RouterEventKind.ACTION_COMPLETED,
                ),
                current_stage=ProcessStage.ARCHITECTURE,
                event_kind=RouterEventKind.ACTION_COMPLETED,
                outcome=RouterOutcome.ADVANCE,
                next_stage=ProcessStage.GRILL,
                required_source_kinds=(ArtifactKind.ARCHITECTURE,),
                eligible_capabilities=(grill,),
                accepted_completion_actions=(CompletionActionKind.DOCUMENTATION,),
            ),
            TransitionRule(
                skill_reference=_skill_reference_for(
                    current_stage=ProcessStage.GRILL,
                    event_kind=RouterEventKind.ACTION_COMPLETED,
                ),
                expected_return=_expected_return_for(
                    current_stage=ProcessStage.GRILL,
                    event_kind=RouterEventKind.ACTION_COMPLETED,
                ),
                current_stage=ProcessStage.GRILL,
                event_kind=RouterEventKind.ACTION_COMPLETED,
                outcome=RouterOutcome.ADVANCE,
                next_stage=ProcessStage.CONTEXT,
                required_source_kinds=(ArtifactKind.GRILL,),
                eligible_capabilities=(context,),
                accepted_completion_actions=(CompletionActionKind.DOCUMENTATION,),
            ),
            TransitionRule(
                skill_reference=_skill_reference_for(
                    current_stage=ProcessStage.CONTEXT,
                    event_kind=RouterEventKind.ACTION_COMPLETED,
                ),
                expected_return=_expected_return_for(
                    current_stage=ProcessStage.CONTEXT,
                    event_kind=RouterEventKind.ACTION_COMPLETED,
                ),
                current_stage=ProcessStage.CONTEXT,
                event_kind=RouterEventKind.ACTION_COMPLETED,
                outcome=RouterOutcome.ADVANCE,
                next_stage=ProcessStage.SPEC,
                required_source_kinds=(ArtifactKind.CONTEXT,),
                eligible_capabilities=(specification,),
                accepted_completion_actions=(CompletionActionKind.DOCUMENTATION,),
            ),
            TransitionRule(
                skill_reference=_skill_reference_for(
                    current_stage=ProcessStage.SPEC,
                    event_kind=RouterEventKind.ACTION_COMPLETED,
                ),
                expected_return=_expected_return_for(
                    current_stage=ProcessStage.SPEC,
                    event_kind=RouterEventKind.ACTION_COMPLETED,
                ),
                current_stage=ProcessStage.SPEC,
                event_kind=RouterEventKind.ACTION_COMPLETED,
                outcome=RouterOutcome.SUSPEND,
                next_stage=None,
                required_source_kinds=(ArtifactKind.SPEC,),
                requires_human_approval=True,
                wait_reason=HumanWaitReason.SPECIFICATION_APPROVAL_REQUIRED,
                accepted_completion_actions=(CompletionActionKind.DOCUMENTATION,),
            ),
            TransitionRule(
                skill_reference=_skill_reference_for(
                    current_stage=ProcessStage.SPEC,
                    event_kind=RouterEventKind.APPROVAL_GRANTED,
                ),
                expected_return=_expected_return_for(
                    current_stage=ProcessStage.SPEC,
                    event_kind=RouterEventKind.APPROVAL_GRANTED,
                ),
                current_stage=ProcessStage.SPEC,
                event_kind=RouterEventKind.APPROVAL_GRANTED,
                outcome=RouterOutcome.ADVANCE,
                next_stage=ProcessStage.TICKETS,
                required_authority=AuthorityState.APPROVED,
                required_source_kinds=(ArtifactKind.SPEC,),
                eligible_capabilities=(tickets,),
            ),
            TransitionRule(
                skill_reference=_skill_reference_for(
                    current_stage=ProcessStage.TICKETS,
                    event_kind=RouterEventKind.TICKET_DISPATCH_REQUIRED,
                ),
                expected_return=_expected_return_for(
                    current_stage=ProcessStage.TICKETS,
                    event_kind=RouterEventKind.TICKET_DISPATCH_REQUIRED,
                ),
                current_stage=ProcessStage.TICKETS,
                event_kind=RouterEventKind.TICKET_DISPATCH_REQUIRED,
                outcome=RouterOutcome.SUSPEND,
                next_stage=None,
                required_source_kinds=(ArtifactKind.TICKET,),
                requires_human_approval=True,
                wait_reason=HumanWaitReason.TICKET_DISPATCH_CONFIRMATION_REQUIRED,
                requires_implementation_handoff=True,
            ),
            TransitionRule(
                skill_reference=_skill_reference_for(
                    current_stage=ProcessStage.TICKETS,
                    event_kind=RouterEventKind.IMPLEMENTATION_DISPATCH_CONFIRMED,
                ),
                expected_return=_expected_return_for(
                    current_stage=ProcessStage.TICKETS,
                    event_kind=RouterEventKind.IMPLEMENTATION_DISPATCH_CONFIRMED,
                ),
                current_stage=ProcessStage.TICKETS,
                event_kind=RouterEventKind.IMPLEMENTATION_DISPATCH_CONFIRMED,
                outcome=RouterOutcome.ADVANCE,
                next_stage=ProcessStage.GRILL,
                required_authority=AuthorityState.APPROVED,
                required_source_kinds=(ArtifactKind.TICKET,),
                eligible_capabilities=(grill,),
                requires_dispatch_receipt=True,
            ),
            TransitionRule(
                skill_reference=_skill_reference_for(
                    current_stage=ProcessStage.IMPLEMENT,
                    event_kind=RouterEventKind.IMPLEMENTATION_RETURNED,
                ),
                expected_return=_expected_return_for(
                    current_stage=ProcessStage.IMPLEMENT,
                    event_kind=RouterEventKind.IMPLEMENTATION_RETURNED,
                ),
                current_stage=ProcessStage.IMPLEMENT,
                event_kind=RouterEventKind.IMPLEMENTATION_RETURNED,
                outcome=RouterOutcome.ADVANCE,
                next_stage=ProcessStage.SMOKE_TEST,
                required_source_kinds=(ArtifactKind.TICKET,),
                eligible_capabilities=(smoke_test,),
                accepted_completion_actions=(CompletionActionKind.IMPLEMENTATION,),
            ),
            TransitionRule(
                skill_reference=_skill_reference_for(
                    current_stage=ProcessStage.GRILL,
                    event_kind=RouterEventKind.INTEGRATION_COMPLETED,
                ),
                expected_return=_expected_return_for(
                    current_stage=ProcessStage.GRILL,
                    event_kind=RouterEventKind.INTEGRATION_COMPLETED,
                ),
                current_stage=ProcessStage.GRILL,
                event_kind=RouterEventKind.INTEGRATION_COMPLETED,
                outcome=RouterOutcome.ADVANCE,
                next_stage=ProcessStage.GRILL,
                required_source_kinds=(ArtifactKind.TICKET,),
                eligible_capabilities=(grill,),
            ),
            TransitionRule(
                skill_reference=_skill_reference_for(
                    current_stage=ProcessStage.GRILL,
                    event_kind=RouterEventKind.AUDIT_COMPLETED,
                ),
                expected_return=_expected_return_for(
                    current_stage=ProcessStage.GRILL,
                    event_kind=RouterEventKind.AUDIT_COMPLETED,
                ),
                current_stage=ProcessStage.GRILL,
                event_kind=RouterEventKind.AUDIT_COMPLETED,
                outcome=RouterOutcome.ADVANCE,
                next_stage=ProcessStage.REVIEW,
                required_authority=AuthorityState.APPROVED,
                required_source_kinds=(ArtifactKind.TICKET,),
                eligible_capabilities=(review,),
            ),
            TransitionRule(
                skill_reference=_skill_reference_for(
                    current_stage=ProcessStage.IMPLEMENT,
                    event_kind=RouterEventKind.ACTION_COMPLETED,
                ),
                expected_return=_expected_return_for(
                    current_stage=ProcessStage.IMPLEMENT,
                    event_kind=RouterEventKind.ACTION_COMPLETED,
                ),
                current_stage=ProcessStage.IMPLEMENT,
                event_kind=RouterEventKind.ACTION_COMPLETED,
                outcome=RouterOutcome.ADVANCE,
                next_stage=ProcessStage.SMOKE_TEST,
                required_source_kinds=(ArtifactKind.TICKET,),
                eligible_capabilities=(smoke_test,),
                accepted_completion_actions=(CompletionActionKind.IMPLEMENTATION,),
            ),
            TransitionRule(
                skill_reference=_skill_reference_for(
                    current_stage=ProcessStage.SMOKE_TEST,
                    event_kind=RouterEventKind.VALIDATION_PASSED,
                ),
                expected_return=_expected_return_for(
                    current_stage=ProcessStage.SMOKE_TEST,
                    event_kind=RouterEventKind.VALIDATION_PASSED,
                ),
                current_stage=ProcessStage.SMOKE_TEST,
                event_kind=RouterEventKind.VALIDATION_PASSED,
                outcome=RouterOutcome.ADVANCE,
                next_stage=ProcessStage.REVIEW,
                required_source_kinds=(ArtifactKind.TICKET,),
                eligible_capabilities=(review,),
            ),
            TransitionRule(
                skill_reference=_skill_reference_for(
                    current_stage=ProcessStage.SMOKE_TEST,
                    event_kind=RouterEventKind.VALIDATION_FAILED,
                ),
                expected_return=_expected_return_for(
                    current_stage=ProcessStage.SMOKE_TEST,
                    event_kind=RouterEventKind.VALIDATION_FAILED,
                ),
                current_stage=ProcessStage.SMOKE_TEST,
                event_kind=RouterEventKind.VALIDATION_FAILED,
                outcome=RouterOutcome.RETRY,
                next_stage=ProcessStage.IMPLEMENT,
                required_source_kinds=(ArtifactKind.TICKET,),
                eligible_capabilities=(implementation,),
            ),
            TransitionRule(
                skill_reference=_skill_reference_for(
                    current_stage=ProcessStage.REVIEW,
                    event_kind=RouterEventKind.ACTION_COMPLETED,
                ),
                expected_return=_expected_return_for(
                    current_stage=ProcessStage.REVIEW,
                    event_kind=RouterEventKind.ACTION_COMPLETED,
                ),
                current_stage=ProcessStage.REVIEW,
                event_kind=RouterEventKind.ACTION_COMPLETED,
                outcome=RouterOutcome.ADVANCE,
                next_stage=ProcessStage.HANDOFF,
                required_source_kinds=(ArtifactKind.TICKET,),
                eligible_capabilities=(handoff,),
                accepted_completion_actions=(CompletionActionKind.REVIEW,),
            ),
            TransitionRule(
                skill_reference=_skill_reference_for(
                    current_stage=ProcessStage.HANDOFF,
                    event_kind=RouterEventKind.ACTION_COMPLETED,
                ),
                expected_return=_expected_return_for(
                    current_stage=ProcessStage.HANDOFF,
                    event_kind=RouterEventKind.ACTION_COMPLETED,
                ),
                current_stage=ProcessStage.HANDOFF,
                event_kind=RouterEventKind.ACTION_COMPLETED,
                outcome=RouterOutcome.STOP,
                next_stage=ProcessStage.STOPPED,
                required_source_kinds=(ArtifactKind.TICKET,),
                accepted_completion_actions=(CompletionActionKind.HANDOFF,),
            ),
            TransitionRule(
                skill_reference=_skill_reference_for(
                    current_stage=ProcessStage.IMPLEMENT,
                    event_kind=RouterEventKind.REQUIREMENT_CHANGED,
                ),
                expected_return=_expected_return_for(
                    current_stage=ProcessStage.IMPLEMENT,
                    event_kind=RouterEventKind.REQUIREMENT_CHANGED,
                ),
                current_stage=ProcessStage.IMPLEMENT,
                event_kind=RouterEventKind.REQUIREMENT_CHANGED,
                outcome=RouterOutcome.ADVANCE,
                next_stage=ProcessStage.GRILL,
                required_source_kinds=(ArtifactKind.CHANGE,),
                eligible_capabilities=(grill,),
            ),
        ),
        shared_context_ref="ctx-shared-project",
        architecture_owner_capability_ref="cap-architecture-owner",
        model_role_assignments=model_role_assignments,
    )


def build_plugin_distribution_profile() -> ProjectWorkflowProfile:
    """Build the profile-bound policy for the plugin-distribution POC."""

    base_profile = build_router_poc_profile()
    profile_id = "plugin-distribution-poc-r02"
    return ProjectWorkflowProfile(
        profile_id=profile_id,
        profile_version="2",
        delivery_stage=base_profile.delivery_stage,
        router_control_reference=base_profile.router_control_reference,
        halt_return_contract=base_profile.halt_return_contract,
        transition_rules=base_profile.transition_rules,
        shared_context_ref="ctx-plugin-distribution-r02",
        architecture_owner_capability_ref="cap-plugin-distribution-architecture-owner-r02",
        model_role_assignments=(
            ModelRoleAssignment(
                project_profile_ref=profile_id,
                role=ModelRole.ARCHITECTURE_OWNER,
                model_ref="model-gpt-5-6-sol-xhigh-architecture-r02",
                capability_refs=("cap-plugin-distribution-architecture-r02",),
                activity_state=RoleActivityState.ACTIVE,
                evidence_refs=("evidence-owner-approved-plugin-architecture-r02",),
            ),
            ModelRoleAssignment(
                project_profile_ref=profile_id,
                role=ModelRole.SUPERVISOR_REVIEWER,
                model_ref="model-gpt-5-6-terra-high-senior-r02",
                capability_refs=("cap-plugin-distribution-ticket-review-r02",),
                activity_state=RoleActivityState.ACTIVE,
                evidence_refs=("evidence-owner-approved-terra-senior-r02",),
            ),
            ModelRoleAssignment(
                project_profile_ref=profile_id,
                role=ModelRole.IMPLEMENTATION_OWNER,
                model_ref="model-gpt-5-6-luna-xhigh-implementer-r02",
                capability_refs=("cap-plugin-distribution-implementation-r02",),
                activity_state=RoleActivityState.SLEEPING,
                evidence_refs=("evidence-owner-approved-luna-implementer-r02",),
            ),
            ModelRoleAssignment(
                project_profile_ref=profile_id,
                role=ModelRole.RESEARCH_HELPER,
                model_ref="model-gpt-5-6-luna-readonly-helper-r02",
                capability_refs=("cap-plugin-distribution-readonly-research-r02",),
                activity_state=RoleActivityState.SLEEPING,
                evidence_refs=("evidence-reviewer-owned-helper-policy-r02",),
            ),
        ),
    )
