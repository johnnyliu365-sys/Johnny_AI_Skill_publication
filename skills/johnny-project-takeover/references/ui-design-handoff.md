# Optional UI design-source handoff

Read this reference when a requirement includes a formal UI, a design source or visual
acceptance. A design tool is an optional input capability, never an installation prerequisite.

## Typed source classification

```text
DesignSourceKind = FIGMA | SCREENSHOT | DESIGN_BRIEF
                 | EXISTING_DESIGN_SYSTEM | NONE

DesignCapabilityState = AVAILABLE_AUTHORIZED | AVAILABLE_NOT_AUTHORIZED
                      | UNAVAILABLE | DECLINED
```

Classify both values during Architecture/Grill and persist only metadata references in Router
state. Do not request or install Figma merely because the project has UI work.

## Routing

- `FIGMA + AVAILABLE_AUTHORIZED`: preflight the exact file/node/frame/variant, confirm design
  context and screenshot, and resolve only the required variables, assets, tokens and component
  metadata. Truncation requires another bounded metadata read, not an invented design.
- `AVAILABLE_NOT_AUTHORIZED`: `WAIT_FOR_HUMAN` for exact design-read authority; do not access the
  source or substitute credentials.
- `UNAVAILABLE` or `DECLINED`: continue with an approved screenshot, design brief or existing
  design system when one supplies a complete acceptance source.
- If formal new UI needs a visual source and none is approved, return
  `WAIT_FOR_HUMAN / UI_DESIGN_SOURCE_REQUIRED`; do not force plugin installation.
- Only when the approved SPEC explicitly requires an exact Figma node and that source cannot be
  resolved may the route return `HALT / DESIGN_SOURCE_UNAVAILABLE`.

Figma is design input, not target runtime and not implementation authority. Target-specific
file/node/variant identifiers belong in the target SPEC/ticket rather than global governance.

## UI implementation contract

The supervisor converts the approved design source into a target-owned
`UIImplementationContract` containing component/frame boundary, semantic DOM, inputs/outputs,
finite UI states, responsive breakpoints, tokens/assets, accessibility behavior, existing
design-system mapping, screenshot/visual acceptance and applicable renderer security class.

The implementation owner writes the HTML/CSS/component source from that contract. One UI ticket
delivers an observable component/frame with its HTML, CSS, responsive and loading/empty/error/
permission states together; do not split markup and styling into incomplete tickets. The
supervisor independently reviews behavior and visual evidence with an available browser/test
capability, and does not author the implementation it reviews.

## UI regime source and sealing

A `UIImplementationContract` is per-feature. The facts it maps onto — breakpoint policy, type and
colour system, component-library selection, interaction and motion convention, macrostructure
vocabulary — are cross-feature and invariant, so they are decided once and sealed, not re-decided
per ticket. Deciding them per ticket produces drift that no per-feature contract can detect.

Architecture selects the UI technical boundary; Grill closes the remaining UI questions; `CONTEXT`
seals one owner-approved revision. Major difficult-to-reverse choices additionally receive an ADR,
per `discovery-change.md`. After sealing, every downstream feature resolves
`DesignSourceKind = EXISTING_DESIGN_SYSTEM` and reads the sealed regime rather than re-deriving it.

The sealed regime is target-owned: tokens, reference implementations and the ADR live in the
target repository and are readable without any capability installed. A target must not depend on a
design-craft tool being present in order to build against its own sealed regime.

### Design-craft capabilities

A design-craft capability generates or audits visual and motion craft — theme and token systems,
macrostructure vocabulary, animation construction, library selection, craft review. It admits as
`CapabilityKind = DESIGN_CRAFT` under [`capability-admission.md`](capability-admission.md), which
owns state typing, installation scope, authority rank and artifact landing.

- A design-craft capability usually spans both tiers: colour, type, spacing and motion
  conventions are `REGIME` and admissible on any platform; components, macrostructures and
  generated markup are `ARTIFACT` and admissible only where the capability's `CapabilityTarget`
  matches the target's UI platform. A `DOM`-targeted generator contributes regime input to a
  `NATIVE_ENGINE` project and nothing else.
- Such a capability supplies craft; it does not hold authority. Finite UI states, responsive
  breakpoint policy, accessibility behavior, renderer security class, file-change authority and
  the review conclusion remain governed here and by `implementation-authority.md`,
  `security-boundary.md` and `CodeReview.md`. Where a capability's own text asserts one of these,
  this reference is canonical.
- A generator that deliberately varies structure between briefs is producing variety this regime
  exists to prevent. Use it to choose the regime once, then disable its variation before sealing.
- When an approved human design source exists, the generator does not author the design. Its
  admissible uses narrow to extracting a design source the owner approved and to auditing
  implemented output. Audit targets the implementation, never the approved design source.
- Craft findings enter review as findings only, under the `UI craft / motion` category in
  `review-checks.md`. They do not carry a review conclusion.

## XSS boundary

External design metadata alone does not trigger XSS review. Apply `xss-review.md` only when
untrusted runtime data can reach Browser/WebView/HTML/DOM/JavaScript sinks. A JavaScript context
with Native Bridge, IPC, Extension API or another privileged capability still forces privileged
XSS review and `HIGH_ASSURANCE`.
