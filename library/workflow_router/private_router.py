"""Metadata-only Private Router POC with safe automatic continuation planning.

This module is deliberately an in-process, test-only boundary.  A later approved MVP
may replace ``RouterServicePort`` with a protected remote transport, but no source text,
URI, path, prompt, or ContextPacket crosses this boundary here.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Annotated, Literal, Protocol
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field, ValidationError, model_validator

from .contracts import (
    ArtifactKind,
    ArtifactRef,
    AuthorityState,
    CapabilityRef,
    CollaborationDispatchPlan,
    CollaborationTopology,
    CollaborationTopologyPlan,
    CompletionEvidence,
    ConsumerFingerprint,
    ContinuationDirective,
    DeliveryStage,
    HumanWaitReason,
    ImplementationHandoff,
    ImplementationReturn,
    ImplementationReturnStatus,
    NonBlankText,
    OpaqueMetadataId,
    PositiveTokenBudget,
    ProjectId,
    PendingDispatchDescriptor,
    ProcessStage,
    ResolvedContext,
    RouterEvent,
    RouterEventKind,
    RouterModel,
    RouterOutcome,
    RouterState,
    TicketDispatchConfirmation,
    TicketDispatchReceipt,
    TicketProposal,
)
from .profile import ProjectWorkflowProfile
from .policy_response import (
    ApprovedDispatchArtifactRegistry,
    CommittedDispatchArtifacts,
    DispatchResponseFormatter,
    FixedDispatchResponse,
    RenderError,
    RenderOutcome,
    RenderedDispatchResponse,
    StaticApprovedDispatchArtifactRegistry,
    resolve_approved_dispatch_artifact,
)
from .router import ContextResolver, RouterEngine


OpaqueAccountSubjectId = Annotated[str, Field(pattern=r"^acct_[0-9a-f]{16}$")]
OpaqueRequestId = Annotated[str, Field(pattern=r"^req_[0-9a-f]{32}$")]
OpaqueDecisionId = Annotated[str, Field(pattern=r"^dec_[0-9a-f]{32}$")]
OpaqueEventId = Annotated[str, Field(pattern=r"^evt_[0-9a-f]{32}$")]
RevisionDigest = Annotated[str, Field(pattern=r"^rev_[0-9a-f]{64}$")]
ClientVersion = Annotated[str, Field(pattern=r"^v[1-9][0-9]*$")]


class EntitlementMode(str, Enum):
    """The POC's closed entitlement categories; this is not payment processing."""

    FIRST_PROJECT_FREE = "first_project_free"
    STANDARD_PROJECT = "standard_project"
    ACTIVE_AUDIT = "active_audit"
    DENIED = "denied"


class RouterServiceErrorCode(str, Enum):
    """Stable public error codes that reveal no Profile or source detail."""

    ROUTER_INPUT_INVALID = "router_input_invalid"
    ROUTER_ENTITLEMENT_DENIED = "router_entitlement_denied"
    ROUTER_SERVICE_UNAVAILABLE = "router_service_unavailable"
    ROUTER_RESPONSE_INVALID = "router_response_invalid"
    ROUTER_POLICY_BLOCKED = "router_policy_blocked"


class ProductActionLabel(str, Enum):
    """Product-language labels.  Internal stage and Profile names are never UI labels."""

    DEFINE_STARTING_POINT = "define_starting_point"
    SHAPE_SOLUTION = "shape_solution"
    CONFIRM_ASSUMPTIONS = "confirm_assumptions"
    ORGANIZE_WORKSPACE = "organize_workspace"
    DRAFT_DELIVERY_PLAN = "draft_delivery_plan"
    PLAN_EXECUTION = "plan_execution"
    BUILD_AND_TEST = "build_and_test"
    VERIFY_DELIVERY = "verify_delivery"
    COMPLETE_HANDOFF = "complete_handoff"
    REQUEST_APPROVAL = "request_approval"


class ContinuationMode(str, Enum):
    """Local execution disposition after a validated private Router response."""

    AUTO_RUN = "auto_run"
    WAIT_FOR_HUMAN = "wait_for_human"
    HALT = "halt"


class RedactedSummary(RouterModel):
    """A finite, content-free summary; free prose and arbitrary dictionaries are impossible."""

    evidence_codes: tuple[Literal["goal_captured", "evidence_available", "validation_recorded"], ...]
    risk_codes: tuple[Literal["none", "requires_review", "external_dependency"], ...]
    source_count_bucket: Annotated[int, Field(ge=0, le=100)]

    @model_validator(mode="after")
    def has_at_least_one_finite_claim(self) -> RedactedSummary:
        """Reject empty summaries rather than treating missing evidence as a safe default."""

        if not self.evidence_codes and not self.risk_codes and self.source_count_bucket == 0:
            raise ValueError("structured_redacted_summary must contain a finite claim")
        return self


class RouterRequestEnvelope(RouterModel):
    """The complete local-to-private boundary; every field is typed and allowlisted."""

    request_id: OpaqueRequestId
    account_subject_id: OpaqueAccountSubjectId
    opaque_project_id: ProjectId
    project_entry_mode: Literal[
        "new_project", "inherited_audit", "repair", "deployment_preparation"
    ]
    entitlement_mode: EntitlementMode
    workflow_stage: ProcessStage
    authority_state: AuthorityState
    delivery_stage: DeliveryStage
    router_event_kind: RouterEventKind
    event_correlation_id: OpaqueEventId
    available_source_kinds: tuple[ArtifactKind, ...]
    revision_digests: tuple[RevisionDigest, ...]
    structured_redacted_summary: RedactedSummary
    client_version: ClientVersion
    completion_evidence: CompletionEvidence | None = None
    implementation_return: ImplementationReturn | None = None
    implementation_handoff: ImplementationHandoff | None = None
    topology: CollaborationTopology | None = None
    collaboration_plan: CollaborationTopologyPlan | None = None
    ticket_reference: OpaqueMetadataId | None = None
    dispatch_confirmation: TicketDispatchConfirmation | None = None
    dispatch_receipt: TicketDispatchReceipt | None = None
    ticket_proposal: TicketProposal | None = None

    @model_validator(mode="after")
    def has_minimum_metadata_without_locations(self) -> RouterRequestEnvelope:
        """Require finite availability and digest metadata before the request may travel."""

        if not self.available_source_kinds:
            raise ValueError("available_source_kinds must not be empty")
        if not self.revision_digests:
            raise ValueError("revision_digests must not be empty")
        if len(set(self.available_source_kinds)) != len(self.available_source_kinds):
            raise ValueError("available_source_kinds must not repeat")
        if len(set(self.revision_digests)) != len(self.revision_digests):
            raise ValueError("revision_digests must not repeat")
        if self.completion_evidence is not None and self.router_event_kind is not RouterEventKind.ACTION_COMPLETED:
            raise ValueError("completion_evidence requires action_completed")
        if self.implementation_return is not None:
            if self.completion_evidence is not None:
                raise ValueError("completion evidence and implementation return cannot share a request")
            if self.router_event_kind is not self.implementation_return.emitted_event:
                raise ValueError("implementation return event must match router_event_kind")
        if self.implementation_handoff is not None:
            if self.completion_evidence is not None or self.implementation_return is not None:
                raise ValueError("implementation handoff cannot share a request with completion or return")
            if (
                self.workflow_stage is not ProcessStage.TICKETS
                or self.router_event_kind
                not in (
                    RouterEventKind.APPROVAL_GRANTED,
                    RouterEventKind.TICKET_DISPATCH_REQUIRED,
                )
            ):
                raise ValueError("implementation handoff requires a ticket dispatch lifecycle event")
        if self.dispatch_confirmation is not None or self.dispatch_receipt is not None:
            if self.router_event_kind not in (
                RouterEventKind.TICKET_DISPATCH_REQUIRED,
                RouterEventKind.IMPLEMENTATION_DISPATCH_CONFIRMED,
            ):
                raise ValueError("dispatch metadata requires a ticket dispatch event")
        if (
            self.dispatch_receipt is not None
            and self.router_event_kind is not RouterEventKind.IMPLEMENTATION_DISPATCH_CONFIRMED
        ):
            raise ValueError("dispatch receipts require confirmed dispatch")
        if self.ticket_proposal is not None and self.router_event_kind is not RouterEventKind.TICKET_DISPATCH_REQUIRED:
            raise ValueError("ticket proposals require a dispatch-required event")
        return self


class RouterResponseEnvelope(RouterModel):
    """The service response contains only a safe action and metadata-only grants."""

    request_id: OpaqueRequestId
    decision_id: OpaqueDecisionId
    outcome: RouterOutcome
    continuation: ContinuationDirective
    next_stage: ProcessStage | None
    action_label: ProductActionLabel | None
    allowed_action_labels: tuple[ProductActionLabel, ...]
    required_source_kinds: tuple[ArtifactKind, ...]
    context_budget: PositiveTokenBudget | None
    error_code: RouterServiceErrorCode | None = None
    wait_reason: HumanWaitReason | None = None
    dispatch_plan: CollaborationDispatchPlan | None = None
    ticket_lane_capabilities: tuple[CapabilityRef, ...] = ()
    ticket_proposal: TicketProposal | None = None
    pending_dispatch: PendingDispatchDescriptor | None = None

    @model_validator(mode="after")
    def response_shape_is_safe_and_unambiguous(self) -> RouterResponseEnvelope:
        """Reject responses that could accidentally grant work after a failure."""

        if self.continuation is ContinuationDirective.AUTO_CONTINUE:
            if self.outcome not in (RouterOutcome.ADVANCE, RouterOutcome.RETRY):
                raise ValueError("automatic continuation requires an advancing decision")
            if self.next_stage is None or self.action_label is None or self.context_budget is None:
                raise ValueError("automatic continuation requires a complete local grant")
            if self.allowed_action_labels != (self.action_label,):
                raise ValueError("automatic continuation must grant exactly its displayed action")
            if self.error_code is not None:
                raise ValueError("automatic continuation cannot carry an error code")
            if self.wait_reason is not None:
                raise ValueError("automatic continuation cannot carry a human wait reason")
            if self.ticket_proposal is not None:
                raise ValueError("automatic continuation cannot carry an opened proposal")
            if self.pending_dispatch is not None:
                raise ValueError("automatic continuation cannot carry pending dispatch state")
            if self.dispatch_plan is None and self.ticket_lane_capabilities:
                raise ValueError("ticket-lane capabilities require a dispatch plan")
        elif self.continuation is ContinuationDirective.WAIT_FOR_HUMAN:
            if self.outcome is not RouterOutcome.SUSPEND:
                raise ValueError("human waits must be suspensions")
            if self.next_stage is not None or self.action_label is not ProductActionLabel.REQUEST_APPROVAL:
                raise ValueError("human waits must expose only the approval action")
            if self.allowed_action_labels or self.context_budget is not None or self.error_code is not None:
                raise ValueError("human waits cannot grant execution or report a service failure")
            if self.wait_reason is None:
                raise ValueError("human waits require a precise wait reason")
            if self.dispatch_plan is not None:
                raise ValueError("human waits cannot grant a dispatch plan")
            if self.ticket_lane_capabilities:
                raise ValueError("human waits cannot grant ticket-lane capabilities")
            if self.pending_dispatch is not None and self.ticket_proposal is None:
                raise ValueError("pending dispatch state requires its opened ticket proposal")
            if (
                self.pending_dispatch is not None
                and self.ticket_proposal is not None
                and (
                    self.pending_dispatch.ticket_reference != self.ticket_proposal.ticket_reference
                    or self.pending_dispatch.proposal_revision != self.ticket_proposal.proposal_revision
                    or self.pending_dispatch.dispatch_question_id != self.ticket_proposal.dispatch_question_id
                    or self.pending_dispatch.implementation_owner_id
                    != self.ticket_proposal.implementation_owner_id
                )
            ):
                raise ValueError("pending dispatch state must match its opened ticket proposal")
        else:
            if self.allowed_action_labels or self.context_budget is not None:
                raise ValueError("halted responses cannot grant capabilities or Context")
            if self.action_label is not None:
                raise ValueError("halted responses cannot invent a next action")
            if self.error_code is None:
                raise ValueError("halted responses require a stable error code")
            if self.wait_reason is not None:
                raise ValueError("halted responses cannot carry a human wait reason")
            if self.dispatch_plan is not None:
                raise ValueError("halted responses cannot grant a dispatch plan")
            if self.ticket_lane_capabilities:
                raise ValueError("halted responses cannot grant ticket-lane capabilities")
            if self.ticket_proposal is not None:
                raise ValueError("halted responses cannot carry an opened proposal")
            if self.pending_dispatch is not None:
                raise ValueError("halted responses cannot carry pending dispatch state")
        return self


class EntitlementGrant(RouterModel):
    """A test-only typed entitlement record; it holds no account secret or payment detail."""

    account_subject_id: OpaqueAccountSubjectId
    opaque_project_id: ProjectId
    permitted_modes: tuple[EntitlementMode, ...]

    @model_validator(mode="after")
    def grant_has_at_least_one_mode(self) -> EntitlementGrant:
        """Reject an ambiguous empty grant."""

        if not self.permitted_modes:
            raise ValueError("permitted_modes must not be empty")
        return self


class EntitlementPort(Protocol):
    """Private entitlement boundary; a future service replaces this fake implementation."""

    def permits(self, *, request: RouterRequestEnvelope) -> bool:
        """Return whether the metadata-only request is entitled to use the product path."""


class FakeEntitlementProvider:
    """In-memory POC entitlement provider with exact opaque identity comparison."""

    def __init__(self, *, grants: tuple[EntitlementGrant, ...]) -> None:
        self._grants = grants

    def permits(self, *, request: RouterRequestEnvelope) -> bool:
        """Permit only an exact account, project, and declared mode match."""

        if request.entitlement_mode is EntitlementMode.DENIED:
            return False
        return any(
            grant.account_subject_id == request.account_subject_id
            and grant.opaque_project_id == request.opaque_project_id
            and request.entitlement_mode in grant.permitted_modes
            for grant in self._grants
        )


class RouterServicePort(Protocol):
    """The only client-facing private Router boundary in this POC."""

    def decide(self, request: RouterRequestEnvelope) -> object:
        """Return a serialized response shape from the private decision service."""


class FakePrivateRouterService:
    """Test-only service stand-in that keeps the Profile evaluation behind a port."""

    def __init__(
        self,
        *,
        profile: ProjectWorkflowProfile,
        entitlement_provider: EntitlementPort,
        context_budget: PositiveTokenBudget = 1_000,
        approved_dispatch_artifact_registry: ApprovedDispatchArtifactRegistry | None = None,
    ) -> None:
        self._profile = profile
        self._entitlement_provider = entitlement_provider
        self._context_budget = context_budget
        self._approved_dispatch_artifact_registry = (
            approved_dispatch_artifact_registry or StaticApprovedDispatchArtifactRegistry(records=())
        )
        self._captured_requests: list[RouterRequestEnvelope] = []
        self._pending_dispatches: dict[tuple[str, str, str], PendingDispatchDescriptor] = {}
        self._pending_dispatches_by_ticket: dict[
            tuple[str, str, str], PendingDispatchDescriptor
        ] = {}
        self.request_count = 0

    def decide(self, request: RouterRequestEnvelope) -> RouterResponseEnvelope:
        """Evaluate only strictly validated metadata and return a typed public projection."""

        self.request_count += 1
        self._captured_requests.append(request)
        decision_id = self._decision_id(request=request)
        if not self._entitlement_provider.permits(request=request):
            return self._halted_response(
                request_id=request.request_id,
                decision_id=decision_id,
                outcome=RouterOutcome.SUSPEND,
                error_code=RouterServiceErrorCode.ROUTER_ENTITLEMENT_DENIED,
            )
        if (
            request.implementation_return is not None
            and request.implementation_return.status is ImplementationReturnStatus.BLOCKED
        ):
            return self._halted_response(
                request_id=request.request_id,
                decision_id=decision_id,
                outcome=RouterOutcome.SUSPEND,
                error_code=RouterServiceErrorCode.ROUTER_POLICY_BLOCKED,
            )
        pending_dispatch = self._pending_dispatch_for(request=request)
        decision = RouterEngine(
            approved_dispatch_artifact_registry=self._approved_dispatch_artifact_registry,
        ).decide(
            state=RouterState(
                project_id=request.opaque_project_id,
                stage=request.workflow_stage,
                authority_state=request.authority_state,
                delivery_stage=request.delivery_stage,
                artifact_refs=self._private_artifact_refs(request=request),
                topology=request.topology,
                collaboration_plan=request.collaboration_plan,
                pending_dispatch=pending_dispatch,
            ),
            event=RouterEvent(
                event_id=request.event_correlation_id,
                kind=request.router_event_kind,
                completion_evidence=request.completion_evidence,
                implementation_return=request.implementation_return,
                implementation_handoff=request.implementation_handoff,
                dispatch_confirmation=request.dispatch_confirmation,
                dispatch_receipt=request.dispatch_receipt,
                ticket_proposal=request.ticket_proposal,
            ),
            profile=self._profile,
        )
        if decision.continuation is ContinuationDirective.AUTO_CONTINUE:
            if request.router_event_kind is RouterEventKind.IMPLEMENTATION_DISPATCH_CONFIRMED:
                self._consume_pending_dispatch(request=request)
            assert decision.next_stage is not None
            action_label = self._action_for(stage=decision.next_stage)
            return RouterResponseEnvelope(
                request_id=request.request_id,
                decision_id=decision_id,
                outcome=decision.outcome,
                continuation=decision.continuation,
                next_stage=decision.next_stage,
                action_label=action_label,
                allowed_action_labels=(action_label,),
                required_source_kinds=tuple(source.kind for source in decision.required_sources),
                context_budget=self._context_budget,
                wait_reason=None,
                dispatch_plan=decision.dispatch_plan,
                ticket_lane_capabilities=decision.ticket_lane_capabilities,
                pending_dispatch=None,
            )
        if decision.continuation is ContinuationDirective.WAIT_FOR_HUMAN:
            if decision.pending_dispatch is not None:
                self._store_pending_dispatch(
                    request=request,
                    pending_dispatch=decision.pending_dispatch,
                )
            return RouterResponseEnvelope(
                request_id=request.request_id,
                decision_id=decision_id,
                outcome=RouterOutcome.SUSPEND,
                continuation=ContinuationDirective.WAIT_FOR_HUMAN,
                next_stage=None,
                action_label=ProductActionLabel.REQUEST_APPROVAL,
                allowed_action_labels=(),
                required_source_kinds=(),
                context_budget=None,
                wait_reason=decision.wait_reason,
                ticket_proposal=decision.ticket_proposal,
                pending_dispatch=decision.pending_dispatch,
            )
        if (
            request.router_event_kind is RouterEventKind.IMPLEMENTATION_DISPATCH_CONFIRMED
            and not self._dispatch_confirmation_retry_permitted(request=request)
        ):
            self._discard_pending_dispatch(request=request)
        return self._halted_response(
            request_id=request.request_id,
            decision_id=decision_id,
            outcome=decision.outcome,
            error_code=RouterServiceErrorCode.ROUTER_POLICY_BLOCKED,
        )

    def _pending_dispatch_for(
        self,
        *,
        request: RouterRequestEnvelope,
    ) -> PendingDispatchDescriptor | None:
        """Load pending dispatch only from the Router-owned metadata store."""

        if request.router_event_kind is RouterEventKind.TICKET_DISPATCH_REQUIRED:
            ticket_reference = self._ticket_reference_for_request(request=request)
            if ticket_reference is not None:
                pending_by_ticket = self._pending_dispatches_by_ticket.get(
                    self._pending_ticket_key(
                        request=request,
                        ticket_reference=ticket_reference,
                    )
                )
                if pending_by_ticket is not None:
                    return pending_by_ticket
            correlation_id = request.event_correlation_id
        elif (
            request.router_event_kind is RouterEventKind.IMPLEMENTATION_DISPATCH_CONFIRMED
            and request.dispatch_receipt is not None
        ):
            correlation_id = request.dispatch_receipt.correlation_id
        else:
            return None
        return self._pending_dispatches.get(
            self._pending_key(request=request, correlation_id=correlation_id)
        )

    def _store_pending_dispatch(
        self,
        *,
        request: RouterRequestEnvelope,
        pending_dispatch: PendingDispatchDescriptor,
    ) -> None:
        """Index one live pending question by both its correlation and ticket identity."""

        self._pending_dispatches[
            self._pending_key(
                request=request,
                correlation_id=pending_dispatch.event_correlation_id,
            )
        ] = pending_dispatch
        self._pending_dispatches_by_ticket[
            self._pending_ticket_key(
                request=request,
                ticket_reference=pending_dispatch.ticket_reference,
            )
        ] = pending_dispatch

    def _consume_pending_dispatch(self, *, request: RouterRequestEnvelope) -> None:
        """Consume the accepted confirmation exactly once."""

        if request.dispatch_receipt is None:
            return
        pending_dispatch = self._pending_dispatches.pop(
            self._pending_key(
                request=request,
                correlation_id=request.dispatch_receipt.correlation_id,
            ),
            None,
        )
        if pending_dispatch is not None:
            ticket_key = self._pending_ticket_key(
                request=request,
                ticket_reference=pending_dispatch.ticket_reference,
            )
            if self._pending_dispatches_by_ticket.get(ticket_key) == pending_dispatch:
                self._pending_dispatches_by_ticket.pop(ticket_key, None)

    def _discard_pending_dispatch(self, *, request: RouterRequestEnvelope) -> None:
        """Fail closed by clearing a failed confirmation when the Profile permits no retry."""

        pending_dispatch: PendingDispatchDescriptor | None = None
        if request.dispatch_receipt is not None:
            pending_dispatch = self._pending_dispatches.get(
                self._pending_key(
                    request=request,
                    correlation_id=request.dispatch_receipt.correlation_id,
                )
            )
            if pending_dispatch is None:
                pending_dispatch = self._pending_dispatches_by_ticket.get(
                    self._pending_ticket_key(
                        request=request,
                        ticket_reference=request.dispatch_receipt.ticket_reference,
                    )
                )
        if pending_dispatch is None:
            ticket_reference = self._ticket_reference_for_request(request=request)
            if ticket_reference is not None:
                pending_dispatch = self._pending_dispatches_by_ticket.get(
                    self._pending_ticket_key(
                        request=request,
                        ticket_reference=ticket_reference,
                    )
                )
        if pending_dispatch is None:
            return
        self._pending_dispatches.pop(
            self._pending_key(
                request=request,
                correlation_id=pending_dispatch.event_correlation_id,
            ),
            None,
        )
        ticket_key = self._pending_ticket_key(
            request=request,
            ticket_reference=pending_dispatch.ticket_reference,
        )
        if self._pending_dispatches_by_ticket.get(ticket_key) == pending_dispatch:
            self._pending_dispatches_by_ticket.pop(ticket_key, None)

    def _dispatch_confirmation_retry_permitted(
        self,
        *,
        request: RouterRequestEnvelope,
    ) -> bool:
        """Derive retry permission from the Profile instead of assuming failed receipt retries."""

        rule = self._profile.rule_for(
            current_stage=request.workflow_stage,
            event_kind=request.router_event_kind,
        )
        return rule is not None and rule.outcome is RouterOutcome.RETRY

    @staticmethod
    def _ticket_reference_for_request(
        *,
        request: RouterRequestEnvelope,
    ) -> str | None:
        """Resolve the ticket identity without accepting pending state from the caller."""

        if request.ticket_reference is not None:
            return request.ticket_reference
        if request.ticket_proposal is not None:
            return request.ticket_proposal.ticket_reference
        return None

    @staticmethod
    def _pending_key(
        *,
        request: RouterRequestEnvelope,
        correlation_id: str,
    ) -> tuple[str, str, str]:
        """Scope one pending dispatch to its private account, project and correlation."""

        return (request.account_subject_id, request.opaque_project_id, correlation_id)

    @staticmethod
    def _pending_ticket_key(
        *,
        request: RouterRequestEnvelope,
        ticket_reference: str,
    ) -> tuple[str, str, str]:
        """Scope the live-question invariant to one private account, project and ticket."""

        return (request.account_subject_id, request.opaque_project_id, ticket_reference)

    def captured_requests_json(self) -> str:
        """Expose POC test evidence only; it serializes no local source or ContextPacket."""

        return "\n".join(request.model_dump_json() for request in self._captured_requests)

    def _private_artifact_refs(self, *, request: RouterRequestEnvelope) -> tuple[ArtifactRef, ...]:
        """Convert source-kind availability to private synthetic refs without receiving locators."""

        return tuple(
            ArtifactRef(
                kind=kind,
                identifier=(
                    request.ticket_reference
                    if kind is ArtifactKind.TICKET and request.ticket_reference is not None
                    else f"available-{kind.value}"
                ),
                uri=f"private://availability/{kind.value}",
                revision="metadata-only",
            )
            for kind in request.available_source_kinds
        )

    def _decision_id(self, *, request: RouterRequestEnvelope) -> OpaqueDecisionId:
        """Make retries stable while ensuring a different event yields a different opaque ID."""

        seed = "\x1f".join(
            (
                request.account_subject_id,
                request.opaque_project_id,
                request.event_correlation_id,
                self._profile.profile_id,
                self._profile.profile_version,
            )
        )
        return f"dec_{uuid5(NAMESPACE_URL, seed).hex}"

    @staticmethod
    def _halted_response(
        *,
        request_id: OpaqueRequestId,
        decision_id: OpaqueDecisionId,
        outcome: RouterOutcome,
        error_code: RouterServiceErrorCode,
    ) -> RouterResponseEnvelope:
        """Create the one non-grant response shape."""

        return RouterResponseEnvelope(
            request_id=request_id,
            decision_id=decision_id,
            outcome=outcome,
            continuation=ContinuationDirective.HALT,
            next_stage=ProcessStage.STOPPED if outcome is RouterOutcome.STOP else None,
            action_label=None,
            allowed_action_labels=(),
            required_source_kinds=(),
            context_budget=None,
            error_code=error_code,
            wait_reason=None,
        )

    @staticmethod
    def _action_for(*, stage: ProcessStage) -> ProductActionLabel:
        """Map internal stage output to the closed product-language action surface."""

        labels = {
            ProcessStage.WAYFINDER: ProductActionLabel.DEFINE_STARTING_POINT,
            ProcessStage.ARCHITECTURE: ProductActionLabel.SHAPE_SOLUTION,
            ProcessStage.GRILL: ProductActionLabel.CONFIRM_ASSUMPTIONS,
            ProcessStage.CONTEXT: ProductActionLabel.ORGANIZE_WORKSPACE,
            ProcessStage.SPEC: ProductActionLabel.DRAFT_DELIVERY_PLAN,
            ProcessStage.TICKETS: ProductActionLabel.PLAN_EXECUTION,
            ProcessStage.IMPLEMENT: ProductActionLabel.BUILD_AND_TEST,
            ProcessStage.SMOKE_TEST: ProductActionLabel.VERIFY_DELIVERY,
            ProcessStage.REVIEW: ProductActionLabel.VERIFY_DELIVERY,
            ProcessStage.HANDOFF: ProductActionLabel.COMPLETE_HANDOFF,
        }
        try:
            return labels[stage]
        except KeyError as error:
            raise ValueError("no product action is declared for the requested transition") from error


class LocalMetadataNormalizer:
    """Validate untrusted local boundary data before any transport is called."""

    @staticmethod
    def normalize(*, raw_request: Mapping[str, object]) -> RouterRequestEnvelope:
        """Normalize a closed metadata mapping or raise a validation-only failure."""

        try:
            return RouterRequestEnvelope.model_validate(raw_request)
        except ValidationError as error:
            raise ValueError("private Router request is invalid") from error


class ContinuationPlan(RouterModel):
    """The single local command surface; an Agent never decides Context access itself."""

    mode: ContinuationMode
    action_label: ProductActionLabel | None
    required_source_kinds: tuple[ArtifactKind, ...]
    context_budget: PositiveTokenBudget | None
    error_code: RouterServiceErrorCode | None
    response: RouterResponseEnvelope | None = None
    wait_reason: HumanWaitReason | None = None
    dispatch_plan: CollaborationDispatchPlan | None = None
    ticket_lane_capabilities: tuple[CapabilityRef, ...] = ()
    ticket_proposal: TicketProposal | None = None
    pending_dispatch: PendingDispatchDescriptor | None = None

    @model_validator(mode="after")
    def plan_shape_is_safe(self) -> ContinuationPlan:
        """Make an accidental action or Context grant impossible after a stop or wait."""

        if self.mode is ContinuationMode.AUTO_RUN:
            if self.action_label is None or self.context_budget is None or self.response is None:
                raise ValueError("automatic plans require a validated Router response and Context budget")
            if self.error_code is not None:
                raise ValueError("automatic plans cannot have an error")
            if self.wait_reason is not None:
                raise ValueError("automatic plans cannot have a wait reason")
            if self.dispatch_plan != self.response.dispatch_plan:
                raise ValueError("automatic plans must preserve the validated dispatch plan")
            if self.ticket_lane_capabilities != self.response.ticket_lane_capabilities:
                raise ValueError("automatic plans must preserve ticket-lane capabilities")
            if self.ticket_proposal is not None:
                raise ValueError("automatic plans cannot carry an open proposal")
            if self.pending_dispatch is not None:
                raise ValueError("automatic plans cannot carry pending dispatch state")
        elif self.mode is ContinuationMode.WAIT_FOR_HUMAN:
            if self.action_label is not ProductActionLabel.REQUEST_APPROVAL:
                raise ValueError("human waits require the approval action")
            if self.required_source_kinds or self.context_budget is not None or self.error_code is not None:
                raise ValueError("human waits cannot grant Context or report a transport error")
            if self.response is None or self.wait_reason is None:
                raise ValueError("human waits require a validated response and precise reason")
            if self.dispatch_plan is not None:
                raise ValueError("human waits cannot grant a dispatch plan")
            if self.ticket_lane_capabilities:
                raise ValueError("human waits cannot grant ticket-lane capabilities")
            if self.pending_dispatch is not None and self.ticket_proposal is None:
                raise ValueError("pending dispatch state requires its opened ticket proposal")
            if (
                self.pending_dispatch is not None
                and self.ticket_proposal is not None
                and (
                    self.pending_dispatch.ticket_reference != self.ticket_proposal.ticket_reference
                    or self.pending_dispatch.proposal_revision != self.ticket_proposal.proposal_revision
                    or self.pending_dispatch.dispatch_question_id != self.ticket_proposal.dispatch_question_id
                    or self.pending_dispatch.implementation_owner_id
                    != self.ticket_proposal.implementation_owner_id
                )
            ):
                raise ValueError("pending dispatch state must match its opened ticket proposal")
            if self.pending_dispatch != self.response.pending_dispatch:
                raise ValueError("human waits must preserve pending dispatch state")
        elif (
            self.action_label is not None
            or self.required_source_kinds
            or self.context_budget is not None
            or self.wait_reason is not None
            or self.dispatch_plan is not None
            or self.ticket_lane_capabilities
            or self.ticket_proposal is not None
            or self.pending_dispatch is not None
        ):
            raise ValueError("halted plans cannot grant a local action, Context, or wait reason")
        return self


class PrivateRouterClient:
    """Fail-closed local adapter for the private service boundary and replay checks."""

    def __init__(
        self,
        *,
        service: RouterServicePort,
        approved_dispatch_artifact_registry: ApprovedDispatchArtifactRegistry | None = None,
    ) -> None:
        self._service = service
        self._approved_dispatch_artifact_registry = (
            approved_dispatch_artifact_registry or StaticApprovedDispatchArtifactRegistry(records=())
        )
        self._decision_for_event: dict[str, str] = {}
        self._event_for_decision: dict[str, str] = {}
        self._request_for_event: dict[str, str] = {}
        self._pending_dispatch_plans: dict[str, ContinuationPlan] = {}

    def route(self, *, raw_request: Mapping[str, object]) -> ContinuationPlan:
        """Return one validated plan; every boundary error becomes an explicit halt."""

        try:
            request = LocalMetadataNormalizer.normalize(raw_request=raw_request)
        except (TypeError, ValueError):
            return self._halt(code=RouterServiceErrorCode.ROUTER_INPUT_INVALID)
        if request.router_event_kind is RouterEventKind.TICKET_DISPATCH_REQUIRED:
            handoff = request.implementation_handoff
            proposal = request.ticket_proposal
            if (
                proposal is None
                or handoff is None
                or handoff.ticket_reference != proposal.ticket_reference
                or handoff.implementation_owner_id != proposal.implementation_owner_id
                or resolve_approved_dispatch_artifact(
                    self._approved_dispatch_artifact_registry,
                    project_id=request.opaque_project_id,
                    ticket_reference=proposal.ticket_reference,
                    handoff_reference=handoff.handoff_reference,
                    implementation_owner_id=proposal.implementation_owner_id,
                    ticket_docs_commit=handoff.ticket_docs_commit,
                    handoff_docs_commit=handoff.handoff_docs_commit,
                )
                is None
            ):
                return self._halt(code=RouterServiceErrorCode.ROUTER_POLICY_BLOCKED)
        if request.dispatch_receipt is not None:
            # A confirmation attempt closes the local rendering capability even if
            # the service later rejects the receipt.  This makes the response one-shot.
            self._pending_dispatch_plans.pop(request.dispatch_receipt.correlation_id, None)
        try:
            raw_response = self._service.decide(request)
        except Exception:
            return self._halt(code=RouterServiceErrorCode.ROUTER_SERVICE_UNAVAILABLE)
        try:
            response = RouterResponseEnvelope.model_validate(raw_response)
        except ValidationError:
            return self._halt(code=RouterServiceErrorCode.ROUTER_RESPONSE_INVALID)
        if response.request_id != request.request_id or not self._accept_correlation(
            event_id=request.event_correlation_id,
            request_id=request.request_id,
            decision_id=response.decision_id,
        ):
            return self._halt(code=RouterServiceErrorCode.ROUTER_RESPONSE_INVALID)
        if response.continuation is ContinuationDirective.AUTO_CONTINUE:
            return ContinuationPlan(
                mode=ContinuationMode.AUTO_RUN,
                action_label=response.action_label,
                required_source_kinds=response.required_source_kinds,
                context_budget=response.context_budget,
                error_code=None,
                response=response,
                wait_reason=None,
                dispatch_plan=response.dispatch_plan,
                ticket_lane_capabilities=response.ticket_lane_capabilities,
                ticket_proposal=None,
            )
        if response.continuation is ContinuationDirective.WAIT_FOR_HUMAN:
            plan = ContinuationPlan(
                mode=ContinuationMode.WAIT_FOR_HUMAN,
                action_label=ProductActionLabel.REQUEST_APPROVAL,
                required_source_kinds=(),
                context_budget=None,
                error_code=None,
                response=response,
                wait_reason=response.wait_reason,
                dispatch_plan=None,
                ticket_lane_capabilities=(),
                ticket_proposal=response.ticket_proposal,
                pending_dispatch=response.pending_dispatch,
            )
            if plan.pending_dispatch is not None:
                self._pending_dispatch_plans[plan.pending_dispatch.event_correlation_id] = plan
            return plan
        return self._halt(code=response.error_code or RouterServiceErrorCode.ROUTER_RESPONSE_INVALID)

    def owns_pending_dispatch_plan(self, plan: object) -> bool:
        """Prove object-identity ownership of a live pending dispatch plan."""

        if not isinstance(plan, ContinuationPlan) or plan.pending_dispatch is None:
            return False
        return (
            self._pending_dispatch_plans.get(plan.pending_dispatch.event_correlation_id)
            is plan
        )

    def render_dispatch_response(
        self,
        *,
        plan: ContinuationPlan,
        artifacts: CommittedDispatchArtifacts | None = None,
        formatter: DispatchResponseFormatter | None = None,
    ) -> RenderedDispatchResponse:
        """Render from Router state; optional artifacts are equality assertions only."""
        if not self.owns_pending_dispatch_plan(plan):
            return RenderedDispatchResponse(
                outcome=RenderOutcome.HALT,
                error=RenderError.UNTRUSTED_RESPONSE,
            )
        try:
            pending = plan.pending_dispatch
            proposal = plan.ticket_proposal
            response = plan.response
            if artifacts is not None and (
                pending is None
                or pending.ticket_docs_commit is None
                or pending.handoff_docs_commit is None
                or artifacts.ticket_docs_commit != pending.ticket_docs_commit
                or artifacts.ticket_reference != pending.ticket_reference
                or artifacts.handoff_docs_commit != pending.handoff_docs_commit
                or artifacts.handoff_reference != pending.reviewed_handoff_reference
            ):
                return RenderedDispatchResponse(
                    outcome=RenderOutcome.HALT,
                    error=RenderError.ARTIFACT_MISMATCH,
                )
            if (
                plan.mode is not ContinuationMode.WAIT_FOR_HUMAN
                or pending is None
                or proposal is None
                or response is None
                or pending.ticket_docs_commit is None
                or pending.handoff_docs_commit is None
                or response.pending_dispatch != pending
                or proposal.ticket_reference != pending.ticket_reference
            ):
                return RenderedDispatchResponse(
                    outcome=RenderOutcome.HALT,
                    error=RenderError.INVALID_RESPONSE,
                )
            candidate = FixedDispatchResponse(
                pending_dispatch=pending,
                ticket_docs_commit=pending.ticket_docs_commit,
                ticket_reference=pending.ticket_reference,
                handoff_docs_commit=pending.handoff_docs_commit,
                handoff_reference=pending.reviewed_handoff_reference,
                implementation_owner_id=pending.implementation_owner_id,
            )
            deterministic = DispatchResponseFormatter()
            expected = deterministic.format(candidate)
            selected = formatter or deterministic
            rendered = selected.format(candidate)
            if rendered != expected:
                return RenderedDispatchResponse(
                    outcome=RenderOutcome.HALT,
                    error=RenderError.FORMATTER_OUTPUT_INVALID,
                )
            return RenderedDispatchResponse(outcome=RenderOutcome.RENDERED, text=rendered)
        except Exception:
            return RenderedDispatchResponse(
                outcome=RenderOutcome.HALT,
                error=RenderError.FORMATTER_FAILURE,
            )

    def _accept_correlation(
        self,
        *,
        event_id: OpaqueEventId,
        request_id: OpaqueRequestId,
        decision_id: OpaqueDecisionId,
    ) -> bool:
        """Use exact opaque IDs: retries stay stable and cross-event replay is rejected."""

        known_decision = self._decision_for_event.get(event_id)
        known_event = self._event_for_decision.get(decision_id)
        known_request = self._request_for_event.get(event_id)
        if known_decision is not None and known_decision != decision_id:
            return False
        if known_event is not None and known_event != event_id:
            return False
        if known_request is not None and known_request != request_id:
            return False
        self._decision_for_event[event_id] = decision_id
        self._event_for_decision[decision_id] = event_id
        self._request_for_event[event_id] = request_id
        return True

    @staticmethod
    def _halt(*, code: RouterServiceErrorCode) -> ContinuationPlan:
        """Create the only local error result; never invent a next action or Context grant."""

        return ContinuationPlan(
            mode=ContinuationMode.HALT,
            action_label=None,
            required_source_kinds=(),
            context_budget=None,
            error_code=code,
            wait_reason=None,
            dispatch_plan=None,
            ticket_lane_capabilities=(),
            ticket_proposal=None,
            pending_dispatch=None,
        )


class LocalContextGate:
    """Permit local Context resolution only for a currently validated automatic plan."""

    def resolve(
        self,
        *,
        plan: ContinuationPlan,
        resolver: ContextResolver,
        event_id: NonBlankText,
        required_sources: tuple[ArtifactRef, ...],
        target_artifact: ArtifactRef,
        consumer: ConsumerFingerprint,
    ) -> ResolvedContext:
        """Enforce decision source kinds and budget before the resolver reads local text."""

        if plan.mode is not ContinuationMode.AUTO_RUN or plan.context_budget is None:
            raise PermissionError("private Router did not grant local Context access")
        actual_kinds = tuple(source.kind for source in required_sources)
        if actual_kinds != plan.required_source_kinds:
            raise PermissionError("local sources do not exactly match the Router Context grant")
        return resolver.resolve(
            event_id=event_id,
            required_sources=required_sources,
            target_artifact=target_artifact,
            consumer=consumer,
            token_budget=plan.context_budget,
        )


class AutomaticContinuationExecutor(Protocol):
    """Local capability runner port.  Production model dispatch remains outside this POC."""

    def execute(self, *, action_label: ProductActionLabel) -> RouterRequestEnvelope:
        """Run the granted local action and return its next metadata-only event request."""


class ContinuityRunResult(RouterModel):
    """A bounded run stops only at a human gate, a failure, or its declared safety ceiling."""

    auto_steps: Annotated[int, Field(ge=0)]
    final_plan: ContinuationPlan


class AutomaticContinuationRunner:
    """Execute consecutive safe product actions without pausing between non-human stages."""

    def __init__(self, *, client: PrivateRouterClient, executor: AutomaticContinuationExecutor) -> None:
        self._client = client
        self._executor = executor

    def run_until_pause(
        self,
        *,
        initial_request: RouterRequestEnvelope,
        max_auto_steps: Annotated[int, Field(gt=0)],
    ) -> ContinuityRunResult:
        """Continue while exactly one valid action is granted; fail closed at the safety ceiling."""

        if max_auto_steps <= 0:
            raise ValueError("max_auto_steps must be greater than zero")
        request = initial_request
        auto_steps = 0
        while True:
            plan = self._client.route(raw_request=request.model_dump())
            if plan.mode is not ContinuationMode.AUTO_RUN:
                return ContinuityRunResult(auto_steps=auto_steps, final_plan=plan)
            if auto_steps >= max_auto_steps or plan.action_label is None:
                return ContinuityRunResult(
                    auto_steps=auto_steps,
                    final_plan=PrivateRouterClient._halt(
                        code=RouterServiceErrorCode.ROUTER_POLICY_BLOCKED
                    ),
                )
            try:
                raw_next_request = self._executor.execute(action_label=plan.action_label)
                request = RouterRequestEnvelope.model_validate(raw_next_request)
            except Exception:
                return ContinuityRunResult(
                    auto_steps=auto_steps,
                    final_plan=PrivateRouterClient._halt(
                        code=RouterServiceErrorCode.ROUTER_POLICY_BLOCKED
                    ),
                )
            auto_steps += 1
