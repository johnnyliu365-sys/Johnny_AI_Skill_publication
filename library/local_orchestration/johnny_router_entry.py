"""Johnny Router runtime entry.

This file ships inside the plugin payload and is copied to
`<johnny-root>/runtime/johnny_router_entry.py` at install time. It resolves
its own root from its location, exposes the plugin payload on `sys.path`,
and delegates every command to the typed live CLI inside the payload. It
performs no effect of its own.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _resolve_root() -> Path:
    return Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    root = _resolve_root()
    plugin_root = root / "plugin"
    if not plugin_root.is_dir():
        print('{"status":"CAPABILITY_UNAVAILABLE","code":"PLUGIN_PAYLOAD_MISSING"}')
        return 3
    sys.path.insert(0, str(plugin_root))
    try:
        from library.local_orchestration.johnny_live_cli import run_live_cli
    except ImportError:
        print('{"status":"CAPABILITY_UNAVAILABLE","code":"LIVE_CLI_MISSING"}')
        return 3
    return run_live_cli(
        tuple(sys.argv[1:] if argv is None else argv), johnny_root=root
    )


if __name__ == "__main__":
    raise SystemExit(main())
