"""Pure local resolution of stable identities and safe display labels."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias


@dataclass(frozen=True, slots=True)
class StableIdentityId:
    """An opaque, stable identity key that is never inferred from a display label."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value.strip():
            raise ValueError("stable identity identifier must be a non-blank string")


@dataclass(frozen=True, slots=True)
class DisplayLabel:
    """A presentation-only label that has no authorization meaning."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value.strip():
            raise ValueError("display label must be a non-blank string")


UNKNOWN_DISPLAY_LABEL = DisplayLabel(value="Unknown")


@dataclass(frozen=True, slots=True)
class IdentityRecord:
    """One registered identity with an optional presentation label."""

    identity_id: StableIdentityId
    display_label: DisplayLabel | None

    def __post_init__(self) -> None:
        if not isinstance(self.identity_id, StableIdentityId):
            raise TypeError("identity_id must be a StableIdentityId")
        if self.display_label is not None and not isinstance(
            self.display_label, DisplayLabel
        ):
            raise TypeError("display_label must be a DisplayLabel or None")


class IdentityEnrollmentRejectionReason(str, Enum):
    """Finite reasons that prevent unsafe identity replacement."""

    STABLE_ID_ALREADY_REGISTERED = "stable_id_already_registered"


@dataclass(frozen=True, slots=True)
class IdentityEnrollmentAccepted:
    """One registered record and the next immutable identity directory."""

    directory: IdentityDirectory
    record: IdentityRecord

    def __post_init__(self) -> None:
        if not isinstance(self.directory, IdentityDirectory):
            raise TypeError("directory must be an IdentityDirectory")
        if not isinstance(self.record, IdentityRecord):
            raise TypeError("record must be an IdentityRecord")


@dataclass(frozen=True, slots=True)
class IdentityEnrollmentRejected:
    """A rejected enrollment that leaves the existing directory unchanged."""

    directory: IdentityDirectory
    reason: IdentityEnrollmentRejectionReason

    def __post_init__(self) -> None:
        if not isinstance(self.directory, IdentityDirectory):
            raise TypeError("directory must be an IdentityDirectory")
        if not isinstance(self.reason, IdentityEnrollmentRejectionReason):
            raise TypeError("reason must be an IdentityEnrollmentRejectionReason")


IdentityEnrollmentResult: TypeAlias = (
    IdentityEnrollmentAccepted | IdentityEnrollmentRejected
)


@dataclass(frozen=True, slots=True)
class ResolvedIdentity:
    """A known stable identity paired with a safe display label."""

    identity_id: StableIdentityId
    display_label: DisplayLabel

    def __post_init__(self) -> None:
        if not isinstance(self.identity_id, StableIdentityId):
            raise TypeError("identity_id must be a StableIdentityId")
        if not isinstance(self.display_label, DisplayLabel):
            raise TypeError("display_label must be a DisplayLabel")


@dataclass(frozen=True, slots=True)
class IdentityUnknown:
    """A fail-closed result for an identity never registered in this directory."""

    identity_id: StableIdentityId

    def __post_init__(self) -> None:
        if not isinstance(self.identity_id, StableIdentityId):
            raise TypeError("identity_id must be a StableIdentityId")


IdentityResolution: TypeAlias = ResolvedIdentity | IdentityUnknown


@dataclass(frozen=True, slots=True)
class IdentityDirectory:
    """An immutable local directory that never maps labels back to identities."""

    records: tuple[IdentityRecord, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.records, tuple):
            raise TypeError("records must be a tuple")
        _require_unique_identity_records(self.records)

    @classmethod
    def empty(cls) -> IdentityDirectory:
        """Create a directory with no implied identities or fallback enrollment."""
        no_records: tuple[IdentityRecord, ...] = ()
        return cls(records=no_records)

    def enroll(
        self,
        identity_id: StableIdentityId,
        display_label: DisplayLabel | None,
    ) -> IdentityEnrollmentResult:
        """Register an identity once; a later display label cannot replace it."""
        if not isinstance(identity_id, StableIdentityId):
            raise TypeError("identity_id must be a StableIdentityId")
        if display_label is not None and not isinstance(display_label, DisplayLabel):
            raise TypeError("display_label must be a DisplayLabel or None")
        if self._find_record(identity_id) is not None:
            return IdentityEnrollmentRejected(
                directory=self,
                reason=IdentityEnrollmentRejectionReason.STABLE_ID_ALREADY_REGISTERED,
            )
        record = IdentityRecord(
            identity_id=identity_id,
            display_label=display_label,
        )
        next_directory = IdentityDirectory(records=self.records + (record,))
        return IdentityEnrollmentAccepted(directory=next_directory, record=record)

    def resolve(self, identity_id: StableIdentityId) -> IdentityResolution:
        """Resolve only registered identities; unknown keys do not receive a label."""
        if not isinstance(identity_id, StableIdentityId):
            raise TypeError("identity_id must be a StableIdentityId")
        record = self._find_record(identity_id)
        if record is None:
            return IdentityUnknown(identity_id=identity_id)
        return ResolvedIdentity(
            identity_id=record.identity_id,
            display_label=_resolved_display_label(record.display_label),
        )

    def _find_record(self, identity_id: StableIdentityId) -> IdentityRecord | None:
        record: IdentityRecord
        for record in self.records:
            if record.identity_id == identity_id:
                return record
        return None


def _resolved_display_label(display_label: DisplayLabel | None) -> DisplayLabel:
    """Use a fixed, non-identifying presentation fallback when no label was supplied."""
    if display_label is None:
        return UNKNOWN_DISPLAY_LABEL
    return display_label


def _require_unique_identity_records(records: tuple[IdentityRecord, ...]) -> None:
    seen_identity_ids: tuple[StableIdentityId, ...] = ()
    record: IdentityRecord
    for record in records:
        if not isinstance(record, IdentityRecord):
            raise TypeError("records must contain IdentityRecord values")
        if record.identity_id in seen_identity_ids:
            raise ValueError("stable identity identifiers must be unique")
        seen_identity_ids += (record.identity_id,)
