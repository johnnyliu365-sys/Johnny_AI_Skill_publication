# Implementation authority and workspace binding

Read this reference when admitting an implementation owner/task, controlling another Agent,
validating worktree authority or processing same-ticket corrections.

## Role separation

The control-plane Agent owns Wayfinder, Architecture/Grill, Context, SPEC, ticket, preflight,
implementation handoff, independent review and product handoff. It does not edit or commit an
approved ticket's production source, tests, migration or deployment unless the project owner
records a ticket-scoped owner override.

The named implementation owner receives exactly one approved ticket in one owner worktree. It
implements, tests, verifies, commits and returns a typed result. It cannot change requirements,
architecture, public contracts or AC; any such conflict returns `CHANGE_DETECTED`.

Every ticket names control owner, implementation owner and reviewer. The reviewer is the only
Agent-to-Agent orchestrator.

## Orchestration gateway

For a cross-lifetime handoff, Johnny's reviewer-owned gateway is the only Agent-control effect
entry. A reviewer capability bound to the exact project, ticket, reviewed handoff, unconsumed
receipt and target owner may create/fork the implementation task, send/follow up/steer, wait,
interrupt or close it. This gateway, its receipt and its host readback are not prerequisites for a
same-lifetime synchronous lane: the reviewer directly dispatches, waits and receives the owner,
and an unavailable bridge must not halt that lane.

The implementation owner receives no gateway port/credential and no multi-agent or thread-control
tool in either path. Direct or indirect spawn/delegate/send/follow-up/steer/wait/interrupt/close
returns `HALT / ROLE_FORBIDDEN` before effect.

Prompt text, model name, role name, configuration, `CapabilityRef`, MCP alias and indirect
adapter are not authority. Each cross-lifetime gateway effect validates reviewer role/capability,
project, ticket, handoff, unconsumed receipt, target owner, worktree, branch, baseline, action and
correlation against the live pending descriptor. Copy, forgery, replay or substitution fails
closed. Effective-session tool absence and gateway unreachability require supported host readback
only on that cross-lifetime path; source/config inspection alone is insufficient. A missing bridge
is `UNAVAILABLE`, not evidence that a wake was delivered.

## Task/worktree admission

For a cross-lifetime resumed task, obtain the task's active workspace root from product/task
readback and the ticket worktree from Git metadata. Admit only when all are equal:

1. platform-normalized absolute root;
2. filesystem identity after resolving reparse points/symlinks;
3. linked-worktree `.git` pointer and registered worktree metadata.

Prompt/handoff paths, shell `cd`, command working directory, environment variables, sibling
access and task self-report are not workspace binding. Do not launch from the control project
and `cd` into the implementation worktree. Do not create a replacement worktree merely to pass
admission.

Missing/unreadable/mismatched identity returns `HALT / TASK_WORKSPACE_MISMATCH` before question,
pending descriptor, receipt, branch, source access or host/Git effect. Persist only opaque
project/task/workspace/worktree references, evidence digest, revision and verification-time
reference, never raw paths.

For a same-lifetime synchronous lane, the reviewer directly allocates a repository-contained
worktree and binds the owner to its exact ticket, branch and baseline. The reviewer validates the
worktree's Git metadata and containment as part of that allocation, but absent product/task host
readback, a receipt or a live descriptor may not block the lane. The three-way normalized-root,
filesystem-identity and Git-metadata proof above remains required whenever a task is resumed
across lifetimes.

## Allocation and correction

One implementation owner holds at most one active lane. Release a completed/integrated
allocation before assigning the next ticket.

`CHANGES_REQUESTED` keeps the same ticket, owner, worktree, branch, allocation and valid receipt
by default. Record the review commit and correction handoff, then append correction commits.
Never reset, amend, force, overwrite or delete reviewed commits.

Create a new branch only with recorded `FRESH_BRANCH_REQUIRED` evidence:

- approved `REQUIREMENT_CHANGED` route;
- owner/worktree replacement;
- unsafe worktree contamination that cannot be recovered safely; or
- verified branch/baseline conflict that prevents safe additive correction.

New defect discovery or a request for more tests is not sufficient. Preserve old branch/commit
references and use traceable Git transfer with full re-verification. Active owners may clear
known reproducible residue in their own worktree; no other Agent may edit across worktrees.
