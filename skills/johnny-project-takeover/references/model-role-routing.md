# Model role lifecycle and escalation

Read this reference when assigning a model capability to a workflow role, deciding whether the
architecture owner may sleep, or routing work back from the supervisor or implementer. Model
selection never grants authority.

## Semantic roles

```text
ModelRole = ARCHITECTURE_OWNER | SUPERVISOR_REVIEWER
          | IMPLEMENTATION_OWNER | RESEARCH_HELPER

RoleActivityState = ACTIVE | SLEEPING | WAKE_REQUIRED

SpecificationReadinessDecision = READY_FOR_SUPERVISION
                               | ARCHITECTURE_OWNER_REQUIRED
                               | OWNER_APPROVAL_REQUIRED
```

- The human owner and `ARCHITECTURE_OWNER` converge intake, Wayfinder, architecture, Grill and
  the formal SPEC, and owns creation/change-control revision of shared project Context. The
  architecture owner does not implement or review its own production work.
- `SUPERVISOR_REVIEWER` owns approved-SPEC ticket decomposition, schema/type preflight,
  dispatch, monitoring, independent review, correction routing and guarded integration.
- `IMPLEMENTATION_OWNER` receives one admitted ticket, implements it and returns only the
  ticket's typed result. It cannot alter the SPEC, architecture, public contract or AC.
- `RESEARCH_HELPER` is optional, reviewer-owned, read-only and no-code as defined by
  `delivery-profile.md`.

The versioned `ProjectWorkflowProfile` records opaque model references and capability evidence
for these roles. The current default host mapping is a highest-capability architecture owner,
Terra supervisor/reviewer and Luna implementation owner. Exact provider/model names belong to
the Profile rather than global workflow prose so a host mapping can change without changing
authority or policy.

## SPEC readiness and sleep

The architecture owner may enter `SLEEPING` only after all of the following are true:

1. the human owner approved one exact SPEC revision;
2. every public contract, finite state, error meaning, ownership boundary, dependency direction,
   external effect, rollback/forward-fix rule and acceptance criterion is closed;
3. the SPEC contains no unresolved design decision delegated to a ticket or implementer;
4. applicable security, XSS, delivery-profile and UI-design-source classifications are closed;
5. the supervisor capability is available and bound to the same project/Profile revision.

Success returns `READY_FOR_SUPERVISION` and records the exact SPEC/Profile refs. Missing owner
approval returns `OWNER_APPROVAL_REQUIRED`. Any other open design question returns
`ARCHITECTURE_OWNER_REQUIRED`; the Router must not let the supervisor infer the answer.

## Supervisor boundary

The supervisor behaves as a compiler over the approved SPEC. It may normalize identifiers,
split closed behavior into tickets and repair a ticket omission only when the exact meaning is
already present in the approved SPEC. It may not create new product behavior, choose among
unresolved architecture alternatives, weaken an AC or reinterpret a public failure.

The supervisor has no shared-Context write capability. Ticket planning, dispatch, monitoring,
correction and review may bind only the exact sealed Context revision and bounded source spans.
Any needed shared fact that is absent or changed is an architecture-owner wake condition, not a
reason to append Context from the ticket lane.

The supervisor routes implementation/test/evidence defects through same-ticket correction.
Model capability failure is not inferred from one defect. Only after the allowed initial review
and one bounded correction review both fail against the same complete Closure revision may the
supervisor return `MODEL_CAPABILITY_INSUFFICIENT`; this marks the architecture owner
`WAKE_REQUIRED` (delivered by an armed runner, else relayed by the owner) or requests
an owner-approved Profile change and does not grant the supervisor implementation authority.

## Mandatory wake triggers

The Router changes the architecture owner to `WAKE_REQUIRED` before further ticket/source/host
effect when any of these typed conditions is present. `WAKE_REQUIRED` is a state, not a
delivery: only a runner armed for this project turns it into an actual wake, and when none is
armed the owner must be told to relay it (SKILL.md § Automation readiness):

- `SPEC_AMBIGUOUS` or `SPEC_CONTRADICTORY`;
- `PUBLIC_CONTRACT_UNDEFINED` or an unprovable acceptance criterion;
- `ARCHITECTURE_CONFLICT` or a cross-ticket design conflict;
- `REQUIREMENT_CHANGED` or a new external/privileged boundary;
- a newly applicable `HIGH_ASSURANCE` trigger;
- `MODEL_CAPABILITY_INSUFFICIENT` after bounded convergence is exhausted.

The implementation owner reports such a conflict as `CHANGE_DETECTED` or `BLOCKED`; it never
wakes or controls another Agent directly. The supervisor emits the typed wake request through
the Router. The human owner retains approval for requirements, SPEC, maturity changes,
irreversible effects, push, release and deployment.
