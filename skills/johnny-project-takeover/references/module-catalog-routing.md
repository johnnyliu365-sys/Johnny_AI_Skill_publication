# Reusable module catalog routing

Read this reference when maintaining or traversing Johnny's reusable source-module library.

`library/MODULE_CATALOG.md` is the root index, not a flat list of every module. It identifies
capability-domain child indexes. A domain index records only its direct module ID, lifecycle
status and exact README leaf. The selected leaf owns or points to the public contract,
dependencies, minimum reading path, prohibited uses and version/digest evidence required for
adoption.

Selection follows exactly one or more explicitly matched branches:

```text
MODULE_CATALOG -> capability domain -> exact README leaf -> public API -> exact contract
```

Do not load sibling domains or flatten every module into the root. Cross-domain dependencies are
opaque module-ID edges until selected. Cycles, missing leaves, duplicate IDs, conflicting status
or unresolvable dependencies fail closed and return to Wayfinder/Grill.

Partition by capability domain, then language/platform only when that distinction changes the
consumer's reading path. Do not split by arbitrary file/line thresholds.
