# External capability admission

Read this reference when admitting, classifying or invoking an optional external capability, or
when deciding whether its output may enter a stage. An external capability is a tool, skill or
service outside the governed workflow that supplies orientation, craft or transport. It is never
part of the workflow's authority chain.

## Typed classification

```text
CapabilityKind   = CODEBASE_MAP | DESIGN_CRAFT | OUTPUT_REDUCTION
CapabilityState  = AVAILABLE_AUTHORIZED | AVAILABLE_NOT_AUTHORIZED
                 | UNAVAILABLE | DECLINED
CapabilityTier   = REGIME | ARTIFACT
CapabilityTarget = DOM | NATIVE_ENGINE | NATIVE_MOBILE | TERMINAL | ANY
```

Classify state at the stage that first needs the capability and persist only metadata in Router
state. `CapabilityState` carries the same four values as `DesignCapabilityState` in
`ui-design-handoff.md` by design: a design source and a design capability classify identically,
and routing treats them the same way when one is absent.

## Admission rules for every kind

1. **Optional, never a prerequisite.** `UNAVAILABLE` or `DECLINED` continues on the existing
   path. An absent capability never blocks a stage and never returns `ROUTE_REFERENCE_INVALID`.
   Do not install a capability merely because a project looks like it could benefit.
2. **Scope the installation to the target that approved it.** A machine-wide installation
   applies its triggers to every project, including work where the capability has no scope.
3. **Input, never authority.** The decisions named by the governing references — finite states,
   boundaries, security classes, file-change authority, review conclusions — stay where those
   references put them. Where a capability's own text asserts one of them, the governing
   reference is canonical.
4. **Output ranks as lead or finding, never as evidence or conclusion.** Confirm capability
   output against the source before a Grill answer, SPEC, ticket, review finding or commit
   depends on it. No capability output serves as implementation authority, review evidence or
   merge source.
5. **Kept output lands target-owned.** Anything worth keeping is written under the target's own
   paths and versioned there. Nothing is written into plugin trees, and the target gains no
   runtime dependency on the capability.
6. **Verdict stages stay unmediated.** A capability that reduces, intercepts or redirects what
   an Agent reads is restricted at `SMOKE_TEST` and `REVIEW` as the owning reference specifies.
   The reviewer's independent read of product, filesystem and Git evidence is never mediated.

## Tier and target fit

State answers "installed and authorized?". Tier and target answer "applicable here?". Both gates
must pass, and both are classified once at admission so later stages refuse a mismatch without
re-litigating it.

- `REGIME` — cross-feature invariants: colour and type systems, spacing scales, motion and
  interaction conventions. Platform-independent; admissible whatever the target runs on.
- `ARTIFACT` — concrete implementation output: components, layout structures, generated markup
  or code, animation implementations. Admissible only when the capability's `CapabilityTarget`
  matches the target project's actual UI or runtime platform.

An `AVAILABLE_AUTHORIZED` capability whose `ARTIFACT` tier targets `DOM` contributes only its
`REGIME` tier to a `NATIVE_ENGINE` project. The mismatch is a classification, not a defect:
record it once at admission and stop re-asking.

## Kind registry

| Kind | Owning reference | Kind-specific rules that stay there |
| --- | --- | --- |
| `CODEBASE_MAP` | `discovery-change.md` | evidence rank of inferred edges, approved always-on block, hook modes, provider pinning |
| `DESIGN_CRAFT` | `ui-design-handoff.md` | regime sealing, variation freeze, narrowing beside a human design source |
| `OUTPUT_REDUCTION` | `context-routing.md` | `LOSSLESS`/`LOSSY` classification and its stage table |

Admitting a new kind extends `CapabilityKind`, adds one registry row and places its specific
rules in exactly one owning reference. The rules above apply to every kind without restatement;
a kind-owning reference must not restate them, only extend them.
