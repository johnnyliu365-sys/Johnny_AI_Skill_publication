# Discovery and change control

Read this reference for `WAYFINDER`, `ARCHITECTURE`, `GRILL` and confirmed requirement
changes. For Wayfinder's detailed evaluation procedure, also read `../../../Defined_wayfinder.md`.

## Wayfinder and architecture

Every new or inherited project starts with Wayfinder. Its sole goal authority is the committed
typed `NormalizedGoal` produced by INTAKE: `intake_mode` scopes the evaluation (`GREENFIELD`
runs all seven steps; `TAKEOVER` binds an existing `baseline_reference` and skips business and
cost derivation; `DELTA` re-converges only the slices named in `delta_scope`), and
`product_kind` selects the slice interaction-boundary shape (screen/page/flow, API endpoint,
CLI command or event contract). `NO-GO` stops the workflow until the
declared reassessment conditions are met. When required input is missing, Wayfinder emits one
typed `WAYFINDER_INFO_REQUIRED` round instead of guessing or free-form questioning: every
currently blocking gap is listed at once from the closed `WayfinderInputField` set, each gap
names the output field or strict-veto item it unblocks, answered fields are never re-asked,
and the round counter is closed at two. Answers become authority only after they are committed
into the intake goal record; `OWNER_INPUT_PROVIDED` then re-enters `WAYFINDER`. Round
exhaustion forces a terminal decision: `GO` with explicitly marked assumptions, or
`NO-GO / INSUFFICIENT_INPUT` whose gap list is the reassessment condition. `GO` produces a
Shared Context in this order:

```text
product position
-> observable frontend feature slices
-> backend capabilities and data pipelines required by each slice
-> composition and dependency-injection boundaries
```

Architecture works from that approved input. It may select structure and technical boundaries;
it must not infer missing user behavior or omit data ownership. Architecture's mandatory
output additionally includes, for every approved slice, the complete data pipeline
(validation/normalization, command or event, storage boundary, read projection, UI-state
return, lifecycle/privacy) and the full composition map: Composition Root, injected
dependencies, lifetime/scope and test-fake replacement points. Missing any of these is an
Architecture completion blocker — this gate moved here from Wayfinder, which now checks only
separability plausibility.

## Grill

Before a new feature, cross-module change, requirement redefinition or formal UI change,
read only the scoped requirements, approved artifacts, code, tests, Context and change history.
Close the following questions:

- observable result, error behavior and acceptance method;
- traceability from each frontend slice to one backend use case, data owner/pipeline, read
  projection and returned UI state;
- domain language, data ownership, flow, retention and deletion;
- UI, API, background work, cache, database, Provider, authorization, cost and operations;
- module responsibility, dependency direction, Composition Root, lifetime, production
  binding, test fake and immutable boundary;
- alternatives, risks, rollback/forward-fix and out-of-scope work;
- whether the XSS trigger in `xss-review.md` applies.

Confirmed facts update target-owned `CONTEXT.md`. Major difficult-to-reverse decisions also
receive an ADR. Without owner authorization, report a draft or gap and do not create a formal
artifact.

## Requirement change

When approved requirements, formal UI, data contracts, permissions, cache, Provider or
business rules change:

1. Stop affected implementation; mark unfinished tickets `BLOCKED` and replaced artifacts
   `SUPERSEDED`.
2. Read the Requirement Change Log and re-run Grill with impact analysis.
3. Add one `CHG-YYYYMMDD-NNN` record containing old rule, new rule, rationale, impact, PRD
   index and later the exact SPEC ID.
4. Update target-owned Context by removing invalid facts while preserving provenance.
5. Re-run specification approval and ticket approval.
6. Reattach shared Context references with a docs-only baseline commit when applicable.
7. Remove only tests replaced by the approved requirement; retain valid security, contract and
   regression tests.

Return event: `REQUIREMENT_CHANGED` until the new approved ticket baseline exists.
