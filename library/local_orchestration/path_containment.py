"""The one containment predicate every host-side port shares.

A second implementation of this rule is how a reparse-point evasion gets
reintroduced: the reviewed version already carries a base self-resolution
precheck that a fresh rewrite would omit. Import this; do not restate it.
"""

from __future__ import annotations

from pathlib import Path


def resolves_within_root(target: Path, base: Path) -> bool:
    """Reject a target whose own path or any ancestor redirects elsewhere.

    Checking only an existing leaf misses two cases: a not-yet-created leaf
    under a redirected parent, and a redirected ancestor above it. The nearest
    existing ancestor is therefore resolved and required to stay inside the
    resolved base, with the unresolved remainder appended unchanged.
    """

    try:
        resolved_base = base.resolve()
        if resolved_base != base:
            # The base itself redirects somewhere else; a containment check
            # anchored to the redirected location would be circular.
            return False
        existing = target
        remainder: list[str] = []
        while not existing.exists():
            if existing.parent == existing:
                return False
            remainder.append(existing.name)
            existing = existing.parent
        resolved = existing.resolve().joinpath(*reversed(remainder))
        return resolved == resolved_base or resolved_base in resolved.parents
    except OSError:
        return False


__all__ = ["resolves_within_root"]
