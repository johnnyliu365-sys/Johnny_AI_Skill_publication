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

## XSS boundary

External design metadata alone does not trigger XSS review. Apply `xss-review.md` only when
untrusted runtime data can reach Browser/WebView/HTML/DOM/JavaScript sinks. A JavaScript context
with Native Bridge, IPC, Extension API or another privileged capability still forces privileged
XSS review and `HIGH_ASSURANCE`.
