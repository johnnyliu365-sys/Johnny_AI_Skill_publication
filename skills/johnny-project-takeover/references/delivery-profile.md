# Delivery profile and lifecycle

Read this reference during intake, delivery-stage changes, resource planning, POC freeze or
staging admission. Do not load it for an implementation ticket whose profile and baseline
have already been admitted.

## Delivery maturity

`delivery_stage` describes the product promise:

- `POC` validates the smallest explicit feasibility assumptions and ends in a GO/NO-GO.
- `MVP` requires an approved change record and a new Wayfinder pass over MVP value, risk,
  scope and acceptance.
- `COMMERCIAL` requires an approved change record and a new Wayfinder pass over operational,
  security, support, observability, data-governance, legal and service-level commitments.

Do not infer a maturity upgrade from chat or from a successful POC. Router state and the
approved Project Workflow Profile must agree or the route suspends.

## Workflow intensity

`delivery_profile` describes the assurance needed by the current project or ticket:

- `COMPACT`: one bounded, reversible change using an established pattern and deterministic
  verification. Requirements, AC, owner, green test evidence (baseline-red only for defect
  corrections) and independent review still apply.
- `STANDARD`: multiple local components, a shared contract, a new adapter or moderate
  uncertainty.
- `HIGH_ASSURANCE`: high impact, difficult recovery, new architecture or a formal external
  boundary. Include alternatives, threat/failure matrix and adversarial verification.

Intensity is derived, never asserted. The typed authority is `WorkloadAssessment` plus
`derive_workflow_intensity()` in `library/workflow_router/contracts.py`: five evidence-backed
signals (change surface, uncertainty, recovery difficulty, security surface, external
effects), each with a fixed intensity floor, combined by deterministic maximum. There is no
override input, so a lower intensity cannot be claimed directly. The assessment is committed
at INTAKE inside `NormalizedGoal.workload`; a missing assessment means minimum `STANDARD`
and `COMPACT` is unclaimable. Authentication, authorization, secrets, payment, regulated
data, destructive migration, release/deployment, signing/supply chain, irreversible effects,
distributed consistency, sandbox escape, privileged host capability and privileged XSS map
to the `PRIVILEGED` / `IRREVERSIBLE` / `NETWORK_OR_RELEASE` signal values and therefore force
`HIGH_ASSURANCE`. Project size, file count, line count and model name never lower the
profile.

## Adaptive workflow shape

The derived intensity scales the workflow deterministically; stage order and Router
authority never change, only what each stage must produce:

| Aspect | `COMPACT` | `STANDARD` | `HIGH_ASSURANCE` |
| --- | --- | --- | --- |
| Discovery (`WAYFINDER`/`ARCHITECTURE`/`GRILL`) | One combined discovery leaf may satisfy all three stages; the stages execute as three bounded `AUTO_CONTINUE` hops over that leaf in the same session, waking no additional model | One artifact per stage | One artifact per stage plus alternatives and a threat/failure matrix |
| `SPEC` | Micro-SPEC: acceptance criteria, public contract and rollback rule on one page | Full SPEC | Full SPEC plus adversarial acceptance review |
| `TICKETS` | Exactly one ticket | Per decomposition reference | Per decomposition reference with high-assurance admission |
| Review depth | Focused matrix and strict typing | Focused matrix plus full suite | Full suite plus reverse mutation and adversarial probes |
| Red evidence | Baseline-red for defect corrections only; new behavior needs green tests | Baseline-red for defect corrections; green tests at the approved seam | Baseline-red for corrections plus reverse mutation proving test quality |
| Handoff and closure | Commit-as-handoff: one implementation commit whose message carries AC, results and digests; no separate handoff leaf or evidence table | Ticket and handoff leaves per the artifact tree | Ticket and handoff leaves plus the adversarial review record |
| Default model tier | Implementation and drafting stay on the low tier; the supervisor tier reviews once | Low-tier implementer, supervisor-tier reviewer | Supervisor-tier-or-higher implementer or reviewer; architecture-owner wake conditions widen |
| Research helper | Not admitted | One optional read-only helper | One optional read-only helper |

A change declared with a test-exempt `ChangeClass` (`DOCS_ONLY`, `COMMENT_ONLY`,
`SCHEMA_VALIDATED_CONFIG`, `TYPE_CHECKED_RENAME`) skips test writing at every intensity; the
exemption is a typed declaration whose own gate (schema validation, strict typing, compile)
still runs, and any production-behavior effect voids it. Ceremony scales with future readers
and writer distrust, not with project size: evidence tables and handoff leaves exist to
compress state for later sessions and lanes, and reverse mutation exists to prove test
quality — both stay wherever those consumers exist.

`DELTA` intake combined with a derived `COMPACT` intensity is the minimal path: one combined
discovery hop over the affected slices, one micro-SPEC, one ticket, focused review.
Reassessment is mandatory whenever new evidence raises any signal; the derivation then
upgrades automatically. A downgrade requires new committed evidence lowering a signal plus
owner approval, and never removes already-required tests or findings.

## Resource plan

Default to one implementer and no helper. Use zero implementers for read-only/document-only
work. Add parallel lanes only when ownership, files and AC are disjoint and the integration
order is explicit. A high-search, low-authority, zero-write-conflict task may receive one
reviewer-owned read-only/no-code research helper. The implementation owner never controls a
helper or another Agent. Model tier is a cost/capability choice, not authority.

Role assignment, the default Terra supervisor/Luna implementer mapping, SPEC-readiness sleep
and typed wake conditions are defined only in `model-role-routing.md`. This Profile stores the
versioned opaque model references and capability evidence; it does not turn a model name into
authority.

Reassess when requirements, risk, security/XSS classification, coupling or verification
results change. Upgrade automatically when evidence requires it; downgrade only with recorded
evidence and without removing required tests or findings.

## POC freeze and staging

After independent POC review and owner acceptance, create a typed `StagingTransitionPlan`
bound to repository identity, accepted POC commit, expected staging ref, frozen version record
and plan digest.

- Without unique review, acceptance and commit identity, return
  `WAIT_FOR_HUMAN / POST_POC_BASELINE_REQUIRED` and create no feature worktree.
- A local staging ref may be created or verified-fast-forwarded only to the accepted POC or a
  verified successor. Never reset, force, delete, overwrite the frozen POC or resolve a
  conflict silently.
- Remote staging publication is a separate effect requiring authority, remote-history check
  and exact SHA readback.
- Every later branch/worktree is admitted from the read-back staging SHA. Wrong ref, stale or
  dirty base, divergence, repository mismatch or wrong ancestry halts before effect.
- Staging integration is not release. Packaging requires a separate promotion gate.
- Staging is not an installation/effect sandbox. Host, installation, removal, migration and
  other effects require a receipt-bound disposable environment.
