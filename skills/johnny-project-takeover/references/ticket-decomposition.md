# Low-model ticket decomposition and admission

Read this reference when a supervisor decomposes an approved SPEC, validates whether a ticket
is safe for the default implementation model, or replans after convergence failure.

## Closed decision

```text
TicketDecompositionDecision = READY_LOW_MODEL
                            | SPLIT_REQUIRED
                            | UPSTREAM_DECISION_REQUIRED
                            | HIGH_ASSURANCE_REQUIRED
```

A `READY_LOW_MODEL` ticket has exactly one observable closure, one implementation owner, one
primary change/effect boundary, a finite TDD matrix, deterministic verification and zero
unresolved design decisions. File count, source-line count and estimated coding time are not
decomposition criteria.

## Decomposition method

Split along the smallest boundary that preserves an independently observable vertical result:

1. behavior or state transition;
2. effect/transaction boundary;
3. ownership or Composition Root boundary;
4. independently provable verification closure.

Do not split a feature into incomplete horizontal layers such as model-only, backend-only,
frontend-only or tests-later tickets. Shared public contracts must be frozen upstream before
dependent tickets. If two slices must write the same contract or cannot be accepted
independently, keep one owner or create a prior contract ticket with an explicit integration
order.

## Admission closure

Before `READY_LOW_MODEL`, the exact committed ticket must resolve all of these from the approved
SPEC and target Context:

- one named observable outcome and finite Closure revision;
- exact public input/output/state/error contracts and nullability;
- exact data/effect owner, dependency direction, Composition Root and rollback/compensation;
- exact source/symbol or creation locations and the writable scope;
- named positive, negative, boundary and failure TDD cells plus an authentic first-red command;
- strict type checker, focused/regression/build/smoke commands and deterministic expected result;
- environment, dependency, worktree/baseline and applicable security/XSS/UI references;
- typed `ImplementationReturn` and evidence-only handoff fields.

The strong-type preflight in `specification-ticketing.md` remains mandatory. The first dispatch
still carries identifiers only; this reference does not duplicate the ticket into the prompt.

## Sealed Context input

Ticket decomposition treats the exact sealed shared-Context revision as immutable input. The
supervisor may select feature/ticket source spans and emit metadata references, but may not
create, revise or append shared Context while splitting, admitting, dispatching, correcting or
reviewing a ticket. If the approved SPEC cannot be compiled without a new shared fact, return
`UPSTREAM_DECISION_REQUIRED`; if a previously sealed fact changed, return
`REQUIREMENT_CHANGED`. Both routes mark the architecture owner `WAKE_REQUIRED` (delivered only where a runner is
armed; otherwise the owner relays) instead of letting the
supervisor manufacture or persist the missing meaning.

## Fail-closed routing

- Use `SPLIT_REQUIRED` when the contract is complete but more than one observable closure,
  owner/effect boundary or independently verifiable responsibility remains.
- Use `UPSTREAM_DECISION_REQUIRED` when semantics, architecture, public contracts, AC or
  ownership are missing, ambiguous or contradictory. Return to the architecture owner; the
  supervisor must not fill the gap.
- Use `HIGH_ASSURANCE_REQUIRED` when the delivery Profile or a hard escalation trigger requires
  stronger architecture, threat/failure analysis or verification before dispatch.
- Missing schema or preflight evidence remains `HALT / TICKET_SCHEMA_INVALID`; missing or
  mismatched committed references remains `HALT / DISPATCH_REFERENCE_INVALID`.

Replanning after convergence preserves reviewed commits as evidence. It changes the Closure or
ticket decomposition through control-plane artifacts; it never resets, overwrites or silently
reuses historical implementation source.
