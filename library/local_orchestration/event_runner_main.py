"""Detached entry point for the per-project event runner.

The lifecycle port spawns exactly this module with `JOHNNY_ROOT` set, so the
runner resolves its own root the same way every other Johnny component does.
"""

from __future__ import annotations

from .event_runner import run_event_runner
from .johnny_root_layout import JohnnyRootLayout


def main() -> int:
    return run_event_runner(JohnnyRootLayout.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
