# Agent Context lifecycle

Read this reference when constructing, handing off, invalidating or closing an Agent's bounded
working Context. An Agent Context is a temporary view over exact artifact-tree leaves; it is not
shared project Context and is never another progress log.

## Role-scoped views

- The architecture owner receives the current requirement/change branch, architecture sources
  and the shared-Context draft or sealed revision needed to close one SPEC revision.
- The supervisor/reviewer receives one current decision closure: exact approved SPEC, current
  ticket/review leaf and the minimum policy/source references.
- An implementation owner receives exactly one ticket context bound to ticket ID/revision,
  receipt, owner, worktree, branch, baseline, side-context ID and expected return.
- A research helper receives one reviewer-owned read-only query leaf and returns only bounded
  findings/evidence references.

## Ticket isolation

Implementation Context is single-ticket. Selecting a different ticket always closes the old
`ContextView`/side-context mapping and creates a new ID; no raw text, inferred decision, resume
summary or uncommitted evidence crosses that boundary. Same-ticket correction may reuse the
ticket identity only when the revised ticket/review baseline and bounded resume state are
explicitly rebound; a changed ticket revision invalidates the prior view.

Durable Router state retains only identifiers, revisions, digests and lifecycle state. It does
not retain an Agent transcript, full ticket, full SPEC, source body or prior ticket Context.

## Fail-closed rules

- Different ticket, owner, receipt, worktree, branch, baseline or revision:
  `HALT / AGENT_CONTEXT_BINDING_MISMATCH`.
- Closed, replaced or stale view: `HALT / AGENT_CONTEXT_STALE`.
- Missing required upstream fact: `UPSTREAM_DECISION_REQUIRED`.
- Changed requirement or shared fact: `REQUIREMENT_CHANGED` and return to the architecture owner.

Closing a view removes its ephemeral packet and marks its metadata reference closed. It never
deletes target-owned source, commits, reviews or archive evidence.
