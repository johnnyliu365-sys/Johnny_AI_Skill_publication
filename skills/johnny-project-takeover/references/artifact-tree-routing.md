# Artifact tree routing

Read this reference when creating, locating, partitioning or retiring formal project artifacts.
The purpose is bounded lookup: a root index identifies a branch, branch indexes identify their
direct children, and only the selected leaf contains working detail.

## Tree invariant

Every managed artifact belongs to exactly one rooted tree and has one stable opaque identifier.
Managed families include requirement/change, shared Context, ticket-scoped Agent Context, SPEC,
ticket, review, progress/handoff/evidence, ADR/security, archive-library and reusable-module
artifacts. Product source stays in its normal project source tree, but workflow records may point
to it only through an exact typed leaf reference.

An index node contains only metadata for its direct children: child ID, artifact kind, revision,
digest, lifecycle state and child-index or leaf reference. It must not copy child bodies,
descendant inventories, progress prose or chat history.

The Router resolves one path at a time:

```text
root index -> partition index -> feature/year/ticket index -> exact leaf
```

It must not recursively materialize the tree, scan unrelated siblings or persist a flattened
copy. A missing, ambiguous, cyclic, duplicate-parent, stale-revision or digest-mismatched edge is
`HALT / ARTIFACT_TREE_INVALID` before Agent, filesystem, Git or host effect.

## Lifecycle

- `ACTIVE` leaves remain reachable from the active tree.
- `CLOSED` ticket/Agent leaves are immutable evidence and are not input to a later ticket.
- `ARCHIVED` product requirements leave the active tree and become reachable only through the
  archive library's exact index path; current indexes keep only the archive identifier/reference,
  not a copy of the retired body.
- A replacement creates a new leaf/revision and updates one parent edge. It never edits a sealed
  or archived leaf in place.

Identifiers and references are clues, not copied context. Every consumer receives only the exact
path IDs needed to resolve its current leaf.

## Growth rule

Partition by meaning and ownership before a node starts mixing unrelated child kinds. Typical
partitions are feature, artifact kind, year, language or capability domain. No hard line/file
count is a quality gate; a node is split when one consumer would otherwise need to inspect
unrelated siblings or when different owners/lifecycles share one index.

This rule is recursive. Archive libraries and reusable-module libraries must have their own
bounded root and partition indexes as they grow. Moving a flat ledger or catalog into a directory
without direct-child indexes and exact-leaf routing does not satisfy this rule.
