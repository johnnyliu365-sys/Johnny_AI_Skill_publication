# Security, secrets and external effects

Read this reference when work touches secrets, credentials, authorization, production logs,
incident data, paid Providers, external webhooks, destructive data operations, release,
deployment or another privileged/external effect. XSS uses `xss-review.md` in addition.

## Secret and log boundary

- Never accept, print, persist or place plaintext secrets in prompts, Router state, tickets,
  reports, telemetry, errors or source control.
- Use KMS, Secret Manager or an authorized Tool Gateway. Agents receive only opaque alias/key
  ID, revision and sanitized result.
- Production logs are read-only, redacted and sanitized. Remove authorization headers, cookies,
  tokens, precise user location, regulated data and unrelated production records before an Agent
  can read them.
- A target project's detailed provider/log/incident rules live in its target-owned,
  target-versioned security boundary document.

## Input and webhook boundary

Servers revalidate and normalize all client input. External webhooks require signature
verification, replay/idempotency protection, rate limiting and fail-closed error behavior.
Public errors do not reveal internal reasons; structured internal diagnostics use sanitized,
stable reason codes.

## Effect authority

Secret access, paid Provider use, production diagnostics, administrative permission, data
deletion, migration, push, release, deployment, signing, publication and other irreversible or
external effects require a target SPEC/ticket plus explicit, scope-bound authority. An approved
implementation or review does not imply effect authority.

Before effect, bind exact owner, action, target, environment, receipt, baseline and correlation;
after effect, read back the exact result. Missing, replayed or mismatched evidence halts. Never
fallback from a denied/unavailable secure Provider to local plaintext handling.
