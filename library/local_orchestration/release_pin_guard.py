"""Prove the one-click wrapper points at the bundle a release actually built.

The wrapper carries two literals: the approved bundle's file name and its
SHA-256. Neither can be derived from the repository, because the bundle is a
build output. A release that bumps the version and forgets the wrapper ships a
wrapper that refuses the very artifact it was published beside, and the owner
sees `DIGEST_MISMATCH` on a correctly built bundle.

This module reads the wrapper as data and compares it to a built artifact. It
never rewrites the pin: a wrapper that edited itself to match whatever bundle
it was shown would defeat the approval it exists to enforce.
"""

from __future__ import annotations

import hashlib
import json
import re
from enum import Enum
from pathlib import Path
from typing import NamedTuple

_BUNDLE_NAME_PATTERN = re.compile(r'set "BUNDLE_NAME=([^"]+)"')
_DIGEST_PATTERN = re.compile(r'set "APPROVED_DIGEST=([0-9a-f]{64})"')
_READ_CHUNK = 1024 * 1024


class ReleasePinStatus(str, Enum):
    """Finite outcomes of one release-pin verification."""

    MATCHED = "MATCHED"
    REFUSED = "REFUSED"


class ReleasePinFailure(str, Enum):
    """Finite reasons a wrapper does not match the artifact it is shown."""

    WRAPPER_UNREADABLE = "WRAPPER_UNREADABLE"
    WRAPPER_PIN_MALFORMED = "WRAPPER_PIN_MALFORMED"
    BUNDLE_UNREADABLE = "BUNDLE_UNREADABLE"
    BUNDLE_NAME_MISMATCH = "BUNDLE_NAME_MISMATCH"
    DIGEST_MISMATCH = "DIGEST_MISMATCH"


class WrapperPin(NamedTuple):
    """Exactly what the wrapper declares approved."""

    bundle_name: str
    digest: str


def read_wrapper_pin(
    wrapper_path: Path,
) -> tuple[WrapperPin | None, ReleasePinFailure | None]:
    """Parse the wrapper's two pinned literals, or refuse."""

    try:
        body = wrapper_path.read_bytes().decode("ascii")
    except (OSError, UnicodeDecodeError):
        return None, ReleasePinFailure.WRAPPER_UNREADABLE
    name_match = _BUNDLE_NAME_PATTERN.search(body)
    digest_match = _DIGEST_PATTERN.search(body)
    if name_match is None or digest_match is None:
        return None, ReleasePinFailure.WRAPPER_PIN_MALFORMED
    return WrapperPin(name_match.group(1), digest_match.group(1)), None


def declared_plugin_version(
    plugin_manifest: Path,
) -> tuple[str | None, ReleasePinFailure | None]:
    """The single declared version every other name must agree with."""

    try:
        manifest = json.loads(plugin_manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, ReleasePinFailure.WRAPPER_UNREADABLE
    version = manifest.get("version") if isinstance(manifest, dict) else None
    if not isinstance(version, str) or not version:
        return None, ReleasePinFailure.WRAPPER_PIN_MALFORMED
    return version, None


def expected_bundle_name(version: str) -> str:
    """The one bundle file name a given plugin version may publish."""

    return f"johnny-ai-skill-{version}.zip"


def _digest_of(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(_READ_CHUNK):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def verify_release_pin(
    wrapper_path: Path, bundle_path: Path
) -> tuple[ReleasePinStatus, ReleasePinFailure | None]:
    """Prove the wrapper approves exactly this built bundle.

    Run this before publishing a release asset. A refusal means the wrapper
    and the bundle disagree, and shipping them together would hand the owner
    a refusal on a correctly built artifact.
    """

    pin, failure = read_wrapper_pin(wrapper_path)
    if pin is None:
        return ReleasePinStatus.REFUSED, failure
    if bundle_path.name != pin.bundle_name:
        return ReleasePinStatus.REFUSED, ReleasePinFailure.BUNDLE_NAME_MISMATCH
    actual = _digest_of(bundle_path)
    if actual is None:
        return ReleasePinStatus.REFUSED, ReleasePinFailure.BUNDLE_UNREADABLE
    if actual != pin.digest:
        return ReleasePinStatus.REFUSED, ReleasePinFailure.DIGEST_MISMATCH
    return ReleasePinStatus.MATCHED, None


__all__ = [
    "ReleasePinFailure",
    "ReleasePinStatus",
    "WrapperPin",
    "declared_plugin_version",
    "expected_bundle_name",
    "read_wrapper_pin",
    "verify_release_pin",
]
