# Router control contract

Read this reference when resolving a workflow event, emitting a decision, validating a
completion return, or admitting an implementation dispatch. Do not load it merely to
implement an already admitted ticket.

## Closed state machine

```text
ProcessStage = INTAKE | WAYFINDER | ARCHITECTURE | GRILL | CONTEXT | SPEC | TICKETS
             | IMPLEMENT | SMOKE_TEST | REVIEW | HANDOFF | BLOCKED | STOPPED

RouterEvent = INTAKE | WAYFINDER_GO | WAYFINDER_NO_GO
            | WAYFINDER_INFO_REQUIRED | OWNER_INPUT_PROVIDED
            | ACTION_COMPLETED
            | VALIDATION_PASSED | VALIDATION_FAILED
            | APPROVAL_GRANTED | APPROVAL_DENIED | REQUIREMENT_CHANGED
            | CONTEXT_REFERENCE_CLOSED | EXTERNAL_DECISION_REQUIRED
            | TICKET_DISPATCH_REQUIRED | IMPLEMENTATION_DISPATCH_CONFIRMED
```

The executable typed contracts in `library/workflow_router/` are authoritative for field
shape and validation. The policy invariants below are authoritative for routing behavior:

- `RouterState` binds one `project_id`, stage, authority state, delivery stage, artifact
  references and at most one live pending dispatch descriptor.
- `RouterDecision` returns one outcome, one continuation, one optional next stage, the
  minimum required source references, one optional `ContextView`, eligible capabilities
  and typed blockers.
- `CompletionEvidence` is attached to `ACTION_COMPLETED`; a commit digest is evidence, not
  permission to select a next stage.
- `ImplementationHandoff` contains approved artifact and role references only.
- `ImplementationReturn` is exactly `COMPLETED`, `BLOCKED` or `CHANGE_DETECTED`.
- `CHANGE_DETECTED` emits `REQUIREMENT_CHANGED` and returns to change control. It is never
  patched silently inside an approved ticket.

## Metadata-only boundary

Serializable Router state, formatter output, telemetry and errors may contain only opaque
identifiers, revisions, spans, fingerprints, evidence references and digests. They must not
contain raw source text, `ContextPacket`, prompts, filesystem paths, URIs, secrets, PII or
exception details.

Policy documents are read only through an ephemeral source boundary. The boundary returns
typed metadata such as source ID, revision and digest; policy text does not enter durable
Router state.

## Shared-Context authority

Shared project Context supports `CREATE`, `REVISE` and `READ_REFERENCE` as distinct typed
operations. `CREATE` is admitted only for the architecture owner during `ARCHITECTURE`,
`GRILL` or `CONTEXT`. `REVISE` additionally requires an approved change reference and an exact
expected sealed revision. The `CONTEXT` completion seals the new revision before SPEC approval.

Every later stage and every supervisor/ticket/implementation/review role is limited to
`READ_REFERENCE`. The effect gate validates project, actor role, stage, operation, artifact
kind, expected revision and change authority before exposing a write capability. A forbidden
role/stage/operation is `HALT / CONTEXT_WRITE_FORBIDDEN`; a missing or mismatched sealed
revision is `HALT / CONTEXT_REVISION_STALE`. Prompt instructions and filesystem access do not
override this gate.

## Continuation

Every decision declares exactly one continuation:

1. `AUTO_CONTINUE` applies only when the declared transition, complete minimum sources,
   valid evidence, one allowlisted capability and existing authority all agree. Execute one
   action, emit a new event, then route again.
2. `WAIT_FOR_HUMAN` applies only to a Profile-declared approval, an owner decision or an
   irreversible external effect. State the exact decision required. The Wayfinder
   information-gap round (`WAYFINDER_INFO_REQUIRED`, wait reason `WAYFINDER_INPUT_GAP`)
   is such a declared owner decision: the typed `WayfinderInfoRequest` lists every
   currently blocking enumerated gap at once, never re-asks an answered field, is closed
   at two rounds, and resumes only through `OWNER_INPUT_PROVIDED` after the answers are
   committed into the intake goal record. Round exhaustion forces a terminal
   `WAYFINDER_GO` with explicit assumptions or `WAYFINDER_NO_GO / INSUFFICIENT_INPUT`.
3. `HALT` applies to missing or invalid sources, denied or absent authority, unavailable
   capability, failed validation, replay or mismatch, unsafe external boundary, exceeded
   budget, undeclared transition or `NO-GO`. Do not guess, use a local fallback, or wait
   indefinitely.

Automatic continuation has a bounded step/time ceiling. Reaching it is `HALT`.

## Dispatch admission

Dispatch admission has two lifetime-scoped paths. A same-lifetime synchronous reviewer-owned
lane is direct: the reviewer dispatches, waits, receives, reviews and integrates. It does not
consume a receipt or require a runner, queue, live descriptor, host gateway or host workspace
readback, and an unavailable bridge must not halt that lane. The reviewer directly allocates the
repository-contained owner worktree and binds it to the exact ticket, branch and baseline.
The synchronous path must not invent a receipt issuer, durable queue or runner.

The receipt-bound bridge remains mandatory for a cross-lifetime handoff. In that path, the Private
Router owns the live `PendingDispatchDescriptor`, and a typed `ApprovedDispatchArtifactRegistry`
resolves the exact project, ticket, reviewed handoff, ticket and handoff commits, implementation
owner, task/workspace binding, worktree and expected baseline.

Only `IMPLEMENTATION_DISPATCH_CONFIRMED` may consume a matching, unconsumed receipt and create a
cross-lifetime implementation lane. Missing, copied, forged, replayed or mismatched project,
ticket, handoff, owner, task, worktree, branch, baseline, action, question or correlation halts
before source, capability, receipt, branch or host effect. Caller-provided commits are assertions
to compare, never authority sources. A cross-lifetime handoff with no proved bridge is
`UNAVAILABLE`: it is an unarmed wake and must not be reported as delivered.

Wake capability has exactly three finite dispositions: `NOT_REQUIRED` when the host delivers
natively (including a same-lifetime synchronous lane), `AVAILABLE` when a cross-lifetime bridge is
present and actual delivery is proved, and `UNAVAILABLE` when that bridge is absent. These states
must not be folded together; only a person may relay an `UNAVAILABLE` completion.

`TICKETS + APPROVAL_GRANTED -> IMPLEMENT` is a retired transition and always halts. A ticket
dispatch confirmation is asked once; `ACTION_COMPLETED` must not create a second ceremonial
approval prompt.

## Authority line and topology

A project's integration source of truth is its declared authority-line contract: a credential-free
remote repository identity, a validated full branch ref, and a declared topology of
`SINGLE_BRANCH` or `HIGH_COLLABORATION`. No branch name, including `main`, has inherent
authority; a three-line `dev`/`staging`/`main` layout is a recommended default for
multi-session projects, and the names are project data, never assumptions.

Remote truth is directly observed. Admission resolves the declared ref by a fresh direct remote
readback at decision time; a local branch or a possibly stale `origin/<ref>` tracking entry is a
diagnostic, never admission or completion proof. A worktree whose document topology cannot be
derived from the observed authority commit halts as `TOPOLOGY_DRIFT_DETECTED` before any
source, Git or Agent effect — it must not be auto-merged, reset or pushed around.

Integration has two completed-looking but non-equivalent states. Gate success alone is
`LOCAL_INTEGRATED`. Only a non-force push to the declared ref followed by an exact direct remote
SHA readback is `AUTHORITY_INTEGRATED`; a missing, failed or mismatched readback is
`PUSH_UNCONFIRMED`, and no process exit code upgrades it. A topology-changing migration must
reach `AUTHORITY_INTEGRATED` before any further session or machine starts work from that
project, because every new session boots from the remote's shape, not from the machine that did
the work.

## Route table

| Stage | Minimum source kind | Capability kind | Expected return |
| --- | --- | --- | --- |
| `INTAKE` | goal and approved profile | goal normalization into one typed `NormalizedGoal` (intake mode, product kind, baseline/delta binding) | `WAYFINDER` or halt |
| `WAYFINDER` | Wayfinder standard and confirmed facts | viability decision | `WAYFINDER_GO`, `WAYFINDER_NO_GO` or `WAYFINDER_INFO_REQUIRED` |
| `ARCHITECTURE` | GO context, constraints and risks | architecture | completed artifact or blocker |
| `GRILL` | scoped requirements, architecture and change history | requirement convergence | confirmed facts or change event |
| `CONTEXT` / `SPEC` / `TICKETS` | approved scoped artifacts | specification and slicing | draft, approval wait or completion |
| SPEC readiness / model handover | exact SPEC/Profile revision | role lifecycle and wake routing | ready, owner wait or architecture-owner wake |
| low-model ticket admission | approved SPEC and exact ticket | decomposition validation | ready, split, upstream decision or high assurance |
| formal UI / design source | approved UI requirement and capability state | UI contract preparation | contract, owner wait or source halt |
| `IMPLEMENT` / `SMOKE_TEST` | exact admitted ticket and direct contracts | implementation and verification | typed implementation return |
| `REVIEW` / `HANDOFF` | closure set, diff and evidence | independent review | approval, correction route or halt |

## Fail-closed execution boundary

- LangGraph composes only validated transitions and persists descriptors, never raw packets.
- Agent/skill resolution exposes only allowlisted capability references.
- Temporal persists validated events and descriptors; nondeterministic I/O stays in an
  activity/adapter boundary.
- MCP reads only declared source references and normalizes them at the boundary.
- Missing role, owner, workspace binding, source, capability or verification halts rather
  than widening the search or context.
