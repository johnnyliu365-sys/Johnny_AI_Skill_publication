# Specification and ticketing

Read this reference in `SPEC` or `TICKETS`, during ticket schema preflight, or when creating a
minimal dispatch envelope.

## Specification

One feature cluster has one effective `modules/spec/<feature>.md`. It records:

- immutable SPEC ID, state, author/worktree and baseline commit;
- target-owned Context, PRD, CHG and shared-reference indexes;
- problem, user, success measures and out-of-scope work;
- user/data/error/boundary flows;
- domain, data, cache, API/event, UI, Provider, authorization and operational effects;
- Composition Root, public interfaces, dependency direction and responsibility boundaries;
- test seams, AC, risks, compatibility, rollback/forward-fix and deployment prerequisites;
- implementation language decision;
- XSS classification and, when applicable, the matrix/capability graph from `xss-review.md`.

Only the owner may approve it. Revisions append a signature; replacement creates a new ID and
marks the old SPEC `SUPERSEDED`.

## Ticket

Use `ticket-decomposition.md` for splitting and low-model admission. This section owns the
canonical ticket schema; do not duplicate its fields in prompts or decomposition records.

Create vertical, independently observable tickets only after SPEC approval and Context
reattachment. One ticket is the complete implementation contract and records:

- exact SPEC/AC, PRD, CHG, Context and baseline references;
- state and finite `Acceptance Closure Set` revision;
- control owner, implementation owner, reviewer, task/worktree/branch, environment, scope and
  dependencies;
- domain/application/infrastructure/UI effects, public contracts and exact source locations;
- named TDD cells, first-red evidence slots, verification commands and return contract;
- implementation language and strict checker;
- delivery profile, resource-plan reference, model capability tier, lane ownership and helper
  plan;
- XSS classification and exact XSS matrix reference;
- completion, operations and rollback evidence fields.

The ticket owner and supervisor may only bind the sealed shared-Context revision and bounded
feature/source references. They must not create or append shared Context. A missing fact is
`UPSTREAM_DECISION_REQUIRED`; a changed fact is `REQUIREMENT_CHANGED`, both routed to the
architecture owner before ticket admission.

`modules/element/` is an index to target-owned source, types, contracts and tests. It never
copies production source.

## Frontend contract

When a formal UI or design source is involved, also apply `ui-design-handoff.md` before ticket
admission.

A formal frontend ticket names component boundaries, input/output/state, Composition Root,
dependency interfaces and lifetime, production bindings and test fakes. UI components do not
instantiate global singletons, read environment configuration or access external services
implicitly. Acceptance covers loading, empty, failure, permission and accessibility behavior.

## Strong-type preflight

Before dispatch and again before the implementer's first red:

1. Construct every public success-path DTO, value object, enum, event, request/response and
   dependency contract through its ordinary public constructor/validator/round trip. Cover
   exact finite states, nullability and primitive types.
2. For domain rules a strict checker cannot prove, name exact boundary allowlists/denylists and
   a committed AST/source/schema gate.
3. Reverse-mutate each such gate with one bounded forbidden form; it must turn red and return
   green after byte-for-byte restoration.
4. Reject success evidence using bypass constructors, update, cast, coercion, `Any`, dynamic
   member lookup or historical-object reuse. Malformed bypass values belong only to named
   negative rejection cells.

Strict checker success is necessary but insufficient. Missing or failed preflight is
`HALT / TICKET_SCHEMA_INVALID` and `TICKET_DEFECT / NON_DISPATCHABLE`.

## Dispatch normalization

Canonical ownership is fixed:

- global rules: `AGENTS.md`, `Workflow.md`, `CodeReview.md` and this skill's references;
- product behavior/architecture/acceptance: SPEC;
- complete implementation contract: ticket;
- transitions, IDs, commits, review results and exceptions: Work Progress Report;
- instruction: identifiers only.

The first dispatch envelope contains only `ACTION_REQUIRED`, `dispatch_ref`,
`registry_commit`, `ticket`, `receipt` and `owner_task`. An admitted resume may add one bounded
resume-state line. Resolve worktree, branch, baseline, SPEC/AC, scope, TDD, type matrix,
verification, safety and return contract from the exact committed ticket. Correction uses
`correction_ref`, exact review commit and the original ticket/receipt/owner indexes.

If an instruction needs behavior absent from the ticket, update and commit the canonical source
first. Unreadable, unresolved, mismatched or competing references halt before mutation with
`HALT / DISPATCH_REFERENCE_INVALID`.
