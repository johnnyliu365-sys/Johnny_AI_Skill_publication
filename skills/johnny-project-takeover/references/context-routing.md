# Minimal Context routing

Read this reference when constructing `ContextView`, resolving side-context references or
selecting source/capability input for a stage.

## Minimal view

Resolve `RouterState.artifact_refs` by current stage, event, delivery stage and authority.
Select the smallest complete source set. Never copy full shared Context, chat history, the
whole module catalog or unrelated skills into an instruction.

`ContextView` is a durable descriptor containing purpose, source references, stage, budget
and invalidation events. Raw source text exists only in the ephemeral `ContextPacket` and the
reading Agent's own permitted workspace. Do not persist it in Router/LangGraph/Temporal state,
telemetry, citation ledgers or shared Context.

Expose only capability metadata needed for selection. Load the selected skill body and only
its directly applicable reference. Capability selection reduces context; runtime role and
host gates still enforce authority.

## Shared project Context lifecycle

Shared project Context is an architecture artifact, not a progress log or a ticket scratchpad.
The architecture owner may create its draft during `ARCHITECTURE` and `GRILL`; the `CONTEXT`
stage seals one owner-approved revision before SPEC approval. Its content is limited to stable
cross-feature facts, repository/trust identity, invariant ownership/security boundaries,
approved architecture references and a metadata-only feature index.

After sealing, `SPEC`, `TICKETS`, `IMPLEMENT`, `SMOKE_TEST`, `REVIEW` and `HANDOFF` receive
read/reference capability only. A supervisor, ticket splitter, dispatcher, implementer or
reviewer must not append ticket state, handoff text, commits, tests, findings, branches,
worktrees or duplicated SPEC/policy prose to shared Context. They create bounded `ContextView`
and side-context references to the owning artifact instead.

A missing or changed shared fact returns `UPSTREAM_DECISION_REQUIRED` or
`REQUIREMENT_CHANGED`. The Router marks the architecture owner `WAKE_REQUIRED`; an armed runner delivers that wake
(see SKILL.md § Automation readiness — without one, the owner relays it). The route requires an approved change
reference before a new shared-Context revision can replace the sealed one. Replacement
invalidates prior side-context mappings; it never edits a sealed revision in place. There is no
line-count quality gate: admission is determined by the allowed content kinds, lifecycle,
authority and reference completeness.

## Side-context mapping

Each new Router event creates a new `side_context_id`; a retry of the same event keeps the
same ID. Record only:

```text
source reference + revision + span
  -> side_context_id
  -> consumer fingerprint
  -> target Grill, SPEC or ticket artifact
```

The consumer fingerprint identifies agent profile/version, worktree and execution instance
without containing secrets or prompt text. The reading Agent may keep the referenced span in
its own workspace with provenance, but that local evidence is not shared Context.

`CONTEXT_REFERENCE_CLOSED` closes the mapping. A changed source, requirement or approval
invalidates the old reference; the next read resolves the new revision and receives a new ID.
References provide traceability only. They do not authorize implementation or replace change
control.

## Reusable modules

When reusable source is relevant, first use `library/MODULE_CATALOG.md` or
`$apply-reusable-modules` to select the minimum `READY` module. The catalog limits reading;
adoption still requires Grill, SPEC and ticket approval and must not create a runtime
dependency from the target project to this plugin.
