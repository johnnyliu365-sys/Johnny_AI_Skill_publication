---
description: Take over or resume a project through Johnny's governed workflow
argument-hint: [this session's objective]
---

Load the `johnny-project-takeover` skill and follow it for this project.

The owner's objective for this session: $ARGUMENTS

Before proposing any action, read the target project's own governing files
(`AGENTS.md`, `CLAUDE.md`, `Workflow.md`, contributing and security policy,
whatever exists). Those rules outrank this plugin's workflow. Johnny's
Workflow is the fallback only where the target project has established none.

Then converge on the single next governed step and say what it is.

When the Router has not admitted an exact committed ticket-bound action, keep
this entry point in pre-ticket narration: do not begin implementation work,
because this plugin's control plane opens tickets and reviews deliveries and
implementation belongs to a named implementation owner.

There is one explicit same-lifetime continuation. When the Router has already
declared an exact ticket-bound same-lifetime `AUTO_CONTINUE → IMPLEMENT` action, the
pre-ticket narration rule does not apply. The current-session reviewer owns
the continuation: after checking the exact ticket, reviewer-created worktree,
branch, baseline, selected ticket/profile capability and direct same-lifetime
lane, invoke Codex's native `collaboration.spawn_agent` for exactly one
ticket-bound implementation owner. Read the selected model and effort from the
ticket/profile; do not author provider or model literals here. Wait for that
owner with `wait_agent` and no activity or status polling, then review the
returned `ImplementationReturn` and perform the declared review gates.

If native delegation or the selected ticket/profile capability is unavailable,
return only `HALT / CODEX_NATIVE_DELEGATION_UNAVAILABLE`. This direct lane has
no receipt, runner, queue or descriptor prerequisite and must not fabricate a
bridge or fall back to reviewer implementation.
