"""Register the Johnny skills with Antigravity, and take them away again.

Antigravity reads `skills.json` from a customization root and scans every
`entries[].path` for skill directories. Registration therefore adds one entry
pointing at the canonical `skills/` tree: no skill file is ever copied, so
there is exactly one source of truth and removal cannot orphan a stale copy.

The config file belongs to the user, not to Johnny. Every entry this port did
not add is preserved byte-for-byte, removal is idempotent, and a file Johnny
never created is never deleted.
"""

from __future__ import annotations

import json
import os
from enum import Enum
from pathlib import Path
from typing import Any


class SkillRegistrationStatus(str, Enum):
    """Finite outcomes of one registration or removal."""

    REGISTERED = "REGISTERED"
    ALREADY_REGISTERED = "ALREADY_REGISTERED"
    REMOVED = "REMOVED"
    NOT_REGISTERED = "NOT_REGISTERED"
    REFUSED = "REFUSED"


class SkillRegistrationFailure(str, Enum):
    """Finite reasons a registration or removal is refused."""

    SKILLS_DIRECTORY_ABSENT = "SKILLS_DIRECTORY_ABSENT"
    CONFIG_UNREADABLE = "CONFIG_UNREADABLE"
    CONFIG_NOT_AN_OBJECT = "CONFIG_NOT_AN_OBJECT"
    CONFIG_UNWRITABLE = "CONFIG_UNWRITABLE"


def default_customization_root() -> Path:
    """The per-user Antigravity customization root on this host."""

    override = os.environ.get("JOHNNY_ANTIGRAVITY_CONFIG_ROOT")
    if override:
        return Path(override)
    return Path.home() / ".gemini" / "config"


def skills_config_path(customization_root: Path) -> Path:
    return customization_root / "skills.json"


def _load(path: Path) -> tuple[dict[str, Any] | None, SkillRegistrationFailure | None]:
    if not path.exists():
        return {}, None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return None, SkillRegistrationFailure.CONFIG_UNREADABLE
    except ValueError:
        return None, SkillRegistrationFailure.CONFIG_NOT_AN_OBJECT
    if not isinstance(parsed, dict):
        return None, SkillRegistrationFailure.CONFIG_NOT_AN_OBJECT
    return parsed, None


def _entries(document: dict[str, Any]) -> list[Any]:
    existing = document.get("entries")
    return list(existing) if isinstance(existing, list) else []


def _same_path(entry: Any, wanted: Path) -> bool:
    if not isinstance(entry, dict):
        return False
    declared = entry.get("path")
    if not isinstance(declared, str):
        return False
    try:
        return Path(declared) == wanted or Path(declared).resolve() == wanted
    except OSError:
        return False


def _write(path: Path, document: dict[str, Any]) -> SkillRegistrationFailure | None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except OSError:
        return SkillRegistrationFailure.CONFIG_UNWRITABLE
    return None


def register_johnny_skills(
    customization_root: Path, skills_directory: Path
) -> tuple[SkillRegistrationStatus, SkillRegistrationFailure | None]:
    """Add one entry pointing at the canonical skills tree, exactly once."""

    if not skills_directory.is_dir():
        return (
            SkillRegistrationStatus.REFUSED,
            SkillRegistrationFailure.SKILLS_DIRECTORY_ABSENT,
        )
    resolved = skills_directory.resolve()
    path = skills_config_path(customization_root)
    document, failure = _load(path)
    if document is None:
        return SkillRegistrationStatus.REFUSED, failure

    entries = _entries(document)
    if any(_same_path(entry, resolved) for entry in entries):
        return SkillRegistrationStatus.ALREADY_REGISTERED, None

    entries.append({"path": str(resolved)})
    document["entries"] = entries
    write_failure = _write(path, document)
    if write_failure is not None:
        return SkillRegistrationStatus.REFUSED, write_failure
    return SkillRegistrationStatus.REGISTERED, None


def remove_johnny_skills(
    customization_root: Path, skills_directory: Path
) -> tuple[SkillRegistrationStatus, SkillRegistrationFailure | None]:
    """Take only Johnny's own entry away; never touch a foreign one."""

    path = skills_config_path(customization_root)
    if not path.exists():
        return SkillRegistrationStatus.NOT_REGISTERED, None
    resolved = skills_directory.resolve()
    document, failure = _load(path)
    if document is None:
        return SkillRegistrationStatus.REFUSED, failure

    entries = _entries(document)
    remaining = [entry for entry in entries if not _same_path(entry, resolved)]
    if len(remaining) == len(entries):
        return SkillRegistrationStatus.NOT_REGISTERED, None

    document["entries"] = remaining
    write_failure = _write(path, document)
    if write_failure is not None:
        return SkillRegistrationStatus.REFUSED, write_failure
    return SkillRegistrationStatus.REMOVED, None


__all__ = [
    "SkillRegistrationFailure",
    "SkillRegistrationStatus",
    "default_customization_root",
    "register_johnny_skills",
    "remove_johnny_skills",
    "skills_config_path",
]
