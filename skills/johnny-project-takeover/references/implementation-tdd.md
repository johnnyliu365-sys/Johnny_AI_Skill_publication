# Implementation TDD and completion

Read this reference only after exact ticket, receipt, owner and workspace admission succeeds.

## One behavior at a time

1. Write an executable test at the ticket's approved seam.
2. For a defect correction, run that test against the defective baseline and record the red
   failure: baseline-red is mandatory at every intensity because it proves the test captures
   the exact defect. For new behavior, no first-red claim is required — a red run against
   code that does not exist yet proves nothing; test quality is proven instead by the
   reverse-mutation gate at `HIGH_ASSURANCE`, and by green tests at the approved seam
   elsewhere.
3. Write the smallest production change that makes it pass.
4. Run affected tests, strict type checks, lint, formatting, build and data validation.
5. Run the ticket's primary-path smoke test.

Do not start another behavior, ticket or commit before the current behavior and smoke gate are
green.

A change declared with a test-exempt `ChangeClass` (`DOCS_ONLY`, `COMMENT_ONLY`,
`SCHEMA_VALIDATED_CONFIG`, `TYPE_CHECKED_RENAME` in
`library/workflow_router/contracts.py`) skips test writing entirely; the exemption is a typed
declaration validated by its class's own gate (schema validation, strict type check and
compile), never a free judgment. Any production-behavior effect makes the declaration invalid.

The ticket must name every applicable TDD category from the canonical review checks. Generic
labels such as “normal/invalid/external/regression” are insufficient. A relevant category
missing from ticket design is a `TICKET_DEFECT`, not an instruction for the implementer to
invent new scope.

For defect corrections, record the baseline-red test name and failure reason in the ticket
evidence. For new behavior, record the test names and their green results; do not stage or
claim a ceremonial first-red run.

Ordering cannot be verified from the artifact, so it is not the evidence. What a test was
written before is unobservable after the fact and a claim about it is a claim about a process
nobody can check. **Discriminating power is observable, and it is what the ordering was ever
for.**每個具名行為都要交出反向突變證據：把該行為拿掉，指名哪個測試轉紅、失敗訊息是
什麼，還原後轉綠。突變沒有讓任何測試轉紅，表示那個行為沒有被測到——不論測試是先寫還
是後寫。Both directions must be reported; a mutation that was never restored is not evidence
either.

## Type and layering gate

Use named domain types, immutable models, explicit nullability and complete parameter/return
types. Dynamic external input is validated and converted at the boundary. Do not propagate
`Any`, implicit `any` or unvalidated dynamic objects inward.

Use `mypy --strict` or Pyright strict for Python, TypeScript strict for Node.js, and an
equivalent checker elsewhere. Domain holds invariants and values; Application holds use cases,
ports and transaction boundaries; Infrastructure implements external adapters; Transport/UI
handles serialization and presentation. Outer layers do not hold business rules or secrets.

## Smoke gate

Start the affected application/service or invoke its real local entry seam, run at least one
primary observable path and confirm expected result plus absence of obvious runtime/load
errors. If automation is impossible, record exact manual steps and result. Failure returns to
the TDD loop.

## Ticket completion

A ticket is complete only when:

- TDD and affected regression tests pass;
- type, lint, format, build and data gates pass, or a specifically authorized blocker is
  recorded;
- AC, error behavior, data contract, privacy/logging and applicable security matrices have
  reproducible evidence;
- the owner worktree creates one implementation commit containing only this ticket;
- the Work Progress Report records identifiers/results in a separate docs-only commit;
- no cache or unauthorized residue remains.

Return `ImplementationReturn`: `COMPLETED`, `BLOCKED` or `CHANGE_DETECTED`. Do not claim review
approval, merge, release or deployment.
