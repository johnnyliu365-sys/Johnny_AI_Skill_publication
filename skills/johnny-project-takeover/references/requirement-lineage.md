# Requirement lineage and archive library

Read this reference when creating, revising, superseding or locating a product requirement or
requirement change.

## One-to-one identity

Every product requirement has one matching change identifier with the same date/sequence suffix:

```text
PRD-YYYYMMDD-NNN <-> CHG-YYYYMMDD-NNN
```

The active `PRD.md` and `doc/RequirementChangeLog.md` are root indexes. They contain identifiers,
state and exact leaf references, not every requirement body. The canonical active leaf contains
the effective product statement, change decision and links to its Context/SPEC/ADR evidence.

## Retirement

When a requirement no longer applies, move the PRD/CHG pair out of the active tree into one
immutable archive bundle identified as `ARCH-REQ-YYYYMMDD-NNN`. The bundle records both retired
IDs, last active revision, reason, replacement IDs when any, and historical source commit.

Active PRD and change roots then retain only the archive bundle ID and its archive-tree reference.
They must not keep the retired requirement title/body, status narrative or replacement prose.
Git history remains evidence but is not the runtime lookup mechanism.

## Validation

- Active PRD and CHG suffixes must match and resolve to one active leaf.
- An active ID cannot also appear in an archive bundle.
- An archived pair cannot remain reachable through an active child edge.
- Archive roots list only direct partitions; year/category indexes list only direct archive
  bundles; bundle leaves contain the retired association.
- Duplicate, dangling, cyclic, wrong-revision or mixed active/archive references are
  `HALT / REQUIREMENT_LINEAGE_INVALID`.
