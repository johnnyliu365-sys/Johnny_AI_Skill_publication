# Codex native same-lifetime delegation

This reference governs one already-admitted implementation continuation. It is
instruction-level coordination inside the current Codex lifetime; it is not a
runner, queue, durable dispatcher or cross-lifetime wake mechanism.

## Admission gate

Only the current-session reviewer may admit this lane. The Router decision must
be an exact, committed-ticket-bound `AUTO_CONTINUE → IMPLEMENT` decision. Before
calling the native operation, the reviewer verifies every binding below against
that ticket and the live repository state:

| Binding | Required evidence |
| --- | --- |
| Ticket | Exact committed ticket and its approved acceptance closure |
| Workspace | Reviewer-created repository-contained worktree |
| Source identity | Ticket-bound branch and baseline |
| Capability | Selected implementation profile/capability from the ticket |
| Lane | Same-lifetime direct synchronous continuation |

The reviewer is the delegation owner and remains responsible for waiting,
receiving the typed result, review, reverse mutation and integration gates. The
delegated implementation owner is exactly the owner named by the ticket; do not
create helpers or broaden the task.

## Native operation and completion

After all bindings pass, the reviewer calls Codex's native
`collaboration.spawn_agent` exactly once, passing only the ticket-bound owner
task and the identifiers needed to resolve the exact ticket. The selected model
and effort come from the approved ticket/profile at dispatch time. This
reference never selects, embeds or repeats a provider/model literal.

The reviewer then waits for the delegated owner's completion with `wait_agent`.
Waiting is synchronous and one-shot, without activity/status polling. Do not
poll activity, status, heartbeats or an equivalent progress endpoint. On
completion, receive the owner's typed `ImplementationReturn`, perform the ticket's review and
reverse-mutation gates, and return an `ACTION_COMPLETED` event to the Router
only when the declared implementation evidence is complete.

## Lifetime and failure boundary

The bridge disposition for this direct lane is `NOT_REQUIRED`. The lane neither
requires nor creates a handoff receipt, pending descriptor, runner, queue,
gateway, durable state, host readback adapter or fabricated native adapter.
Those mechanisms remain reserved for a cross-lifetime receipt-bound handoff;
their absence cannot block this already-admitted same-lifetime continuation.

If native delegation or the selected ticket/profile capability is unavailable,
the only result for this lane is `HALT / CODEX_NATIVE_DELEGATION_UNAVAILABLE`.
Do not implement the
ticket as a reviewer fallback, wake another owner, enqueue work, issue or mint a
receipt, create a descriptor, or substitute an unverified adapter. No other
failure path may silently change the lane or its owner.
