# XSS review

Read this reference whenever untrusted data may enter a Browser, WebView, HTML/DOM renderer
or JavaScript execution context. This file is the canonical XSS policy for discovery, SPEC,
ticket, TDD and review.

## Classification

Freeze one classification before implementation:

1. `XSS_NOT_APPLICABLE`: no untrusted data reaches a renderer/execution context; record a
   verifiable reason.
2. `STANDARD_XSS_REVIEW`: untrusted data reaches the renderer, but JavaScript cannot reach a
   privileged host capability.
3. `PRIVILEGED_XSS_REVIEW`: JavaScript directly or indirectly reaches Native Bridge, IPC,
   Extension API, filesystem, process, credential, host automation or another privileged
   capability.

If privileged reachability cannot be disproved, classify it as privileged. Such work is
`HIGH_ASSURANCE`.

## Frozen source-to-sink contract

Record every untrusted source and owner; parsing, transformation and storage stage; exact
output context and DOM sink; context-aware encoding/sanitization; prohibited bypass API;
CSP, Trusted Types, sandbox, origin and navigation boundary; and a repeatable isolated
renderer test method.

Do not accept “escaped”, “framework default” or a sanitizer name as evidence.

For privileged XSS, additionally record every reachable bridge/IPC/extension capability,
minimum authority, allowed origin/frame/caller, named message schema, authorization point,
replay behavior, failure result and host-effect fake. Renderer-to-host access is deny-by-default.
Prompts, hidden UI, method names, capability strings and frontend-only checks are not security
boundaries.

## TDD matrix

Name every applicable matrix cell and explain each omission:

- plain text and permitted markup positive cases;
- script and event-handler payloads;
- dangerous URL schemes;
- SVG and foreign content;
- attribute, URL, CSS and template-context breakout;
- HTML entity, URL and Unicode encoding variants;
- stored, reflected and DOM-based sources;
- alternate sink, hydration, template helper, markdown/HTML conversion and second decode;
- redirect, navigation and reload behavior.

Use an isolated renderer without real host effects. Assert that the attack marker does not
execute and that content appears only in the intended context. String contains/not-contains,
snapshots, sanitizer unit tests and source scans do not replace renderer behavior tests.

For privileged XSS, inject fake privileged ports and test malicious script, wrong origin,
frame or caller, wrong schema, extra fields, unauthorized action, replay, indirect adapter and
post-navigation context. Every invalid path must fail before host effect. Retain one exact
authorized positive call to prove the gate did not merely disable the feature.

Record first red, green and at least one bounded reverse mutation that makes a frozen attack
cell execute or reach the privileged gate. Restore byte-for-byte afterward.

## Review

Trace each source to every sink and search for equivalent escape hatches such as `innerHTML`,
`outerHTML`, `insertAdjacentHTML`, `document.write`, HTML/template/markdown converters,
script URLs and dynamic evaluation. Match each reachable sink to a test cell or explicit
unreachability proof.

For privileged cases, enumerate JavaScript-to-host paths in reverse and verify origin, caller,
schema, action allowlist, authorization, replay and effect-before-gate behavior. A missing or
downgraded classification is `TICKET_DEFECT` or `REQUIREMENT_CHANGED`; a bypass of the frozen
contract is `IMPLEMENTATION_DEFECT`.
