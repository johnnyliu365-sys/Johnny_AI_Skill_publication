---
name: johnny-project-takeover
description: Route a new, inherited, or active software project through Johnny's Wayfinder, architecture, requirements, specification, ticket, implementation, review, handoff, POC/MVP/commercial, and staging workflow. Use when Codex must take over or resume a project, select the next governed stage, dispatch or review an implementer, minimize Agent context, or apply Johnny workflow policy without adding a runtime dependency to the target project.
---

# Johnny Project Takeover

Treat this plugin as an external control plane. It guides target-owned work but never becomes a
target project's runtime, CI, hook, import, submodule or symlink dependency.

## Start

1. Read the target project's own `AGENTS.md` and authority record.
2. Read `../../Workflow.md` only far enough to identify the current stage and its routing row.
3. Read exactly the reference named by that row, plus the minimum committed target artifacts it
   requires. Do not load unrelated references, the full library or chat history.
4. Execute one legal action, emit its typed completion event and return to the Router. Do not
   select the next stage locally.

Default delivery maturity is `POC` unless an approved target artifact proves otherwise.

## Codex same-lifetime implementation continuation

The entry command may continue implementation only after the Router has emitted
an exact ticket-bound same-lifetime `AUTO_CONTINUE → IMPLEMENT` decision. This
is a direct synchronous lane, not a new runtime or a cross-lifetime handoff.
The current-session reviewer is the owner of delegation, waiting, review and
integration; the implementation owner is the one owner named by the ticket.

Before delegating, the reviewer must bind all of the following to the exact
committed ticket: the reviewer-created repository-contained worktree, branch,
baseline, selected delivery/profile capability and the direct same-lifetime
lane. The reviewer then invokes the host-native `collaboration.spawn_agent`
operation exactly once for that ticket-bound owner. The selected model and
effort are read from the ticket/profile; this skill does not choose or spell a
provider/model literal.

After delegation, wait with `wait_agent` for the owner's completion. Do not
poll activity, status or an equivalent progress signal. On return, the
reviewer receives the typed `ImplementationReturn`, performs the declared
review and reverse-mutation gates, and only then routes the result onward.
The direct lane's bridge disposition is `NOT_REQUIRED`: it does not require or
create a receipt, runner, queue, pending descriptor, gateway or fabricated
adapter. Cross-lifetime handoffs retain their receipt-bound route.

If native delegation or the selected ticket/profile capability is missing, the
only result for this lane is `HALT / CODEX_NATIVE_DELEGATION_UNAVAILABLE`.
The reviewer must not implement the ticket as a fallback, wake another owner,
or invent a bridge.

## Reference router

All references are one level below this file and canonical for the named concern. Read each
file completely only when its condition applies.

| Condition or stage | Read |
| --- | --- |
| Any Router event, continuation, dispatch receipt or completion return | [Router control contract](references/router-control.md) |
| Intake profile, resource plan, maturity change, POC freeze or staging | [Delivery profile and lifecycle](references/delivery-profile.md) |
| Model-role assignment, SPEC readiness, architecture-owner sleep/wake or escalation | [Model role lifecycle](references/model-role-routing.md) |
| ContextView, source selection, capability selection or side-context mapping | [Minimal Context routing](references/context-routing.md) |
| Artifact index creation/traversal, leaf replacement or lifecycle movement | [Artifact tree routing](references/artifact-tree-routing.md) |
| Agent working Context, ticket switch, correction rebind or view closure | [Agent Context lifecycle](references/agent-context-lifecycle.md) |
| PRD/CHG creation, one-to-one identity, retirement or archive lookup | [Requirement lineage](references/requirement-lineage.md) |
| Reusable library catalog traversal or partition maintenance | [Module catalog routing](references/module-catalog-routing.md) |
| External capability admission, state, tier or target fit | [Capability admission](references/capability-admission.md) |
| Wayfinder, Architecture, Grill or requirement change | [Discovery and change control](references/discovery-change.md) |
| Untrusted data enters Browser/WebView/HTML/DOM/JavaScript | [XSS review](references/xss-review.md) |
| Secret, production log, Provider, webhook or external effect | [Security boundary](references/security-boundary.md) |
| SPEC, ticket, type preflight, frontend contract or dispatch envelope | [Specification and ticketing](references/specification-ticketing.md) |
| Approved-SPEC decomposition, low-model admission or convergence replan | [Ticket decomposition](references/ticket-decomposition.md) |
| Formal UI, Figma/screenshot/brief/design-system input or visual acceptance | [UI design handoff](references/ui-design-handoff.md) |
| Owner/task/worktree admission, Agent control or correction allocation | [Implementation authority](references/implementation-authority.md) |
| Admitted ticket implementation, TDD, type, smoke or completion | [Implementation TDD](references/implementation-tdd.md) |
| Admitted same-lifetime Codex native delegation and completion wait | [Codex native same-lifetime delegation](references/codex-native-same-lifetime-delegation.md) |
| Ticket TDD design or independent code review | [Independent review checks](references/review-checks.md) and `../../CodeReview.md` |
| Architecture/SPEC/ticket language decision | [Implementation language policy](references/language-policy.md) |

If an indexed reference is absent, unreadable, version-mismatched or ambiguous, halt before
mutation with `ROUTE_REFERENCE_INVALID`. Do not reconstruct the missing rule from memory.

## Closed loop

```text
INTAKE → WAYFINDER → ARCHITECTURE → GRILL → CONTEXT → SPEC → TICKETS
      → IMPLEMENT → SMOKE_TEST → REVIEW → HANDOFF
```

- `AUTO_CONTINUE`: execute the one declared next action when sources, evidence, authority and
  capability are complete; then route again.
- `WAIT_FOR_HUMAN`: pause only for a declared approval/owner decision or irreversible effect.
- `HALT`: stop on invalid source, authority, capability, verification, security boundary or
  undeclared transition. Never guess, fallback or wait indefinitely.
- `REQUIREMENT_CHANGED`: return to change control and the affected earlier stage.

An implementation or docs-only commit emits `ACTION_COMPLETED`; a commit does not itself select
the next stage. This skill cannot bypass host approval, permission or receipt enforcement.

### Automation readiness — check before narrating any automatic effect

This readiness gate applies to cross-lifetime wake and supervision protocols. The admitted
same-lifetime Codex native lane above has `NOT_REQUIRED` bridge disposition and uses the host's
`collaboration.spawn_agent`/`wait_agent` capabilities directly; it does not require a Johnny
runner, subscription or wake probe.

Every other wake, automatic continuation or supervision effect this skill describes is a **protocol**.
The mechanism that performs it is the installed Johnny runtime, armed for the specific project.
Before stating that any automatic effect will happen or has happened, verify all four:

1. the per-user runtime root exists (`%LOCALAPPDATA%\JohnnyRouter`, or `JOHNNY_ROOT` when set);
2. a subscription for this project's exact ref exists (`runner-subscriptions.json`);
3. a runner is running for it (`<runtime root>\launcher\johnny-router.ps1 runner status` reports
   `RUNNING`);
4. a wake capability is proven
   (`<runtime root>\launcher\johnny-router.ps1 wake-capability probe`).

`<runtime root>` in points 3 and 4 is the exact root resolved in point 1: `JOHNNY_ROOT` when set,
else `%LOCALAPPDATA%\JohnnyRouter`. Never invoke a bare `johnny-router` name — the launcher is not
assumed to be on PATH; always invoke the exact derived launcher path instead. An overridden
`JOHNNY_ROOT` relocates all four checks together, not point 1 alone.

If any of the four is absent, the honest statement is: *the handoff is committed; no automation
is armed for this project, so the owner must notify the reviewer.* Never report a wake you did
not observe: a committed handoff leaf is evidence of a commit, not of a delivery. Reporting an
unobserved wake manufactures a false completion narrative, which is precisely the failure this
workflow exists to prevent.

Durable Router state contains metadata only. A pending dispatch remains bound to its live
descriptor. The implementation owner returns an `ImplementationReturn`; `CHANGE_DETECTED`
emits `REQUIREMENT_CHANGED` rather than changing the ticket locally.

## Minimal implementation handoff

The implementer receives identifiers, not copied governance text: exact ticket/registry commit,
receipt, owner task, one fresh ticket-bound ContextView and at most one bounded resume state. A
different ticket closes that view and creates a new side-context identity. The exact ticket supplies scope,
contracts, TDD, verification and return format. The selected reference supplies the applicable
method. The Router and host gateway supply authority.

## Reusable modules

When reusable source is relevant, invoke `$apply-reusable-modules`, select the minimum `READY`
card and record its ID/revision/contract in approved target-owned artifacts. Any adopted behavior
must become target-owned, versioned and tested. Never link the target runtime to this plugin.

## Detach

Removing the plugin removes only its skills, workflow references and catalog access. It must not
remove or alter target source, configuration, CI, data or formal artifacts.
