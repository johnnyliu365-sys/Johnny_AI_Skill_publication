"""Pure, bounded resolution of caller-selected workflow artifact-tree paths."""

from __future__ import annotations

from .contracts import (
    ArtifactTreeDecisionKind,
    ArtifactTreeFamily,
    ArtifactTreeInvalidReason,
    ArtifactTreeNode,
    ArtifactTreeNodeKind,
    ArtifactTreeResolutionDecision,
    ArtifactTreeResolutionRequest,
    OpaqueMetadataId,
)


class ArtifactTreeResolver:
    """Resolve one explicit metadata path without discovering sibling nodes."""

    @staticmethod
    def resolve(request: ArtifactTreeResolutionRequest) -> ArtifactTreeResolutionDecision:
        """Return the finite result for one caller-supplied artifact-tree path."""

        path_refs = request.explicit_path_refs
        path_nodes = request.path_nodes
        supplied_refs = tuple(node.node_ref for node in path_nodes)
        if len(supplied_refs) != len(set(supplied_refs)):
            return ArtifactTreeResolver._invalid(
                request,
                ArtifactTreeInvalidReason.DUPLICATE_NODE,
            )
        if (
            path_refs[0] != request.root_ref
            or path_refs[-1] != request.expected_leaf_ref
            or not ArtifactTreeResolver._supplied_nodes_preserve_path_order(path_refs, path_nodes)
        ):
            return ArtifactTreeResolver._invalid(
                request,
                ArtifactTreeInvalidReason.REQUEST_BINDING_MISMATCH,
            )
        if len(path_refs) != len(set(path_refs)) or ArtifactTreeResolver._has_ancestor_edge(path_nodes):
            return ArtifactTreeResolver._invalid(request, ArtifactTreeInvalidReason.CYCLE)
        if any(
            sum(node.node_ref == path_ref for node in path_nodes) != 1
            for path_ref in path_refs
        ):
            return ArtifactTreeResolver._invalid(
                request,
                ArtifactTreeInvalidReason.DANGLING_PATH_NODE,
            )
        if not ArtifactTreeResolver._kinds_are_path_shaped(path_nodes):
            return ArtifactTreeResolver._invalid(
                request,
                ArtifactTreeInvalidReason.KIND_TRANSITION,
            )
        if any(node.family is not request.family for node in path_nodes):
            return ArtifactTreeResolver._invalid(
                request,
                ArtifactTreeInvalidReason.FAMILY_MISMATCH,
            )
        if any(ArtifactTreeResolver._has_duplicate_child_refs(node) for node in path_nodes):
            return ArtifactTreeResolver._invalid(
                request,
                ArtifactTreeInvalidReason.DUPLICATE_CHILD,
            )
        if ArtifactTreeResolver._has_duplicate_parent_refs(path_refs, path_nodes):
            return ArtifactTreeResolver._invalid(
                request,
                ArtifactTreeInvalidReason.DUPLICATE_PARENT,
            )
        for parent, child in zip(path_nodes, path_nodes[1:]):
            matching_edges = tuple(
                edge for edge in parent.child_refs if edge.child_ref == child.node_ref
            )
            if not matching_edges:
                return ArtifactTreeResolver._not_found(request)
            if len(matching_edges) != 1:
                return ArtifactTreeResolver._invalid(
                    request,
                    ArtifactTreeInvalidReason.DUPLICATE_CHILD,
                )
            edge = matching_edges[0]
            if (
                edge.child_kind is not child.node_kind
                or edge.child_revision != child.revision
                or edge.child_digest != child.content_digest
                or edge.child_lifecycle is not child.lifecycle
            ):
                return ArtifactTreeResolver._invalid(
                    request,
                    ArtifactTreeInvalidReason.EDGE_METADATA_MISMATCH,
                )
        return ArtifactTreeResolutionDecision(
            request_ref=request.request_ref,
            family=request.family,
            decision=ArtifactTreeDecisionKind.RESOLVED,
            invalid_reason=None,
            resolved_leaf_ref=request.expected_leaf_ref,
        )

    @staticmethod
    def _supplied_nodes_preserve_path_order(
        path_refs: tuple[OpaqueMetadataId, ...],
        path_nodes: tuple[ArtifactTreeNode, ...],
    ) -> bool:
        """Require supplied nodes to be selected path members in the same order."""

        if any(node.node_ref not in path_refs for node in path_nodes):
            return False
        positions = tuple(path_refs.index(node.node_ref) for node in path_nodes)
        return all(left < right for left, right in zip(positions, positions[1:]))

    @staticmethod
    def _has_ancestor_edge(path_nodes: tuple[ArtifactTreeNode, ...]) -> bool:
        """Reject an edge from a supplied node back to itself or an earlier node."""

        for node_index, node in enumerate(path_nodes):
            ancestor_refs = tuple(
                ancestor.node_ref for ancestor in path_nodes[: node_index + 1]
            )
            if any(edge.child_ref in ancestor_refs for edge in node.child_refs):
                return True
        return False

    @staticmethod
    def _kinds_are_path_shaped(path_nodes: tuple[ArtifactTreeNode, ...]) -> bool:
        """Require root, partition and leaf roles in the supplied order."""

        for node_index, node in enumerate(path_nodes):
            expected_kind = (
                ArtifactTreeNodeKind.ROOT_INDEX
                if node_index == 0
                else (
                    ArtifactTreeNodeKind.LEAF
                    if node_index == len(path_nodes) - 1
                    else ArtifactTreeNodeKind.PARTITION_INDEX
                )
            )
            if node.node_kind is not expected_kind:
                return False
        return True

    @staticmethod
    def _has_duplicate_child_refs(node: ArtifactTreeNode) -> bool:
        """Reject repeated direct-child IDs owned by one supplied index."""

        child_refs = tuple(edge.child_ref for edge in node.child_refs)
        return len(child_refs) != len(set(child_refs))

    @staticmethod
    def _has_duplicate_parent_refs(
        path_refs: tuple[OpaqueMetadataId, ...],
        path_nodes: tuple[ArtifactTreeNode, ...],
    ) -> bool:
        """Reject a selected non-root node referenced by multiple supplied parents."""

        for path_ref in path_refs[1:]:
            parent_count = sum(
                any(edge.child_ref == path_ref for edge in node.child_refs)
                for node in path_nodes
            )
            if parent_count > 1:
                return True
        return False

    @staticmethod
    def _invalid(
        request: ArtifactTreeResolutionRequest,
        reason: ArtifactTreeInvalidReason,
    ) -> ArtifactTreeResolutionDecision:
        """Build one invalid-tree result without exposing a leaf."""

        return ArtifactTreeResolutionDecision(
            request_ref=request.request_ref,
            family=request.family,
            decision=ArtifactTreeDecisionKind.ARTIFACT_TREE_INVALID,
            invalid_reason=reason,
            resolved_leaf_ref=None,
        )

    @staticmethod
    def _not_found(
        request: ArtifactTreeResolutionRequest,
    ) -> ArtifactTreeResolutionDecision:
        """Build the sole missing-path result."""

        return ArtifactTreeResolutionDecision(
            request_ref=request.request_ref,
            family=request.family,
            decision=ArtifactTreeDecisionKind.ARTIFACT_PATH_NOT_FOUND,
            invalid_reason=ArtifactTreeInvalidReason.PATH_SEGMENT_MISSING,
            resolved_leaf_ref=None,
        )
