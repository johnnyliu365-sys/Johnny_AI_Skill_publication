"""Pure admission of one explicitly supplied archive or module path."""

from __future__ import annotations

from .artifact_tree import ArtifactTreeResolver
from .contracts import (
    ArtifactTreeDecisionKind,
    ArtifactTreeFamily,
    ArtifactTreeLifecycle,
    LibrarySelectionDecision,
    LibrarySelectionDecisionKind,
    LibrarySelectionInvalidReason,
    LibrarySelectionKind,
    LibrarySelectionRequest,
)


class LibrarySelectionGate:
    """Validate one caller-selected library leaf without discovery or effects."""

    @staticmethod
    def validate(request: LibrarySelectionRequest) -> LibrarySelectionDecision:
        """Return a finite decision for the supplied metadata-only path."""

        selection = request.selection
        path = request.path
        expected_refs = (
            selection.root_ref,
            selection.partition_ref,
            selection.leaf_ref,
        )
        supplied_node_refs = tuple(node.node_ref for node in path.path_nodes)
        if (
            len(path.explicit_path_refs) != 3
            or len(path.path_nodes) != 3
            or path.root_ref != selection.root_ref
            or path.expected_leaf_ref != selection.leaf_ref
            or path.explicit_path_refs != expected_refs
            or supplied_node_refs != expected_refs
        ):
            return LibrarySelectionGate._invalid(
                request,
                LibrarySelectionInvalidReason.REQUEST_BINDING_MISMATCH,
            )

        if (
            selection.kind is not LibrarySelectionKind.ARCHIVE
            and selection.kind is not LibrarySelectionKind.REUSABLE_MODULE
        ):
            return LibrarySelectionGate._invalid(
                request,
                LibrarySelectionInvalidReason.FAMILY_MISMATCH,
            )
        expected_family, expected_lifecycle = LibrarySelectionGate._kind_contract(
            selection.kind
        )
        if path.family is not expected_family:
            return LibrarySelectionGate._invalid(
                request,
                LibrarySelectionInvalidReason.FAMILY_MISMATCH,
            )

        leaf_node = path.path_nodes[-1]
        if (
            selection.leaf_lifecycle is not expected_lifecycle
            or leaf_node.lifecycle is not expected_lifecycle
        ):
            return LibrarySelectionGate._invalid(
                request,
                LibrarySelectionInvalidReason.LEAF_LIFECYCLE_MISMATCH,
            )

        resolved = ArtifactTreeResolver.resolve(path)
        if resolved.decision is not ArtifactTreeDecisionKind.RESOLVED:
            return LibrarySelectionGate._invalid(
                request,
                LibrarySelectionInvalidReason.PATH_INVALID,
            )

        if (
            resolved.resolved_leaf_ref != selection.leaf_ref
            or leaf_node.node_ref != selection.leaf_ref
            or leaf_node.lifecycle is not selection.leaf_lifecycle
            or leaf_node.content_digest != selection.leaf_digest
        ):
            return LibrarySelectionGate._invalid(
                request,
                LibrarySelectionInvalidReason.LEAF_METADATA_MISMATCH,
            )

        return LibrarySelectionDecision(
            request_ref=request.request_ref,
            selection_ref=selection.selection_ref,
            decision=LibrarySelectionDecisionKind.SELECTED,
            invalid_reason=None,
            selected_leaf_ref=selection.leaf_ref,
        )

    @staticmethod
    def _kind_contract(
        kind: LibrarySelectionKind,
    ) -> tuple[ArtifactTreeFamily, ArtifactTreeLifecycle]:
        """Map each bounded selection kind to its only family and lifecycle."""

        if kind is LibrarySelectionKind.ARCHIVE:
            return ArtifactTreeFamily.ARCHIVE_LIBRARY, ArtifactTreeLifecycle.ARCHIVED
        return ArtifactTreeFamily.REUSABLE_MODULE, ArtifactTreeLifecycle.ACTIVE

    @staticmethod
    def _invalid(
        request: LibrarySelectionRequest,
        reason: LibrarySelectionInvalidReason,
    ) -> LibrarySelectionDecision:
        """Build one finite invalid result with no selected leaf."""

        return LibrarySelectionDecision(
            request_ref=request.request_ref,
            selection_ref=request.selection.selection_ref,
            decision=LibrarySelectionDecisionKind.LIBRARY_SELECTION_INVALID,
            invalid_reason=reason,
            selected_leaf_ref=None,
        )
