"""Public contracts for stable local identity resolution."""

from .identity_resolution import (
    DisplayLabel,
    IdentityDirectory,
    IdentityEnrollmentAccepted,
    IdentityEnrollmentRejected,
    IdentityEnrollmentRejectionReason,
    IdentityEnrollmentResult,
    IdentityRecord,
    IdentityResolution,
    IdentityUnknown,
    ResolvedIdentity,
    StableIdentityId,
    UNKNOWN_DISPLAY_LABEL,
)

__all__ = [
    "DisplayLabel",
    "IdentityDirectory",
    "IdentityEnrollmentAccepted",
    "IdentityEnrollmentRejected",
    "IdentityEnrollmentRejectionReason",
    "IdentityEnrollmentResult",
    "IdentityRecord",
    "IdentityResolution",
    "IdentityUnknown",
    "ResolvedIdentity",
    "StableIdentityId",
    "UNKNOWN_DISPLAY_LABEL",
]
