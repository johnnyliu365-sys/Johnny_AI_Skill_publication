---
name: apply-reusable-modules
description: Select the smallest safe set of Johnny AI Skill reusable source modules before planning or implementing a project capability. Use when a user asks to reuse, find, adopt, or avoid reimplementing shared text, payment, reliability, messaging, identity, event, engagement, or workflow-router modules, especially when reducing context/token use matters.
---

# Apply Reusable Modules

Use this skill as a selector. It does not authorize source copying, implementation, Provider access, or workflow bypass.

## Select before reading

1. Locate `library/MODULE_CATALOG.md` among this plugin's own installed files. If it is absent, request a versioned installation or repository path; do not reconstruct cards from memory.
2. Search that file for the user need and read only the matching card. Use its `ID`, public import, dependency and minimum reading path.
3. Select only delivered cards. If there is no explicit card, state the gap and use the target project's Wayfinder/Grill process; do not invent a near match.
4. Read each selected module in order: README, public `__init__.py`, then the exact contract or implementation named by the card. Read tests only when behavior or an integration boundary must be verified.
5. Load dependencies before dependents. Do not load sibling modules, whole categories or the whole library merely because they share a directory.

## Adopt safely

- Treat a card as a compact capability descriptor. Begin with its public import; do not import internal files directly unless the card requires it.
- Preserve the card and README's prohibited uses. Existing modules are local/fake cores, not authorization for payments, messages, databases, Secrets or production effects.
- Record selected module IDs, repository version/commit, public contracts used and rejected candidates in the target project's formal Context or ticket. Do not copy raw source into shared Context.
- Before modifying a target project, follow its `AGENTS.md` and `Workflow.md`. The catalog reduces context only; it never grants implementation authority.

## Compact selection report

```text
selected: <module-id>@<repository commit or version>
why: <explicit requirement matched by the card>
read: <README → public API → exact contract path>
dependency: <module IDs, if any>
boundary: <uses that remain outside the module>
```
