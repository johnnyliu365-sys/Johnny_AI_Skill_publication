# Implementation language policy

Read this reference during architecture, SPEC, ticket schema validation or an approved language
change. Do not load it for an admitted ticket whose language and checker already match.

## Decision order

Resolve conflicts in this order:

1. maintainability for the team and future Agents;
2. consistency of contracts, types, conventions and toolchain;
3. ecosystem/performance fit.

The maintainable runtime count limits language count; domain count does not. Use one backend
language. If domains suggest different choices, select the one language that covers all with
the lowest maintenance cost and record the alternatives and rationale in target-owned Context.

Deviation requires measured evidence and an approved change-control route. Exceptions are only
platform-mandated runtime or regulation/maturity binding. SQL is not counted as a general
implementation-language choice.

Before adopting multiple runtimes, record network failure surfaces, duplicated/drifting
contracts, type loss across process boundaries, trace propagation, deployment/dependency cost
and the replacement for a single composition root.

## Gate

Every SPEC names the implementation language. Every ticket names the same language and strict
checker; a non-implementation parent/reviewer-only artifact uses explicit `N/A` plus reason.
Missing or conflicting language is `HALT / TICKET_SCHEMA_INVALID` before implementation.
The target project may choose the delivery stage at which this gate becomes mandatory, but that
choice must be target-owned and versioned in Context.
