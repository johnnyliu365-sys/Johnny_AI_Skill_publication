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

## Optional codebase-map capability

Read this section when `intake_mode` is `TAKEOVER` or `DELTA` and an existing codebase must be
located before Wayfinder can bind `baseline_reference` or before Grill can scope a change. A
codebase-map generator admits as `CapabilityKind = CODEBASE_MAP` under
[`capability-admission.md`](capability-admission.md), which owns state typing, installation
scope, authority rank and artifact landing for every capability kind. Classify during Wayfinder;
`UNAVAILABLE` or `DECLINED` continues with direct source reading.

### Evidence rank

The rank rule is `capability-admission.md` rule 4; a map narrows what to read, it does not
establish what is true. In this domain that means:

- An edge the generator marks as inferred rather than extracted from the source is a hypothesis.
  Confirm it against the source before it enters a Grill answer, SPEC, ticket or review finding.
- `baseline_reference` never binds to map output: the Strict Veto on locating an existing
  runtime, build and test baseline is satisfied by the real runtime, build and test surfaces,
  not by a map that describes them.
- When map and source disagree, the source wins. A stale map is a defect to regenerate or
  discard, not a discrepancy to reconcile.

### Boundary conditions

- Code-only extraction that runs entirely on the local machine has no external effect and needs
  no security review.
- Extraction that sends document, PDF, image or transcript content to a model provider is an
  external effect: apply `security-boundary.md` and pin the backend explicitly. Provider
  selection by auto-detection over ambient environment variables is prohibited — an unrelated
  credential present in the environment must never decide where target content is sent, and
  provider choice determines data residency.
- The generator's always-on instruction block in the target's own auto-loaded agent file is
  **required**, not optional. A rule that lives only in a reference an Agent must choose to read
  is a rule that gets skipped; the auto-loaded file is the only channel that binds every session.
  Install it.
- That block is target-owned from the moment it is written. The owner reviews its text like any
  other target rule, and it must be bounded to orientation: it may direct an Agent to consult the
  map first, and it must not grant the map evidence authority or tell an Agent to stop reading
  source. Where its wording exceeds that bound, the owner edits the block; this reference states
  the bound, the target file carries it.
- Advisory read hooks are permitted. A hook that emits a nudge, exits zero and fails open on any
  error leaves independent source reading intact, so it may stay enabled at every stage.
- A hook mode that denies or defers a read — including one that blocks only the first raw read
  per session — is prohibited at `SMOKE_TEST` and `REVIEW`. The reviewer's first raw read of the
  product, filesystem and Git evidence is the one `review-checks.md` depends on, and it is
  exactly the read such a mode intercepts. Enable that mode only in stages where no verdict is
  read from source.

### Approved instruction block

The block below meets the bound above and may be adopted verbatim, with tool and path names
substituted for the generator actually in use. It carries no project-specific fact, so it does
not go stale and needs no owner edit per project.

```text
## <generator>

Rules:
- For codebase questions, first run `<query command>` when <graph artifact> exists. Use
  `<path command>` for relationships and `<explain command>` for focused concepts. These
  return a scoped subgraph, usually much smaller than <report artifact> or raw grep output.
- If <navigation index> exists, use it for broad navigation instead of raw source browsing.
- The map is orientation, not evidence. An inferred edge is a hypothesis until the source
  confirms it; where map and source disagree, the source wins. Read the source before a SPEC,
  ticket, review finding or commit depends on a claim.
- Read <report artifact> only for broad architecture review or when the scoped queries do not
  surface enough context.
- After modifying code, run `<update command>` to keep the map current.
```

Two edits distinguish it from a generator's own default block. The opening declarative that
states what the project has is dropped: the heading already names the section, every rule guards
on its own artifact's existence, and an always-on block should assert no fact that a deleted map
would falsify. The evidence-rank rule is added, because a generator's default block ranks the map
against grep for cost and never ranks it against the source for truth — and a rank that lives
only in this reference is a rank the running Agent never reads.

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
